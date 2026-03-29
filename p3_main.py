#!/usr/bin/env python3
"""
Problem 3 — Crypto Blind Anomaly Hunt: vectorized detection pipeline.
Reads student-pack crypto CSVs; writes submission.csv at repo root.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from p3_utils import (
    AML_STRUCT_BAND_HI, AML_STRUCT_BAND_LO, BTC_ETH_IF_TOP_K, COORD_MIN_AGG_NOTIONAL, COORD_MIN_WALLETS,
    COORD_TOP_N_PER_MINUTE, CROSS_TOP_N_PER_HOT_MINUTE, DEFAULT_MAX_SUBMISSION_ROWS, Flag, IF_CONTAMINATION,
    IF_TOP_K_PER_SYMBOL, PUMP_TOP_N_PER_HOT_MINUTE, ROOT, ROUND_TRIP_MAX_REL_SPREAD, ROUND_TRIP_MAX_UNIQUE_TRADES,
    ROUND_TRIP_MIN_NOTIONAL_PAIR, SYMBOLS, StepTiming, attach_bar_features, configure_logging, load_market_frames,
    load_trades_all, log_data_snapshot, log_detector_counts, log_pipeline, log_submission_accuracy_review,
    merge_flags, run_timed, trim_submission,
)

logger = logging.getLogger("solve_p3")

# --- Detectors ---

def detect_peg_usdc(trades: pd.DataFrame) -> list[Flag]:
    out: list[Flag] = []
    sub = trades[trades["symbol"] == "USDCUSDT"].copy()
    mask = (sub["price"].astype(float) - 1.0).abs() > 0.005
    hit = sub[mask].copy()
    
    # ANTI-FLOOD GATE: Only take the first 5 de-pegged trades per day.
    # This is enough to prove the peg broke without crowding the submission.
    hit = hit.groupby("date").head(5)
    
    for _, r in hit.iterrows():
        out.append(Flag(r["symbol"], r["date"], r["trade_id"], "peg_break", "abs(price-1.0) > 0.005 per Problem 3 peg-break rule"))
    return out

def detect_batusdt_hourly_spikes(trades: pd.DataFrame) -> list[Flag]:
    out: list[Flag] = []
    bat = trades[trades["symbol"] == "BATUSDT"].copy()
    if bat.empty: return out
    bat["hour"] = bat["timestamp"].dt.floor("h")
    hourly = bat.groupby(["date", "hour"], as_index=False)["notional"].sum().rename(columns={"notional": "hourly_usdt"})
    med_by_day = hourly.groupby("date")["hourly_usdt"].transform("median")
    hourly["ratio"] = hourly["hourly_usdt"] / med_by_day.replace(0, np.nan)
    hot_hours = hourly[((hourly["ratio"] >= 5.0) & (hourly["hourly_usdt"] > 8.0)) | ((med_by_day <= 1e-9) & (hourly["hourly_usdt"] > 8.0))]

    for _, h in hot_hours.iterrows():
        block = bat[bat["hour"] == h["hour"]]
        rt = h["ratio"]
        ratio_txt = f"{rt:.1f}x" if pd.notna(rt) else "n/a (zero-median day)"
        for _, r in block.iterrows():
            out.append(Flag(r["symbol"], r["date"], r["trade_id"], "aml_structuring", f"BATUSDT hourly notional {h['hourly_usdt']:.0f} vs median ({ratio_txt})"))
    return out

def detect_wash_same_wallet(trades: pd.DataFrame) -> list[Flag]:
    out: list[Flag] = []
    for sym in SYMBOLS:
        sub = trades[trades["symbol"] == sym].copy()
        if len(sub) < 4: continue
        sub = sub.sort_values(["wallet", "timestamp"])
        for _, g in sub.groupby("wallet", sort=False):
            if len(g) < 4: continue
            g = g.set_index("timestamp").sort_index()
            signed = g["signed_notional"]
            abss = signed.abs()
            roll_net = signed.rolling("8min", min_periods=2).sum()
            roll_gross = abss.rolling("8min", min_periods=2).sum()
            roll_buy = (g["side"] == "BUY").astype(float).rolling("8min", min_periods=2).sum()
            roll_sell = (g["side"] == "SELL").astype(float).rolling("8min", min_periods=2).sum()
            mask = ((roll_gross > 1200.0) & (roll_net.abs() < 0.10 * roll_gross) & (roll_buy >= 1) & (roll_sell >= 1))
            hit = g[mask.fillna(False)].reset_index()
            for _, r in hit.iterrows():
                out.append(Flag(sym, r["date"], r["trade_id"], "wash_trading", "8m rolling net USDT near zero vs gross; both sides; same wallet"))
    return out

def detect_round_trip_two_wallets(trades: pd.DataFrame) -> list[Flag]:
    candidates: list[tuple[float, float, str, str, str, str, str]] = []
    for sym in SYMBOLS:
        sub = trades[trades["symbol"] == sym].copy().sort_values("timestamp")
        if len(sub) < 4: continue
        ts, w, side, tid, dates, price, qty = sub["timestamp"].values, sub["wallet"].values, sub["side"].values, sub["trade_id"].values, sub["date"].values, sub["price"].astype(float).values, sub["quantity"].astype(float).values
        n = len(sub)
        for i in range(n):
            tmax = ts[i] + np.timedelta64(300, "s")
            j_end = int(np.searchsorted(ts, tmax, side="right"))
            for j in range(i + 1, min(j_end, n)):
                if w[i] == w[j] or side[i] == side[j]: continue
                pavg = (price[i] + price[j]) / 2.0
                if pavg <= 0: continue
                rel_spread = abs(price[i] - price[j]) / pavg
                notional_ij = price[i] * qty[i] + price[j] * qty[j]
                if rel_spread < ROUND_TRIP_MAX_REL_SPREAD and notional_ij > ROUND_TRIP_MIN_NOTIONAL_PAIR:
                    candidates.append((notional_ij, rel_spread, sym, str(tid[i]), str(tid[j]), str(dates[i]), str(dates[j])))
    candidates.sort(key=lambda x: -x[0])
    used, picked = set(), []
    for tup in candidates:
        notional_ij, rel_spread, sym, tid_i, tid_j, d_i, d_j = tup
        if tid_i in used or tid_j in used: continue
        used.update([tid_i, tid_j])
        picked.append((sym, tid_i, tid_j, d_i, d_j))
        if len(used) >= ROUND_TRIP_MAX_UNIQUE_TRADES: break
    
    idx = trades.set_index("trade_id", drop=False)
    out: list[Flag] = []
    for sym, tid_i, tid_j, d_i, d_j in picked:
        for tid, day in ((tid_i, d_i), (tid_j, d_j)):
            if tid in idx.index:
                r = idx.loc[tid].iloc[0] if isinstance(idx.loc[tid], pd.DataFrame) else idx.loc[tid]
                out.append(Flag(str(r["symbol"]), str(r["date"]), str(r["trade_id"]), "round_trip_wash", "Greedy high-notional reciprocal pair within 5m"))
    return out

def detect_usdc_wash_volume_at_peg(trades: pd.DataFrame) -> list[Flag]:
    sub = trades[trades["symbol"] == "USDCUSDT"].copy()
    sub = sub.loc[(sub["price"].astype(float) - 1.0).abs() <= 0.001]
    if len(sub) < 4: return []
    out: list[Flag] = []
    sub = sub.sort_values(["wallet", "timestamp"])
    for _, g in sub.groupby("wallet", sort=False):
        if len(g) < 4: continue
        g = g.set_index("timestamp").sort_index()
        signed, abss = g["signed_notional"], g["signed_notional"].abs()
        roll_net, roll_gross = signed.rolling("8min", min_periods=2).sum(), abss.rolling("8min", min_periods=2).sum()
        roll_buy, roll_sell = (g["side"] == "BUY").astype(float).rolling("8min", min_periods=2).sum(), (g["side"] == "SELL").astype(float).rolling("8min", min_periods=2).sum()
        mask = ((roll_gross > 900.0) & (roll_net.abs() < 0.12 * roll_gross) & (roll_buy >= 1) & (roll_sell >= 1))
        hit = g[mask.fillna(False)].reset_index()
        for _, r in hit.iterrows():
            out.append(Flag("USDCUSDT", r["date"], r["trade_id"], "wash_volume_at_peg", "On-peg USDC (~$1) with 8m rolling net small vs gross"))
    return out

def detect_aml_structuring(trades: pd.DataFrame) -> list[Flag]:
    in_band = (trades["notional"] >= AML_STRUCT_BAND_LO) & (trades["notional"] <= AML_STRUCT_BAND_HI)
    n_in_band = trades.assign(_in_band=in_band).groupby(["symbol", "wallet", "date"], sort=False)["_in_band"].transform("sum")
    
    # STRICTER GATE: Raised from >= 2 to >= 4 to eliminate BTC/ETH natural noise
    hit = trades.loc[in_band & (n_in_band >= 4), ["symbol", "date", "trade_id"]]
    
    return [Flag(str(sym), str(d), str(tid), "aml_structuring", "4+ trades with notional in smurfing band same wallet/day") for sym, d, tid in zip(hit["symbol"], hit["date"], hit["trade_id"])]

def detect_coordinated_structuring(trades: pd.DataFrame) -> list[Flag]:
    in_band = (trades["notional"] >= AML_STRUCT_BAND_LO) & (trades["notional"] <= AML_STRUCT_BAND_HI)
    hit_rows = trades.loc[in_band].copy()
    out: list[Flag] = []
    for (sym, day), grp in hit_rows.groupby(["symbol", "date"], sort=False):
        if len(grp.groupby("wallet").size()) >= 3 and len(grp) >= 6:
            for _, r in grp.iterrows():
                out.append(Flag(str(sym), str(day), str(r["trade_id"]), "coordinated_structuring", "≥3 wallets and ≥6 trades in smurfing band same day"))
    return out

def detect_manager_consolidation(trades: pd.DataFrame) -> list[Flag]:
    t = trades[trades["manager_id"].astype(str).str.strip().str.len() > 0].copy()
    out: list[Flag] = []
    for (sym, mgr), g in t.groupby(["symbol", "manager_id"], sort=False):
        g = g.sort_values("timestamp")
        ts, n, tid, dates = g["timestamp"].values, g["notional"].astype(float).values, g["trade_id"].values, g["date"].values
        for i in range(len(g)):
            if n[i] < 25_000.0: continue
            prev = g.loc[(g["timestamp"] < ts[i]) & (g["timestamp"] >= ts[i] - pd.Timedelta("72h"))]
            if (prev["notional"].astype(float) < 9_000.0).sum() >= 6:
                out.append(Flag(str(sym), str(dates[i]), str(tid[i]), "manager_consolidation", "manager_id activity: large notional after multiple small legs"))
    return out

def detect_placement_smurfing(trades: pd.DataFrame) -> list[Flag]:
    t = trades.sort_values("timestamp")
    first = t.groupby(["symbol", "wallet"], sort=False).head(1)
    first = first[(first["notional"] >= 400.0) & (first["notional"] <= 3_500.0)]
    cnt = first.groupby(["symbol", "date"]).size()
    out: list[Flag] = []
    for sym, day in cnt[cnt >= 20].index:
        for _, r in first[(first["symbol"] == sym) & (first["date"] == day)].iterrows():
            out.append(Flag(str(sym), str(day), str(r["trade_id"]), "placement_smurfing", "First-appearance trade on symbol; ≥20 wallets same day"))
    return out

def detect_ramping(trades: pd.DataFrame) -> list[Flag]:
    out: list[Flag] = []
    for sym in SYMBOLS:
        sub = trades[trades["symbol"] == sym].sort_values(["wallet", "timestamp"])
        for w, g in sub.groupby("wallet", sort=False):
            if len(g) < 5: continue
            g = g.reset_index(drop=True)
            ts, prices, sides, tids, dates = g["timestamp"].values, g["price"].astype(float).values, g["side"].values, g["trade_id"].values, g["date"].values
            n, i = len(g), 0
            while i < n - 4:
                j = i
                while j < n and (ts[j] - ts[i]) / np.timedelta64(1, 'm') <= 35: j += 1
                if j - i >= 5:
                    w_sides, w_prices = sides[i:j], prices[i:j]
                    dom_side = "BUY" if (w_sides == "BUY").sum() >= (w_sides == "SELL").sum() else "SELL"
                    dom_count = (w_sides == dom_side).sum()
                    
                    if dom_count / (j - i) >= 0.70 and dom_count >= 5:
                        dom_prices = w_prices[w_sides == dom_side]
                        diffs = np.diff(dom_prices)
                        price_impact = abs(dom_prices[-1] - dom_prices[0]) / dom_prices[0]
                        
                        if price_impact >= 0.0015:
                            if dom_side == "BUY" and (diffs >= 0).mean() >= 0.80 and dom_prices[-1] > dom_prices[0]:
                                for k in range(i, j):
                                    if sides[k] == dom_side: out.append(Flag(sym, str(dates[k]), str(tids[k]), "ramping", "Wallet window >=70% BUY with monotonic rising prices"))
                                i = j - 1
                            elif dom_side == "SELL" and (diffs <= 0).mean() >= 0.80 and dom_prices[-1] < dom_prices[0]:
                                for k in range(i, j):
                                    if sides[k] == dom_side: out.append(Flag(sym, str(dates[k]), str(tids[k]), "ramping", "Wallet window >=70% SELL with monotonic falling prices"))
                                i = j - 1
                i += 1
    return out

def detect_layering_echo(trades: pd.DataFrame) -> list[Flag]:
    out: list[Flag] = []
    for sym in SYMBOLS:
        for _, g in trades[trades["symbol"] == sym].sort_values("timestamp").groupby("wallet"):
            if len(g) < 6: continue
            g = g.set_index("timestamp").sort_index()
            roll = g["signed_notional"]
            rg, rn = roll.abs().rolling("480s", min_periods=6).sum(), roll.rolling("480s", min_periods=6).sum()
            
            # NEW: Calculate price push (max - min) in the 8m window
            p_max = g["price"].astype(float).rolling("480s", min_periods=6).max()
            p_min = g["price"].astype(float).rolling("480s", min_periods=6).min()
            price_push_bps = (p_max - p_min) / g["price"].astype(float)
            
            # GATE: Must have high volume, zero net, AND push the price > 20 bps (0.002)
            mask = (rg > 5000) & (rn.abs() < 0.08 * rg) & (price_push_bps > 0.002)
            
            for _, r in g[mask.fillna(False)].reset_index().iterrows():
                out.append(Flag(sym, r["date"], r["trade_id"], "layering_echo", "8m rolling: massive gross, zero net, WITH >20bps price push"))
    return out

def detect_pump_dump(trades: pd.DataFrame, market: dict[str, pd.DataFrame]) -> list[Flag]:
    out: list[Flag] = []
    for sym in SYMBOLS:
        m = market[sym].copy().sort_values("Date")
        if len(m) < 120: continue
        close = m["Close"].astype(float)
        ret60, ret30_fwd = close.pct_change(60), close.shift(-30) / close - 1.0
        
        # STRICTER GATES: 2.5% up, 2.0% down. Filters out normal crypto beta.
        pump_end = (ret60 > 0.025) & (ret30_fwd < -0.020)
        hot_times = set(m.loc[pump_end.fillna(False), "Date"])
        
        if not hot_times: continue
        t = trades[trades["symbol"] == sym].copy()
        t["minute"] = t["timestamp"].dt.floor("min")
        t = t[t["minute"].isin(hot_times)]
        
        for _, g in t.groupby("minute", sort=False):
            for _, r in g.nlargest(PUMP_TOP_N_PER_HOT_MINUTE, "notional").iterrows():
                out.append(Flag(sym, r["date"], r["trade_id"], "pump_and_dump", "Top-notional trades in severe OHLCV pump minute (>2.5% up, >2.0% reversal)"))
    return out

def detect_cross_pair_divergence(trades: pd.DataFrame, market: dict[str, pd.DataFrame]) -> list[Flag]:
    out: list[Flag] = []
    btc = market["BTCUSDT"].set_index("Date")["ret_1m"].rename("btc_ret")
    for sym in SYMBOLS:
        if sym == "BTCUSDT": continue
        m = market[sym].set_index("Date")
        al = m["ret_1m"].rename("alt_ret")
        joined = pd.concat([btc, al], axis=1).dropna()
        joined["div"] = (joined["alt_ret"] - joined["btc_ret"]).abs()
        
        # GATE: Require >250 bps divergence
        hot = set(joined[joined["div"] > 0.025].index)
        
        if not hot: continue
        t = trades[trades["symbol"] == sym].copy()
        t["minute"] = t["timestamp"].dt.floor("min")
        for _, g in t[t["minute"].isin(hot)].groupby("minute", sort=False):
            for _, r in g.nlargest(CROSS_TOP_N_PER_HOT_MINUTE, "notional").iterrows():
                out.append(Flag(sym, r["date"], r["trade_id"], "cross_pair_divergence", "Top-notional trades in minute with >250 bps 1m divergence vs BTC"))
    return out

def detect_coordinated_pump(trades: pd.DataFrame, market: dict[str, pd.DataFrame]) -> list[Flag]:
    out: list[Flag] = []
    t = trades[trades["side"] == "BUY"].copy()
    t["minute"] = t["timestamp"].dt.floor("min")
    for (sym, minute), grp in t.groupby(["symbol", "minute"]):
        if grp["wallet"].nunique() < COORD_MIN_WALLETS or grp["notional"].sum() < COORD_MIN_AGG_NOTIONAL: continue
        mdf = market.get(sym)
        tc_col = next((c for c in (mdf.columns if mdf is not None else []) if str(c).lower() == "tradecount"), None)
        if mdf is not None and tc_col is not None:
            bar = mdf[mdf["Date"] == pd.Timestamp(minute)]
            if not bar.empty:
                hist = mdf[mdf["Date"] <= pd.Timestamp(minute)].tail(120)[tc_col].astype(float)
                med = float(hist.median()) if len(hist) else 0.0
                if med > 0 and float(bar[tc_col].iloc[0]) < max(20.0, 1.35 * med): continue
        for _, r in grp.nlargest(COORD_TOP_N_PER_MINUTE, "notional").iterrows():
            out.append(Flag(sym, r["date"], r["trade_id"], "coordinated_pump", ">=3 wallets BUY same minute; agg>=15k USDT; 1m bar tradecount elevated"))
    return out

def detect_threshold_testing(trades: pd.DataFrame) -> list[Flag]:
    out: list[Flag] = []
    for sym in SYMBOLS:
        for w, g in trades[trades["symbol"] == sym].sort_values("timestamp").groupby("wallet"):
            g = g.sort_values("timestamp")
            for _, pr in g[(g["notional"] >= 9970) & (g["notional"] <= 10040)].iterrows():
                sm = g[(g["timestamp"] >= pr["timestamp"] - pd.Timedelta("72h")) & (g["timestamp"] <= pr["timestamp"] + pd.Timedelta("72h")) & (g["notional"] >= 8200.0) & (g["notional"] < 9980.0)]
                if len(sm) >= 2:
                    for _, r in sm.iterrows():
                        out.append(Flag(sym, r["date"], r["trade_id"], "threshold_testing", "Probe-sized trade near 10k USDT with companion sub-threshold notionals"))
    return out

def detect_chain_layering(trades: pd.DataFrame) -> list[Flag]:
    out: list[Flag] = []
    for sym in SYMBOLS:
        sub = trades[trades["symbol"] == sym].sort_values("timestamp")
        if len(sub) < 3: continue
        ts, w, side, q, tid, dates = sub["timestamp"].values, sub["wallet"].values, sub["side"].values, sub["quantity"].astype(float).values, sub["trade_id"].values, sub["date"].values
        for i in range(len(sub) - 2):
            if (ts[i + 2] - ts[i]) / np.timedelta64(1, "s") > 900 or len({w[i], w[i + 1], w[i + 2]}) < 3 or side[i] != "SELL" or side[i + 1] != "SELL" or side[i + 2] != "SELL": continue
            m = (q[i] + q[i + 1] + q[i + 2]) / 3.0
            if m <= 0 or max(abs(q[i] - q[i + 1]), abs(q[i + 1] - q[i + 2]), abs(q[i] - q[i + 2])) / m > 0.06: continue
            for k in range(3): out.append(Flag(sym, str(dates[i + k]), str(tid[i + k]), "chain_layering", "Three distinct wallets sequential SELL similar qty within 15m"))
    return out

def detect_isolation_forest(trades_feat: pd.DataFrame) -> list[Flag]:
    out: list[Flag] = []
    for sym in ["SOLUSDT", "DOGEUSDT", "LTCUSDT"]:
        sub = trades_feat[trades_feat["symbol"] == sym].copy()
        if len(sub) < 40: continue
        sub["qty_z"] = sub.groupby("date")["quantity"].transform(lambda x: (x - x.mean()) / (x.std() + 1e-9))
        sub["wallet_day_ct"] = sub.groupby(["wallet", "date"])["trade_id"].transform("count")
        X = sub[["qty_z", "dev_from_mid", "wallet_day_ct", "notional"]].replace([np.inf, -np.inf], np.nan).fillna(0.0).values
        iso = IsolationForest(n_estimators=200, contamination=IF_CONTAMINATION, random_state=42, n_jobs=-1)
        pred, scores = iso.fit_predict(X), iso.score_samples(X)
        sub = sub.assign(_if_score=scores)
        
        # GATE: Must be an IF outlier AND structurally massive (> 3.0 standard deviations)
        take = sub[(pred == -1) & (sub['qty_z'] > 3.0)]
        if len(take) > IF_TOP_K_PER_SYMBOL: take = take.nsmallest(IF_TOP_K_PER_SYMBOL, "_if_score")
        for _, r in take.iterrows(): out.append(Flag(sym, r["date"], r["trade_id"], "spoofing", "IsolationForest outlier (qty_z > 3.0 gate)"))
    return out

def detect_xrp_eod_if(trades_feat: pd.DataFrame) -> list[Flag]:
    sym = "XRPUSDT"
    sub = trades_feat[trades_feat["symbol"] == sym].copy()
    h = sub["timestamp"].dt.hour
    sub = sub.loc[(h == 23) | (h == 0)].copy()
    if len(sub) < 12: return []
    sub["qty_z"] = sub.groupby("date")["quantity"].transform(lambda x: (x - x.mean()) / (x.std() + 1e-9))
    sub["wallet_day_ct"] = sub.groupby(["wallet", "date"])["trade_id"].transform("count")
    X = sub[["qty_z", "dev_from_mid", "wallet_day_ct", "notional"]].replace([np.inf, -np.inf], np.nan).fillna(0.0).values
    iso = IsolationForest(n_estimators=200, contamination=IF_CONTAMINATION, random_state=44, n_jobs=-1)
    pred, scores = iso.fit_predict(X), iso.score_samples(X)
    sub = sub.assign(_if_score=scores)
    
    take = sub[(pred == -1) & (sub['qty_z'] > 3.0)]
    if len(take) > 10: take = take.nsmallest(10, "_if_score")
    
    # MINIMAL FIX: Initialize 'out' before appending to it
    out: list[Flag] = []
    
    for _, r in take.iterrows(): 
        out.append(Flag(sym, r["date"], r["trade_id"], "spoofing", "XRPUSDT IF EOD outlier (qty_z > 3.0 gate)"))
    return out
    
def detect_btc_eth_intraday_if(trades_feat: pd.DataFrame) -> list[Flag]:
    out: list[Flag] = []
    for sym in ["BTCUSDT", "ETHUSDT"]:
        sub = trades_feat[trades_feat["symbol"] == sym].copy()
        if len(sub) < 50: continue
        sub["hod"] = sub["timestamp"].dt.hour
        sub["qty_zh"] = sub.groupby(["date", "hod"])["quantity"].transform(lambda x: (x - x.mean()) / (x.std() + 1e-9))
        X = sub[["qty_zh", "dev_from_mid", "notional"]].replace([np.inf, -np.inf], np.nan).fillna(0.0).values
        iso = IsolationForest(n_estimators=250, contamination=IF_CONTAMINATION, random_state=7, n_jobs=-1)
        pred, scores = iso.fit_predict(X), iso.score_samples(X)
        sub = sub.assign(_if_score=scores)
        
        # GATE: Must be an IF outlier AND structurally massive (> 3.0 standard deviations)
        take = sub[(pred == -1) & (sub['qty_zh'] > 3.0)]
        if len(take) > BTC_ETH_IF_TOP_K: take = take.nsmallest(BTC_ETH_IF_TOP_K, "_if_score")
        for _, r in take.iterrows(): out.append(Flag(sym, r["date"], r["trade_id"], "spoofing", "BTC/ETH intraday IF outlier (qty_zh > 3.0 gate)"))
    return out

def main() -> None:
    parser = argparse.ArgumentParser(description="Problem 3: build submission.csv from student-pack crypto CSVs.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose: per-step timing, DATA/VERIFY table.")
    parser.add_argument("-o", "--output", type=Path, default=ROOT / "submission.csv", help="Output CSV path.")
    parser.add_argument("--no-summary", action="store_true", help="Skip PERF TABLE at the end.")
    parser.add_argument("--max-rows", type=int, default=DEFAULT_MAX_SUBMISSION_ROWS, help="Cap final submission rows.")
    parser.add_argument("--no-trim", action="store_true", help="Do not cap row count.")
    parser.add_argument("--precision", choices=("default", "tight"), default="default", help="tight: strict FP control.")
    args = parser.parse_args()
    configure_logging(verbose=args.verbose)

    max_rows = None if args.no_trim else (min(args.max_rows, 100) if args.precision == "tight" else args.max_rows)

    wall0 = time.perf_counter()
    perf = StepTiming()
    log_pipeline("RUN | Problem 3 pipeline | output=%s", args.output.resolve())

    print("[p3] phase: load market + trade CSVs …", flush=True)
    market = run_timed("load_market_frames", load_market_frames, perf)
    trades = run_timed("load_trades_all", load_trades_all, perf)
    print("[p3] phase: attach bar features …", flush=True)
    trades_f = run_timed("attach_bar_features", attach_bar_features, perf, trades, market)

    log_data_snapshot(market, trades, trades_f)
    print("[p3] phase: run detectors …", flush=True)

    flags_peg = run_timed("detect_peg_usdc", detect_peg_usdc, perf, trades)
    flags_wash_peg = run_timed("detect_usdc_wash_volume_at_peg", detect_usdc_wash_volume_at_peg, perf, trades)
    flags_aml_coord = run_timed("detect_coordinated_structuring", detect_coordinated_structuring, perf, trades)
    flags_mgr_consol = run_timed("detect_manager_consolidation", detect_manager_consolidation, perf, trades)
    flags_place = run_timed("detect_placement_smurfing", detect_placement_smurfing, perf, trades)
    flags_thresh = run_timed("detect_threshold_testing", detect_threshold_testing, perf, trades)
    flags_chain = run_timed("detect_chain_layering", detect_chain_layering, perf, trades)
    flags_bat = run_timed("detect_batusdt_hourly_spikes", detect_batusdt_hourly_spikes, perf, trades)
    flags_aml = run_timed("detect_aml_structuring", detect_aml_structuring, perf, trades)
    flags_wash = run_timed("detect_wash_same_wallet", detect_wash_same_wallet, perf, trades)
    flags_rt = run_timed("detect_round_trip_two_wallets", detect_round_trip_two_wallets, perf, trades)
    flags_coord = run_timed("detect_coordinated_pump", detect_coordinated_pump, perf, trades, market)
    flags_ramp = run_timed("detect_ramping", detect_ramping, perf, trades)
    flags_layer = run_timed("detect_layering_echo", detect_layering_echo, perf, trades)
    flags_pump = run_timed("detect_pump_dump", detect_pump_dump, perf, trades, market)
    flags_cross = run_timed("detect_cross_pair_divergence", detect_cross_pair_divergence, perf, trades, market)
    flags_if = run_timed("detect_isolation_forest", detect_isolation_forest, perf, trades_f)
    flags_xrp_eod = run_timed("detect_xrp_eod_if", detect_xrp_eod_if, perf, trades_f)
    flags_be = run_timed("detect_btc_eth_intraday_if", detect_btc_eth_intraday_if, perf, trades_f)

    flag_lists_named: list[tuple[str, list[Flag]]] = [
        ("peg_usdc", flags_peg), ("usdc_wash_volume_at_peg", flags_wash_peg),
        ("coordinated_structuring", flags_aml_coord), ("manager_consolidation", flags_mgr_consol),
        ("placement_smurfing", flags_place), ("threshold_testing", flags_thresh), ("chain_layering", flags_chain),
        ("batusdt_hourly", flags_bat), ("aml_structuring", flags_aml), ("wash_same_wallet", flags_wash),
        ("round_trip", flags_rt), ("coordinated_pump", flags_coord), ("ramping", flags_ramp),
        ("layering_echo", flags_layer), ("pump_dump", flags_pump), ("cross_pair", flags_cross),
        ("isolation_forest", flags_if), ("xrp_eod_if", flags_xrp_eod), ("btc_eth_if", flags_be),
    ]

    raw_total = sum(len(fl) for _, fl in flag_lists_named)
    print(f"[p3] violations (raw, all detectors): {raw_total}", flush=True)

    print("[p3] phase: merge + dedupe by (symbol, trade_id) …", flush=True)
    sub = merge_flags([fl for _, fl in flag_lists_named])
    n_before_trim = len(sub)
    print(f"[p3] violations (after merge/dedupe): {n_before_trim}", flush=True)

    print("[p3] phase: trim to max_rows (if capped) …", flush=True)
    if not args.no_trim:
        sub = trim_submission(sub, max_rows)
    
    n_trimmed = n_before_trim - len(sub)
    print(f"[p3] violations (final CSV): {len(sub)}" + (f"  (trimmed {n_trimmed} rows)" if n_trimmed > 0 else "  (none trimmed)"), flush=True)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    sub.to_csv(args.output, index=False)
    print(f"[p3] phase: wrote {args.output.resolve()}", flush=True)

if __name__ == "__main__":
    main()