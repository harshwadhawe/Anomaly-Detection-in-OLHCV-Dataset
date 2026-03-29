# Problem 3 — Crypto Blind Anomaly Hunt (Compulsory)

**Max score: 450 points**

---

## What you are doing

You have 8 crypto trading pairs with 1-minute OHLCV market data from Jan 1 to Mar 18 2026, and a synthetic individual trades file for each pair. No labels. No hints on what to look for or where.

Your job: find which specific trades are suspicious. You submit a list of `(symbol, date, trade_id)` rows. Highest score minus false positive penalty wins.

---

## Data files

See `data_schema.md` for full column definitions and sample rows.

| File | Description |
|---|---|
| `SYMBOL_market.csv` (×8) | 1-minute OHLCV bars, Jan 1 – Mar 18 2026 |
| `SYMBOL_trades.csv` (×8) | Synthetic individual trades with `wallet_id` |

Use the market file as your baseline. Hunt in the trades file.

---

## The 8 pairs

| Pair | What to know |
|---|---|
| BTCUSDT | Highest liquidity. Manipulation here is subtle — you need careful baseline work. |
| ETHUSDT | High liquidity. Watch for order flow patterns, not just price. |
| SOLUSDT | Volatile. Volume spikes stand out more clearly than on BTC/ETH. |
| XRPUSDT | Fast and cheap to transact. Watch for fund movement patterns across wallets. |
| DOGEUSDT | Sentiment-driven. Coordinated activity leaves clear volume and tradecount signatures. |
| LTCUSDT | Moderate liquidity. Good pair for round-trip and AML patterns. |
| BATUSDT | Very low liquidity. Most minutes have near-zero volume. Any activity here stands out significantly. |
| USDCUSDT | Stablecoin — always $1.00. Any deviation from $1.00 combined with volume is immediately suspicious. Start here. |

---

## Violation types

Your submission may include a `violation_type` column for +2 bonus points per correct match. Accepted strings (exact, case-sensitive):

**AML violations**

| violation_type | Description |
|---|---|
| `aml_structuring` | Many trades of near-identical size just below a threshold from the same wallet — smurfing |
| `coordinated_structuring` | Multiple wallets running the same below-threshold pattern simultaneously — organised smurfing network |
| `threshold_testing` | A wallet places one trade exactly at the threshold, then follows with a structuring campaign just below it |
| `chain_layering` | Funds passed through a sequential chain of wallets to obscure origin (wallet A → wallet B → wallet C) |
| `manager_consolidation` | After a structuring or layering campaign, a coordinating wallet receives a large consolidated transaction |
| `placement_smurfing` | Coordinated initial placement of a large notional amount via many small first-appearance trades from multiple new wallets |

**Market manipulation violations**

| violation_type | Description |
|---|---|
| `wash_trading` | Same wallet on both sides of trades, near-zero net position |
| `pump_and_dump` | Rising close and volume over several bars, followed by a sharp reversal |
| `layering_echo` | Wallet places multiple trades pushing price in one direction then immediately reverses |
| `spoofing` | Aggressive price movement in one direction then abrupt reversal |
| `ramping` | Sequential trades at monotonically rising prices from the same wallet |
| `coordinated_pump` | Multiple wallets buying simultaneously to push price, coordinated entry |
| `round_trip_wash` | Two linked wallets trading back and forth with no net ownership change |
| `cross_pair_divergence` | Price on this pair moves counter to strongly correlated pairs |
| `peg_break` | USDCUSDT price deviates more than 0.5% from $1.00 |
| `wash_volume_at_peg` | Wash trades on USDCUSDT creating artificial volume at exactly $1.00 |

---

## Scoring

| Outcome | Points |
|---|---|
| True positive — correct `trade_id` identified | +5 |
| False positive | −2 |
| Correct `violation_type` on a true positive | +2 bonus |
| True positive found in under 1 minute of runtime | +2 bonus |
| False positive within that 1-minute window | −1 |
| **Maximum** | **450** |

Think carefully before flagging. False positives are expensive.

### What "correct violation_type" means

Exact string match is required for the +2 bonus — but if your `violation_type` is wrong yet your
`remarks` column explains the suspicious behaviour and your reasoning matches the intent of the
actual violation, the organiser may award the bonus at their discretion. In ambiguous cases,
**a clear written explanation always wins over a blank remarks field**.

Add a `remarks` column to your `submission.csv` (optional, plain text):

```
symbol,date,trade_id,violation_type,remarks
BTCUSDT,2026-01-14,BTCUSDT_00012847,wash_trading,"Same wallet on both sides within 90 seconds, net position zero, consistent for 6 pairs of trades"
BATUSDT,2026-01-22,BATUSDT_00000441,aml_structuring,"9 trades between 09:45–15:30, all quantity*price just under 9 950 USDT — classic smurfing below 10 000 threshold"
```

Graders will read remarks for any trade where `violation_type` does not exactly match — if your
explanation clearly describes the same suspicious pattern, you get the bonus.

---

## Submission format

Submit a file called `submission.csv` at the root of your repository:

```
symbol,date,trade_id,violation_type
BTCUSDT,2026-01-14,BTCUSDT_00012847,wash_trading
USDCUSDT,2026-02-03,USDCUSDT_00001293,peg_break
BATUSDT,2026-01-22,BATUSDT_00000441,aml_structuring
```

- `violation_type` is optional but earns +2 bonus per correct match
- Exact string match required — see taxonomy above
- One row per suspicious trade (not per event — a structuring campaign with 6 trades needs 6 rows)
- `remarks` is strongly recommended — see partial credit rules above

**Example `submission.csv`:**

```
symbol,date,trade_id,violation_type,remarks
BTCUSDT,2026-03-05,BTCUSDT_00099001,wash_trading,"two wallet IDs appear on opposite sides of 5 trades within 3 minutes at nearly identical prices; net position unchanged; no economic rationale for repeated round-trips at this frequency"
ETHUSDT,2026-03-07,ETHUSDT_00099002,layering_echo,"wallet places 6 BUY trades then reverses with 6 SELL trades at slightly lower prices within 8 minutes; price briefly moves in the BUY direction before reverting — classic momentum faking"
ETHUSDT,2026-03-07,ETHUSDT_00099003,layering_echo,"same episode as above — 2nd trade in the sequence; include one row per trade_id in a multi-trade pattern"
SOLUSDT,2026-03-10,SOLUSDT_00099004,ramping,"10 consecutive BUY trades from the same wallet at monotonically increasing prices over 90 minutes; no intervening sells; price increase of 1.8% attributable almost entirely to this wallet's activity"
```

---

## Suggested workflow

1. Load all 8 pairs. Print basic stats (mean, std, min, max for quantity and price per symbol). This takes 10 minutes and gives you a mental model.
2. Start with **USDCUSDT** — flag any row where `abs(price - 1.0) > 0.005`. Quick points.
3. Move to **BATUSDT** — compute hourly volume baseline per day. Flag hours with volume >5x median. Look at the trades in those hours.
4. For DOGE, LTC, SOL — run Isolation Forest on (quantity z-score, price deviation from OHLCV mid, wallet frequency).
5. For BTC and ETH — you need tighter feature engineering. Compute intraday baselines (per hour of day, not just per day). Wallet-level analysis is important here.
6. Build `submission.csv` incrementally as you go. Do not leave it to the last 10 minutes.

---

## Submission reminder

- `submission.csv` must be at the root of your repo or ZIP
- Include a short `README.md` explaining your approach — useful for borderline scoring decisions
- Time to run matters: write vectorised pandas operations, not loops
