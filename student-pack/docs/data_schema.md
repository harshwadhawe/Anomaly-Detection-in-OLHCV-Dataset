# Data Schema

This document describes every file distributed to participants. Read this before writing any loading code.

---

## Crypto Files — Problem 3

### `SYMBOL_market.csv` (8 files)

One file per trading pair. Source: Binance 1-minute OHLCV data, Jan 1 – Mar 18 2026 UTC.

| Column | Type | Description |
|---|---|---|
| `Unix` | int | Unix timestamp in milliseconds (UTC) |
| `Date` | datetime | Human-readable timestamp, format `YYYY-MM-DD HH:MM:SS` |
| `Symbol` | str | Trading pair, e.g. `BTCUSDT` |
| `Open` | float | Opening price of the 1-minute bar (USDT) |
| `High` | float | Highest price within the bar |
| `Low` | float | Lowest price within the bar |
| `Close` | float | Closing price of the bar |
| `Volume BTC` | float | Total volume traded in the base asset (e.g. BTC for BTCUSDT) |
| `Volume USDT` | float | Total volume traded in USDT |
| `tradecount` | int | Number of individual trades in the bar |

**Sample rows:**

```
Unix,Date,Symbol,Open,High,Low,Close,Volume BTC,Volume USDT,tradecount
1735689600000,2026-01-01 00:00:00,BTCUSDT,94150.20,94210.50,94100.00,94180.00,12.43510,1170821.45,312
1735689660000,2026-01-01 00:01:00,BTCUSDT,94180.00,94195.00,94155.00,94160.00,8.91230,839204.18,241
```

**Notes:**
- 77 days × 1440 minutes = up to 110,880 rows per file
- Some low-liquidity pairs (BATUSDT) will have many zero-volume bars
- USDCUSDT prices should be very close to 1.0000 — deviations are signals

**Loading example:**
```python
df = pd.read_csv("BTCUSDT_market.csv", parse_dates=["Date"])
```

---

### `SYMBOL_trades.csv` (8 files)

One file per trading pair. Synthetic individual trades generated from the OHLCV data, with 50 injected violation trades spread across Jan–Feb 2026.

| Column | Type | Description |
|---|---|---|
| `trade_id` | str | Unique trade identifier, e.g. `BTCUSDT_00000001` |
| `symbol` | str | Trading pair, e.g. `BTCUSDT` |
| `timestamp` | datetime | Trade execution time, format `YYYY-MM-DD HH:MM:SS.ffffff` |
| `price` | float | Execution price (USDT) — within the bar's High/Low |
| `quantity` | float | Trade size in base asset |
| `side` | str | `BUY` or `SELL` |
| `wallet_id` | str | Pseudonymous wallet identifier |

**Sample rows:**

```
trade_id,symbol,timestamp,price,quantity,side,wallet_id
BTCUSDT_00000001,BTCUSDT,2026-01-01 00:00:04.231000,94162.30,0.04821,BUY,wallet_A0042
BTCUSDT_00000002,BTCUSDT,2026-01-01 00:00:11.847000,94158.70,0.11340,SELL,wallet_A0017
```

**Notes:**
- `wallet_id` is crypto-specific — it does not appear in any equity file
- Background trades use noise wallets (`wallet_A0001`…`wallet_A0200`); violation trades use named wallets
- `quantity` is log-normally distributed; prices stay within the bar's High/Low
- ~10,000+ rows per pair; low-liquidity pairs (BATUSDT) have fewer rows

**Loading example:**
```python
df = pd.read_csv("BTCUSDT_trades.csv", parse_dates=["timestamp"])
```

---

## Equity Files — Problems 1 and 2

### `ohlcv.csv` (shared across P1 and P2)

Daily OHLCV for the equity tickers in the dataset. Covers 15 trading days before the event week plus the event week itself — providing a rolling baseline for normalisation.

| Column | Type | Description |
|---|---|---|
| `sec_id` | int | Internal security identifier |
| `trade_date` | date | Calendar date, format `YYYY-MM-DD` |
| `open` | float | Opening price |
| `high` | float | Daily high |
| `low` | float | Daily low |
| `close` | float | Closing price |
| `volume` | int | Total shares traded |

**Sample rows:**

```
sec_id,trade_date,open,high,low,close,volume
10042,2026-01-12,142.30,144.80,141.90,143.50,1823400
10042,2026-01-13,143.50,145.20,143.10,144.90,2041200
```

**Notes:**
- The first 15 rows per `sec_id` (by date) are the historical baseline — use these to compute rolling averages and standard deviations
- The event week rows are where injected signals appear
- No `wallet_id` — equity data uses `trader_id` in `trade_data.csv`

---

### `market_data.csv` (Problem 1 only)

Per-minute order book snapshots for the event week. Top 10 bid and ask price/size levels per ticker per minute.

| Column | Type | Description |
|---|---|---|
| `sec_id` | int | Internal security identifier |
| `timestamp` | datetime | Snapshot time, format `YYYY-MM-DD HH:MM:SS` |
| `bid_price_level01` | float | Best bid price (level 1) |
| `bid_size_level01` | int | Shares available at best bid |
| … | … | Same pattern for levels 02 through 10 |
| `ask_price_level01` | float | Best ask price (level 1) |
| `ask_size_level01` | int | Shares available at best ask |
| … | … | Same pattern for levels 02 through 10 |

Full column list: `sec_id, timestamp, bid_price_level01, bid_size_level01, bid_price_level02, bid_size_level02, …, bid_price_level10, bid_size_level10, ask_price_level01, ask_size_level01, …, ask_price_level10, ask_size_level10`

**Sample rows:**

```
sec_id,timestamp,bid_price_level01,bid_size_level01,...,ask_price_level01,ask_size_level01,...
10042,2026-02-03 09:30:00,142.98,1200,...,143.02,800,...
10042,2026-02-03 09:31:00,142.99,950,...,143.03,1100,...
```

**Useful derived metrics to compute immediately:**
```python
# Order book imbalance
total_bid = df[[f"bid_size_level{i:02d}" for i in range(1, 11)]].sum(axis=1)
total_ask = df[[f"ask_size_level{i:02d}" for i in range(1, 11)]].sum(axis=1)
df["obi"] = (total_bid - total_ask) / (total_bid + total_ask)

# Spread in basis points
df["spread_bps"] = (df["ask_price_level01"] - df["bid_price_level01"]) / df["bid_price_level01"] * 10000
```

---

### `trade_data.csv` (Problems 1 and 2)

Individual equity trades for the event week, mimicking client trade data format.

| Column | Type | Description |
|---|---|---|
| `trade_id` | str | Unique trade identifier |
| `sec_id` | int | Internal security identifier (matches `ohlcv.csv` and `market_data.csv`) |
| `trader_id` | str | Internal trader identifier |
| `trade_date` | date | Calendar date of the trade |
| `timestamp` | datetime | Execution timestamp |
| `side` | str | `BUY` or `SELL` |
| `price` | float | Execution price |
| `quantity` | int | Number of shares |

**Sample rows:**

```
trade_id,sec_id,trader_id,trade_date,timestamp,side,price,quantity
TRD_000001,10042,TRD_009,2026-02-03,2026-02-03 09:45:12,BUY,143.10,500
TRD_000002,10042,TRD_023,2026-02-03,2026-02-03 10:12:44,SELL,143.05,200
```

**Notes:**
- `trader_id` is the equity equivalent of a participant identifier — not the same as `wallet_id` in the crypto files
- Problem 2 signals appear as unusually large buy-side trades on T-2 and T-1 before an 8-K filing date
- Use `ohlcv.csv` volume as the ADV baseline to identify abnormal trade sizes

---

## File Summary

| File | Problem | Format | Rows (approx) |
|---|---|---|---|
| `SYMBOL_market.csv` (×8) | 3 | Crypto OHLCV, 1-min bars | ~110,000 per file |
| `SYMBOL_trades.csv` (×8) | 3 | Synthetic crypto trades | ~10,000+ per file |
| `ohlcv.csv` | 1 & 2 | Daily equity OHLCV | ~21 days × N tickers |
| `market_data.csv` | 1 | Equity order book, 1-min snaps | ~5 days × minutes × N tickers |
| `trade_data.csv` | 1 & 2 | Equity client trades | Event week trades |
