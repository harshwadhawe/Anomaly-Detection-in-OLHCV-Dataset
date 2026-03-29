# Problem 1 — Order Book Concentration (Equity, Bonus)

**Max score: 50 points**

---

## What you are doing

You have per-minute order book snapshots for a set of equity tickers alongside their OHLCV and trade data. Your job is to find tickers and time windows where something looks structurally wrong — unusual concentration on one side of the book, spreads that do not make sense, or order patterns that repeat suspiciously. You then cluster those observations and produce structured alerts.

There are no hints about which tickers or which days to look at. That is the problem.

---

## Data files

See `data_schema.md` for full column definitions and sample rows.

| File | Description |
|---|---|
| `market_data.csv` | Per-minute order book snapshots, top 10 bid and ask levels (price + size), event week |
| `ohlcv.csv` | Daily OHLCV for the same tickers — 15 prior days + event week |
| `trade_data.csv` | Individual client trades for the event week |

---

## What to submit

A CSV file named `p1_alerts.csv` with these columns:

| Column | Description |
|---|---|
| `alert_id` | Sequential integer, 1-indexed |
| `sec_id` | The ticker this alert is for |
| `trade_date` | Date of the alert, `YYYY-MM-DD` |
| `time_window_start` | Start of the suspicious window, `HH:MM:SS` |
| `anomaly_type` | Your label for the pattern — free text, be descriptive |
| `severity` | Your severity rating: `LOW`, `MEDIUM`, or `HIGH` |
| `remarks` | Plain-English explanation of what you found |
| `time_to_run` | How long your code took to produce this output, in seconds |

**Example `p1_alerts.csv`:**

```
alert_id,sec_id,trade_date,time_window_start,anomaly_type,severity,remarks,time_to_run
1,99001,2026-02-16,09:35:00,order_book_imbalance,HIGH,"bid_size_level01–02 sustained at 5× the prior 30-minute average for 18 consecutive minutes with ask side compressed to under 25% of normal; OBI above 0.80 throughout; no corresponding volume increase in trade_data",52.1
2,99002,2026-02-17,11:15:00,unusual_cancel_pattern,MEDIUM,"6 large CANCEL rows from the same trader_id within a 12-minute window all on the BUY side; each cancel immediately followed by a small SELL fill — consistent with spoofing",52.1
```

---

## Scoring

| Outcome | Points |
|---|---|
| Correct pattern identified (lands on an injected anomaly) | +10 |
| False positive | −4 |
| Code completes in under 1 minute | +5 bonus |
| Code completes in under 5 minutes | +5 bonus |
| **Maximum** | **50** |

Think before you flag. False positives are expensive.

### Remarks and partial credit

The `remarks` column in your submission is not optional — it is how the organiser scores borderline alerts.
If your `anomaly_type` label does not exactly match the injected pattern but your `remarks` clearly explain
the suspicious behaviour and the reasoning matches the intent of the actual violation, **full marks will be
awarded**. A well-written explanation of why something looks suspicious is worth more than a blank row with
a correct label.

---

## Suggested starting features

Once you have the data loaded, these are the most informative features to compute:

**Order book imbalance (OBI)**
```python
total_bid = df[[f"bid_size_level{i:02d}" for i in range(1, 11)]].sum(axis=1)
total_ask = df[[f"ask_size_level{i:02d}" for i in range(1, 11)]].sum(axis=1)
df["obi"] = (total_bid - total_ask) / (total_bid + total_ask)
```
A sustained OBI above 0.7 or below −0.7 is unusual.

**Spread in basis points**
```python
df["spread_bps"] = (df["ask_price_level01"] - df["bid_price_level01"]) / df["bid_price_level01"] * 10000
```

**Level 1 depth concentration**
```python
df["bid_concentration"] = df["bid_size_level01"] / total_bid
```

Compute rolling z-scores of these features per ticker and cluster the windows that stand out.

---

## Submission reminder

- Include a short `README.md` explaining your approach — judges read these and they can help borderline calls go your way
- Make sure your code runs on a clean machine with standard libraries
