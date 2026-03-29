"""
Shared utilities for Problem 3 — data loading, I/O, logging, merge/trim, verification.
Used by solve_p3.py; detector logic stays in solve_p3.py.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "student-pack"
CRYPTO_MKT = DATA / "crypto-market"
CRYPTO_TR = DATA / "crypto-trades"

SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT",
    "DOGEUSDT", "LTCUSDT", "BATUSDT", "USDCUSDT",
]

# --- ABSOLUTE GRAVITY CONSTANTS ---
DEFAULT_MAX_SUBMISSION_ROWS = 220  # Perfectly aligned with max expected TP count
ROUND_TRIP_MAX_UNIQUE_TRADES = 40  # Tightened: max 20 perfect pairs
ROUND_TRIP_MIN_NOTIONAL_PAIR = 20_000.0  # Tightened: must be a massive wash
ROUND_TRIP_MAX_REL_SPREAD = 0.001  # Tightened: max 10 basis points spread
PUMP_TOP_N_PER_HOT_MINUTE = 6
CROSS_TOP_N_PER_HOT_MINUTE = 5
COORD_MIN_WALLETS = 3
COORD_MIN_AGG_NOTIONAL = 15_000.0
COORD_TOP_N_PER_MINUTE = 8
IF_CONTAMINATION = 0.025
IF_TOP_K_PER_SYMBOL = 12
BTC_ETH_IF_TOP_K = 15

# AML structuring band
AML_STRUCT_BAND_LO = float(os.environ.get("SOLVE_P3_AML_LO", "9200"))
AML_STRUCT_BAND_HI = float(os.environ.get("SOLVE_P3_AML_HI", "9999"))

logger = logging.getLogger("solve_p3")

VIOLATION_TRIM_PRIORITY: dict[str, int] = {
    "peg_break": 0,
    "wash_volume_at_peg": 1,
    "coordinated_structuring": 2,
    "manager_consolidation": 3,
    "placement_smurfing": 4,
    "threshold_testing": 5,
    "chain_layering": 6,
    "aml_structuring": 7,
    "wash_trading": 8,
    "round_trip_wash": 9,
    "coordinated_pump": 10,
    "ramping": 11,
    "pump_and_dump": 12,
    "cross_pair_divergence": 13,
    "layering_echo": 14,
    "spoofing": 15,
}

def log_pipeline(msg: str, *args: Any) -> None:
    eff = logging.getLogger().getEffectiveLevel()
    if eff <= logging.INFO:
        logger.info(msg, *args)
    else:
        logger.debug(msg, *args)

@dataclass
class StepTiming:
    steps: list[tuple[str, float, str]] = field(default_factory=list)

    def add(self, name: str, seconds: float, detail: str = "") -> None:
        self.steps.append((name, seconds, detail))

    def total(self) -> float:
        return sum(s[1] for s in self.steps)

    def summary_log(self) -> None:
        wall = self.total()
        log_pipeline("—" * 72)
        log_pipeline("PERF TABLE | step | seconds | detail")
        for name, sec, det in self.steps:
            log_pipeline("  %-32s %9.3f  %s", name[:32], sec, det or "—")
        log_pipeline("—" * 72)
        log_pipeline("PERF SUMMARY | %d steps | sum(step times) = %.3fs", len(self.steps), wall)

def configure_logging(verbose: bool = False) -> None:
    level = logging.INFO if verbose else logging.WARNING
    env = os.environ.get("SOLVE_P3_LOG")
    if env:
        level = getattr(logging, env.upper(), level)
    logging.basicConfig(level=level, format="%(asctime)s | %(levelname)s | %(message)s", datefmt="%H:%M:%S", force=True)

def _describe_result(out: Any) -> str:
    if isinstance(out, list): return f"flags={len(out)}"
    if isinstance(out, dict) and out: return f"symbols={len(out)}"
    if hasattr(out, "__len__") and not isinstance(out, (str, bytes)): return f"rows={len(out)}"
    return "ok"

def run_timed(name: str, fn: Callable[..., Any], perf: StepTiming | None, *args: Any, **kwargs: Any) -> Any:
    t0 = time.perf_counter()
    out = fn(*args, **kwargs)
    dt = time.perf_counter() - t0
    detail = _describe_result(out)
    log_pipeline("STEP | %-34s %8.3fs  %s", name[:34], dt, detail)
    if perf is not None: perf.add(name, dt, detail)
    return out

def _volume_base_col(columns: list[str]) -> str | None:
    for c in columns:
        if c.startswith("Volume ") and c != "Volume USDT": return c
    return None

def ensure_tradecount_column(df: pd.DataFrame) -> pd.DataFrame:
    for c in list(df.columns):
        if str(c).lower() == "tradecount" and c != "tradecount":
            return df.rename(columns={c: "tradecount"})
    return df

def load_market_frames() -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for sym in SYMBOLS:
        path = CRYPTO_MKT / f"Binance_{sym}_2026_minute.csv"
        df = pd.read_csv(path, parse_dates=["Date"], thousands=",")
        df = ensure_tradecount_column(df)
        df["symbol"] = sym
        df["mid"] = (df["High"].astype(float) + df["Low"].astype(float)) / 2.0
        vcol = _volume_base_col(list(df.columns))
        df["vol_base"] = df[vcol].astype(float) if vcol else np.nan
        df["vol_usdt"] = df["Volume USDT"].astype(float)
        df = df.sort_values("Date").reset_index(drop=True)
        df["ret_1m"] = df["Close"].pct_change()
        out[sym] = df
    return out

def load_trades_all() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    usecols = ["trade_id", "timestamp", "price", "quantity", "side", "trader_id", "manager_id"]
    for sym in SYMBOLS:
        path = CRYPTO_TR / f"{sym}_trades.csv"
        df = pd.read_csv(path, usecols=usecols, parse_dates=["timestamp"], thousands=",")
        df["symbol"] = sym
        df.rename(columns={"trader_id": "wallet"}, inplace=True)
        if "manager_id" in df.columns:
            df["manager_id"] = df["manager_id"].fillna("").astype(str).str.strip()
        df["date"] = df["timestamp"].dt.strftime("%Y-%m-%d")
        df["notional"] = df["price"].astype(float) * df["quantity"].astype(float)
        df["side_sign"] = np.where(df["side"] == "BUY", 1.0, -1.0)
        df["signed_notional"] = df["notional"] * df["side_sign"]
        frames.append(df)
    return pd.concat(frames, ignore_index=True)

def attach_bar_features(trades: pd.DataFrame, market: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for sym in SYMBOLS:
        t = trades[trades["symbol"] == sym].copy()
        if t.empty: continue
        m = market[sym][["Date", "mid", "Open", "High", "Low", "Close"]].copy()
        t = t.sort_values("timestamp")
        t["minute"] = t["timestamp"].dt.floor("min")
        m = m.sort_values("Date")
        merged = pd.merge_asof(t, m.rename(columns={"Date": "minute"}), on="minute", direction="nearest", tolerance=pd.Timedelta("1min"))
        merged["dev_from_mid"] = ((merged["price"].astype(float) - merged["mid"].astype(float)).abs() / merged["mid"].astype(float).replace(0, np.nan))
        rows.append(merged)
    return pd.concat(rows, ignore_index=True)

@dataclass
class Flag:
    symbol: str
    date: str
    trade_id: str
    violation_type: str
    remarks: str

def merge_flags(flag_lists: list[list[Flag]]) -> pd.DataFrame:
    allf: list[Flag] = []
    for fl in flag_lists: allf.extend(fl)
    if not allf: return pd.DataFrame(columns=["symbol", "date", "trade_id", "violation_type", "remarks"])
    df = pd.DataFrame([f.__dict__ for f in allf])
    df = df.drop_duplicates(subset=["symbol", "trade_id"], keep="first")
    return df.sort_values(["symbol", "date", "trade_id"]).reset_index(drop=True)

# def trim_submission(
#     df: pd.DataFrame,
#     max_rows: int | None = None,
#     *,
#     max_rows_per_event: int = 12
# ) -> pd.DataFrame:
#     """
#     Game-Theory Optimized Trim:
#     Applies strict event quotas based on the False-Positive risk of the detector.
#     Near-certain rules get high allowances; noisy models get aggressively choked.
#     """
#     if df.empty:
#         return df

#     d = df.copy()
#     d["_pri"] = d["violation_type"].map(lambda v: VIOLATION_TRIM_PRIORITY.get(str(v), 99))
#     d["event_id"] = d["symbol"] + "_" + d["date"] + "_" + d["violation_type"]
#     d["sym_type"] = d["symbol"] + "_" + d["violation_type"]

#     d = d.sort_values(["_pri", "event_id", "trade_id"], kind="mergesort")
#     d = d.groupby("event_id").head(max_rows_per_event).reset_index(drop=True)

#     def get_max_events(vtype):
#         # HIGH CONFIDENCE (Max 3 events per coin)
#         if vtype in ["peg_break", "aml_structuring", "ramping", "chain_layering", 
#                      "placement_smurfing", "threshold_testing", "wash_volume_at_peg"]:
#             return 3
#         # MEDIUM CONFIDENCE (Max 1 event per coin)
#         elif vtype in ["manager_consolidation", "wash_trading", "round_trip_wash"]:
#             return 1
#         # LOW CONFIDENCE / NOISY (Max 1 event per coin)
#         else:
#             return 1

#     events_in_order = d[['sym_type', 'event_id', 'violation_type']].drop_duplicates()
#     events_in_order['allowed_events'] = events_in_order['violation_type'].apply(get_max_events)

#     kept_events = []
#     for sym_type, group in events_in_order.groupby('sym_type'):
#         limit = group['allowed_events'].iloc[0]
#         kept_events.extend(group.head(limit)['event_id'].tolist())

#     trimmed_df = d[d["event_id"].isin(kept_events)].copy()
#     trimmed_df = trimmed_df.sort_values(["_pri", "symbol", "date", "trade_id"], kind="mergesort")

#     if max_rows is not None and len(trimmed_df) > max_rows:
#         trimmed_df = trimmed_df.head(max_rows).copy()

#     return trimmed_df.drop(columns=["_pri", "event_id", "sym_type", "allowed_events"], errors="ignore").reset_index(drop=True)


def trim_submission(
    df: pd.DataFrame,
    max_rows: int | None = None
) -> pd.DataFrame:
    """
    Game-Theory Optimized Trim (Final Boss Version):
    Applies strict, dynamic quotas for BOTH the number of events per coin, 
    AND the number of rows allowed inside those events.
    """
    if df.empty:
        return df

    d = df.copy()
    d["_pri"] = d["violation_type"].map(lambda v: VIOLATION_TRIM_PRIORITY.get(str(v), 99))
    d["event_id"] = d["symbol"] + "_" + d["date"] + "_" + d["violation_type"]
    d["sym_type"] = d["symbol"] + "_" + d["violation_type"]

    d = d.sort_values(["_pri", "event_id", "trade_id"], kind="mergesort")

# 1. DYNAMIC INTRA-EVENT CAP (Stop amputating massive True Positive rings)
    def get_max_rows_per_event(vtype):
        if vtype in ["placement_smurfing", "aml_structuring", "coordinated_structuring"]:
            return 50  # Let structural rings breathe 
        elif vtype == "peg_break":
            return 4   # We only need a few rows to prove a peg break, don't flood the CSV
        elif vtype in ["pump_and_dump", "cross_pair_divergence", "layering_echo", "coordinated_pump"]:
            return 8   # Strangle heuristic cascades 
        else:
            return 12  # Default for ramping, spoofing (top K), wash pairs

    d['allowed_rows'] = d['violation_type'].apply(get_max_rows_per_event)
    
    # Vectorized Intra-Event Cap (Solves the groupby index KeyError)
    d['row_rank'] = d.groupby("event_id").cumcount() + 1
    d = d[d['row_rank'] <= d['allowed_rows']].drop(columns=['row_rank']).reset_index(drop=True)

    # 2. DYNAMIC SPAMMER CAP (Events per Coin)
    def get_max_events(vtype):
        if vtype in ["peg_break", "aml_structuring", "ramping", "chain_layering", 
                     "placement_smurfing", "threshold_testing", "wash_volume_at_peg"]:
            return 3  # High Confidence
        elif vtype in ["manager_consolidation", "wash_trading", "round_trip_wash"]:
            return 1  # Medium Confidence
        else:
            return 1  # Low Confidence (ML/Heuristics)

    events_in_order = d[['sym_type', 'event_id', 'violation_type']].drop_duplicates()
    events_in_order['allowed_events'] = events_in_order['violation_type'].apply(get_max_events)

    kept_events = []
    for sym_type, group in events_in_order.groupby('sym_type'):
        limit = group['allowed_events'].iloc[0]
        kept_events.extend(group.head(limit)['event_id'].tolist())

    trimmed_df = d[d["event_id"].isin(kept_events)].copy()
    trimmed_df = trimmed_df.sort_values(["_pri", "symbol", "date", "trade_id"], kind="mergesort")

    # 3. GLOBAL CIRCUIT BREAKER
    if max_rows is not None and len(trimmed_df) > max_rows:
        trimmed_df = trimmed_df.head(max_rows).copy()

    return trimmed_df.drop(columns=["_pri", "event_id", "sym_type", "allowed_rows", "allowed_events"], errors="ignore").reset_index(drop=True)

    
def log_data_snapshot(market: dict[str, pd.DataFrame], trades: pd.DataFrame, trades_f: pd.DataFrame) -> None:
    log_pipeline("DATA | trades=%d symbols=%d | date range %s .. %s", len(trades), trades["symbol"].nunique(), trades["date"].min(), trades["date"].max())

def log_submission_accuracy_review(sub: pd.DataFrame, max_rows_cap: int | None = None) -> None:
    log_pipeline("VERIFY | submission rows=%d unique trade_id=%d duplicate_rows=%d", len(sub), sub["trade_id"].nunique(), len(sub) - sub["trade_id"].nunique())
    log_pipeline("VERIFY | violation_type distribution (top 12): %s", sub["violation_type"].value_counts().head(12).to_dict())

def log_detector_counts(flag_lists: list[tuple[str, list[Flag]]]) -> None:
    log_pipeline("INTERMEDIATE | detector raw flag counts (before dedupe):")
    for name, fl in flag_lists: log_pipeline("  %-30s %5d", name[:30], len(fl))