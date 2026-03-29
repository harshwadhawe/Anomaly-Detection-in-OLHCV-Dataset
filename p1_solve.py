#!/usr/bin/env python3
"""
Problem 1 — Order Book Concentration: SNIPER EDITION

- Activity Thresholds: Filters out 2:00 AM "dead book" False Positives.
- Forced Diversity: Selects only the top 2 extreme events per anomaly category.
- Strict HIGH Enforcement: Drops all MEDIUM/LOW noise to protect against -4 penalties.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
EQUITY = ROOT / "student-pack" / "equity"

logger = logging.getLogger("solve_p1")

BID_SIZE_COLS = [f"bid_size_level{i:02d}" for i in range(1, 11)]
ASK_SIZE_COLS = [f"ask_size_level{i:02d}" for i in range(1, 11)]
BID_PRICE_COLS = [f"bid_price_level{i:02d}" for i in range(1, 11)]
ASK_PRICE_COLS = [f"ask_price_level{i:02d}" for i in range(1, 11)]

@dataclass
class Alert:
    sec_id: int
    trade_date: str
    time_window_start: str
    anomaly_type: str
    severity: str
    remarks: str

def configure_logging(verbose: bool) -> None:
    logging.basicConfig(level=logging.INFO if verbose else logging.WARNING, format="%(asctime)s | %(message)s", force=True)

def load_market(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["timestamp"])
    for c in BID_SIZE_COLS + ASK_SIZE_COLS:
        if c in df.columns: df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    for c in BID_PRICE_COLS + ASK_PRICE_COLS:
        if c in df.columns: df[c] = pd.to_numeric(df[c], errors="coerce")
            
    df["total_bid"] = df[BID_SIZE_COLS].sum(axis=1)
    df["total_ask"] = df[ASK_SIZE_COLS].sum(axis=1)
    df["total_book"] = df["total_bid"] + df["total_ask"]
    
    den = df["total_book"]
    df["obi"] = np.where(den > 1e-9, (df["total_bid"] - df["total_ask"]) / den, 0.0)
    
    bp = df["bid_price_level01"].astype(float)
    ap = df["ask_price_level01"].astype(float)
    bs = df["bid_size_level01"].astype(float)
    as_ = df["ask_size_level01"].astype(float)
    
    df["wmp"] = np.where((bs + as_) > 1e-9, (bp * as_ + ap * bs) / (bs + as_), (bp + ap) / 2.0)
    df["spread_bps"] = np.where(bp > 1e-9, (ap - bp) / bp * 10000.0, np.nan)
    df["abs_spread"] = ap - bp
    
    tb = df["total_bid"].replace(0, np.nan)
    ta = df["total_ask"].replace(0, np.nan)
    df["bid_l1_conc"] = df["bid_size_level01"] / tb
    df["ask_l1_conc"] = df["ask_size_level01"] / ta
    
    df["bid_deep_conc"] = df[[f"bid_size_level{i:02d}" for i in range(2, 6)]].sum(axis=1) / tb
    df["ask_deep_conc"] = df[[f"ask_size_level{i:02d}" for i in range(2, 6)]].sum(axis=1) / ta

    df["trade_date"] = df["timestamp"].dt.strftime("%Y-%m-%d")
    df["dkey"] = df["timestamp"].dt.normalize()

    # Market hours filter: 09:00–17:00 (generous window around 09:30–16:00)
    t = df["timestamp"].dt.time
    df["is_market_hours"] = (t >= pd.to_datetime("09:00:00").time()) & (
        t <= pd.to_datetime("17:00:00").time()
    )
    return df.sort_values(["sec_id", "timestamp"]).reset_index(drop=True)

def add_rolling_zscores(m: pd.DataFrame) -> pd.DataFrame:
    m = m.sort_values(["sec_id", "timestamp"]).copy()
    gb = m.groupby(["sec_id", "dkey"], sort=False)
    
    mu_o = gb["obi"].transform(lambda s: s.shift(1).rolling(45, min_periods=12).mean())
    sd_o = gb["obi"].transform(lambda s: s.shift(1).rolling(45, min_periods=12).std())
    m["obi_z"] = ((m["obi"] - mu_o) / (sd_o.clip(lower=0.02))).clip(-8.0, 8.0)
    
    mu_s = gb["spread_bps"].transform(lambda s: s.shift(1).rolling(45, min_periods=12).mean())
    sd_s = gb["spread_bps"].transform(lambda s: s.shift(1).rolling(45, min_periods=12).std())
    m["spread_z"] = ((m["spread_bps"] - mu_s) / sd_s.clip(lower=3.0)).clip(-12.0, 12.0)
    m["obi_roll_abs"] = gb["obi"].transform(lambda s: s.abs().rolling(5, min_periods=3).mean())
    
    m["adv_bid"] = gb["total_bid"].transform("median")
    m["adv_ask"] = gb["total_ask"].transform("median")
    m["adv_book"] = gb["total_book"].transform("median")
    
    return m

def minute_clusters(ts: pd.Series, max_gap_min: int = 2) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    ts = pd.Series(ts.unique()).sort_values()
    if ts.empty: return []
    clusters = [[ts.iloc[0]]]
    for t in ts.iloc[1:]:
        if (t - clusters[-1][-1]).total_seconds() <= max_gap_min * 60: clusters[-1].append(t)
        else: clusters.append([t])
    return [(c[0], c[-1]) for c in clusters]

def market_anomaly_windows(m: pd.DataFrame) -> list:
    rows = []
    m = m.copy()
    
    # Must be market hours AND have at least 50% of normal daily liquidity
    is_active = m["is_market_hours"] & (m["total_book"] > (m["adv_book"] * 0.5))
    
    m["hot_obi"] = is_active & (m["obi"].abs() >= 0.70) & (m["obi_roll_abs"] >= 0.62) & (m["obi_z"].abs() >= 1.8)
    m["hot_spread"] = is_active & (m["spread_z"] >= 4.0) & (m["abs_spread"] > 0.02) & (m["spread_bps"] > m["spread_bps"].median() * 1.08)
    m["hot_bid_stack"] = is_active & ((m["bid_l1_conc"] >= 0.80) & (m["total_bid"] > m["adv_bid"] * 3) & (m["obi"] >= 0.45))
    m["hot_ask_stack"] = is_active & ((m["ask_l1_conc"] >= 0.80) & (m["total_ask"] > m["adv_ask"] * 3) & (m["obi"] <= -0.45))
    m["hot_bid_layering"] = is_active & ((m["bid_deep_conc"] >= 0.70) & (m["total_bid"] > m["adv_bid"] * 3) & (m["obi"] >= 0.45))
    m["hot_ask_layering"] = is_active & ((m["ask_deep_conc"] >= 0.70) & (m["total_ask"] > m["adv_ask"] * 3) & (m["obi"] <= -0.45))

    for (sec_id, _), g in m.groupby(["sec_id", "dkey"], sort=False):
        for mask_col, kind, min_len in (
            ("hot_obi", "order_book_imbalance_sustained", 4),
            ("hot_spread", "abnormal_spread_bps", 3),
            ("hot_bid_stack", "bid_depth_level01_concentration", 4),
            ("hot_ask_stack", "ask_depth_level01_concentration", 4),
            ("hot_bid_layering", "bid_layering_deep_book", 4),
            ("hot_ask_layering", "ask_layering_deep_book", 4),
        ):
            sub = g.loc[g[mask_col]].copy()
            if sub.empty: continue
            td = sub["trade_date"].iloc[0]
            for _a, _b in minute_clusters(sub["timestamp"]):
                chunk = sub[(sub["timestamp"] >= _a) & (sub["timestamp"] <= _b)]
                if len(chunk) < min_len: continue
                
                wstart = chunk["timestamp"].min()
                max_obi = float(chunk["obi"].abs().max())
                score = (float(chunk["spread_z"].max()) * 5) if mask_col == "hot_spread" else (max_obi * 15.0 + float(chunk["obi_z"].abs().max()))
                rows.append((sec_id, td, wstart, kind, score, max_obi, score))
    return rows

def cancel_burst_alerts(trades: pd.DataFrame, m_data: pd.DataFrame) -> list:
    c = trades[trades["order_status"].str.upper() == "CANCELLED"].copy()
    f = trades[trades["order_status"].str.upper() == "FILLED"].copy() 
    if c.empty: return []
    
    m_data_sorted = m_data[['sec_id', 'timestamp', 'wmp']].sort_values('timestamp')
    out = []
    span = pd.Timedelta(minutes=12)
    
    for (sec_id, tid), g in c.groupby(["sec_id", "trader_id"]):
        g = g.sort_values("timestamp")
        best_n, best_t0, best_t1 = 0, None, None
        
        for t0 in g["timestamp"]:
            t1 = t0 + span
            n = int(((g["timestamp"] >= t0) & (g["timestamp"] <= t1)).sum())
            if n > best_n: best_n, best_t0, best_t1 = n, pd.Timestamp(t0), t1
                
        if best_t0 is not None and best_n >= 5: # Raised minimum cancels to 5
            fills = f[(f["sec_id"] == sec_id) & (f["trader_id"] == tid) & (f["timestamp"] >= best_t0) & (f["timestamp"] <= best_t1)]
            if not fills.empty and len(fills) >= (best_n * 0.1): continue 
            
            score = float(best_n) * 3.0
            td = best_t0.strftime("%Y-%m-%d")
            
            sec_m = m_data_sorted[m_data_sorted['sec_id'] == sec_id]
            wmp_start = sec_m[sec_m['timestamp'] >= best_t0]['wmp'].iloc[0] if not sec_m[sec_m['timestamp'] >= best_t0].empty else None
            wmp_end = sec_m[sec_m['timestamp'] >= best_t1]['wmp'].iloc[0] if not sec_m[sec_m['timestamp'] >= best_t1].empty else None
            
            kind = "cancel_burst_same_trader"
            if wmp_start and wmp_end and (abs(wmp_start - wmp_end) / wmp_start < 0.0005):
                kind = "cancel_burst_no_price_impact"
                score += 15.0 
            out.append((int(sec_id), td, best_t0, kind, score, float(best_n)))
    return out

def severity_from_score(kind: str, score: float, max_obi: float, extra: float) -> str:
    if kind == "cancel_burst_no_price_impact" and extra >= 6: return "HIGH"
    if kind == "abnormal_spread_bps" and extra >= 25.0: return "HIGH"
    if max_obi >= 0.88 or score >= 28.0: return "HIGH"
    return "LOW"

def main() -> None:
    t0 = time.perf_counter()
    parser = argparse.ArgumentParser()
    parser.add_argument("-o", "--output", type=Path, default=ROOT / "p1_alerts.csv")
    args = parser.parse_args()
    configure_logging(True)

    m = load_market(EQUITY / "market_data.csv")
    m = add_rolling_zscores(m)
    raw = market_anomaly_windows(m)
    
    trades = pd.read_csv(EQUITY / "trade_data.csv", parse_dates=["timestamp"])
    raw_cb = cancel_burst_alerts(trades, m)

    combined = list(raw)
    for sec_id, td, wstart, kind, score, n in raw_cb:
        combined.append((sec_id, td, wstart, kind, score, 0.0, n))

    # Sort by highest score to prioritize the biggest anomalies
    combined.sort(key=lambda x: -x[4])

    # Deduplicate: keep only the best-scoring alert per (sec_id, trade_date)
    best_per_key: dict[tuple, tuple] = {}
    for row in combined:
        key = (row[0], row[1])  # (sec_id, trade_date)
        if key not in best_per_key or row[4] > best_per_key[key][4]:
            best_per_key[key] = row
    deduped = sorted(best_per_key.values(), key=lambda x: -x[4])

    # Force Diversity: max 2 alerts of each anomaly type
    seen_kinds: dict[str, int] = {}
    diverse_alerts = []
    for row in deduped:
        kind = row[3]
        if seen_kinds.get(kind, 0) < 2:
            diverse_alerts.append(row)
            seen_kinds[kind] = seen_kinds.get(kind, 0) + 1

    # RELAXED CAP: Allow the diversity grid to breathe. 
    # If the math proves they are HIGH severity, submit them.
    diverse_alerts = diverse_alerts[:15]

    alerts = []
    for sec_id, td, wstart, kind, score, max_obi, extra in diverse_alerts:
        sev = severity_from_score(kind, score, max_obi, extra)
        
        # STRICT ENFORCEMENT: If it isn't an undeniable HIGH, throw it out.
        if sev != "HIGH": continue
            
        if "cancel_burst" in kind: rem = f"sec_id={sec_id}: {int(extra)} CANCELLED equity orders from same trader_id within ~12 mins starting {wstart.strftime('%H:%M')}; spoofing signature."
        elif kind == "abnormal_spread_bps": rem = f"sec_id={sec_id}: bid/ask spread elevated vs baseline (max spread z≈{extra:.1f}) starting {wstart.strftime('%H:%M:%S')}."
        elif "concentration" in kind: rem = f"sec_id={sec_id}: level-01 size dominates book (>{int(max_obi*100)}% total depth) from {wstart.strftime('%H:%M:%S')} — spoofing concentration."
        else: rem = f"sec_id={sec_id}: heavy volume detected in deeper order book levels (2-5) starting {wstart.strftime('%H:%M:%S')}. Indicates potential layering."
            
        alerts.append(Alert(sec_id, td, wstart.strftime("%H:%M:%S"), kind, sev, rem))

    out = pd.DataFrame([a.__dict__ for a in alerts])
    if not out.empty:
        out.insert(0, "alert_id", range(1, len(out) + 1))
        out["time_to_run"] = round(time.perf_counter() - t0, 3)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.output, index=False)
    print(f"solve_p1: wrote {len(out)} HIGH-SEVERITY alerts -> {args.output}")

if __name__ == "__main__":
    main()