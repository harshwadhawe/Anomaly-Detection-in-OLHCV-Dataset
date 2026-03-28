# Problem 2 — Insider Trading Signal (Equity, Bonus)

**Max score: 50 points**

---

## What you are doing

You have equity OHLCV and trade data for an event week. Your additional task is to scrape SEC EDGAR for 8-K filings across the ticker universe — these are public announcements of material corporate events (mergers, acquisitions, leadership changes, etc.). You build a news event timeline, then cross-reference it against the trade data to find cases where unusual buying or selling happened in the days before a major announcement.

That pre-announcement activity is the insider trading signal.

---

## Data files

See `data_schema.md` for full column definitions and sample rows.

| File | Description |
|---|---|
| `ohlcv.csv` | Daily OHLCV — 15 prior trading days + the event week. Use the 15 prior days as your rolling baseline. |
| `trade_data.csv` | Individual client trades for the event week |

You build the news event table yourself from EDGAR. See `edgar_starter_snippet.md` for working code.

---

## How the signal works

Once you have a list of `(ticker, event_date)` pairs from EDGAR:

**Abnormal volume** (strongest signal):
```
normal_volume = mean daily volume over prior 15 trading days
volume_z_T-1 = (volume on T-1 - normal_volume) / std_volume_15days
```
A z-score above 3 on T-1 or T-2 is a strong flag.

**Abnormal return:**
```
normal_return = mean daily return over prior 15 trading days
pre_drift = cumulative return from T-5 to T-1
```
If pre_drift is more than 2 standard deviations above the 15-day baseline, flag it.

**Trade-level evidence** (in `trade_data.csv`):
A trader who normally does small quantities on a ticker suddenly placing an unusually large buy order in the T-5 to T-1 window is textbook insider activity.

---

## What to submit

A CSV file named `p2_signals.csv` with these columns:

| Column | Description |
|---|---|
| `sec_id` | The ticker |
| `event_date` | Filing date of the 8-K, `YYYY-MM-DD` |
| `event_type` | e.g. `merger`, `earnings`, `leadership`, `restatement` |
| `headline` | Short description of the event (from EDGAR filing) |
| `source_url` | URL of the EDGAR filing |
| `pre_drift_flag` | `1` if pre-announcement drift detected, `0` otherwise |
| `suspicious_window_start` | Earliest date in the suspicious window, `YYYY-MM-DD` |
| `remarks` | Plain-English explanation of what you found |
| `time_to_run` | How long your code took, in seconds |

**Example `p2_signals.csv`:**

```
sec_id,event_date,event_type,headline,source_url,pre_drift_flag,suspicious_window_start,remarks,time_to_run
99001,2026-02-16,earnings_beat,"Example Corp Q4 EPS beats by 8%",https://efts.sec.gov/LATEST/search-index?q=ExampleCorp&forms=8-K,1,2026-02-09,"Cumulative return T-5 to T-1 was +7.2%; volume z-score on T-2 exceeded 3.1; trade_data shows 3 large BUY fills from an account with no prior activity in this ticker — quantity per fill 8× the 20-day average",41.0
99002,2026-02-18,earnings_miss,"Sample Inc Q3 misses by 11%",https://efts.sec.gov/LATEST/search-index?q=SampleInc&forms=8-K,0,2026-02-11,"No abnormal drift detected pre-announcement; volume in line with baseline; no suspicious trade_data activity — flagged as clean",41.0
```

---

## Scoring

| Outcome | Points |
|---|---|
| Correct (sec_id, event_date) pair identified with pre-announcement flag | +10 |
| False positive | −4 |
| Code completes in under 1 minute | +5 bonus |
| Code completes in under 5 minutes | +5 bonus |
| **Maximum** | **50** |

### Remarks and partial credit

The `remarks` column is your opportunity to explain your reasoning. If your `event_type` label is
slightly off but your `remarks` clearly describe the filing and the suspicious trading pattern
(e.g. "large BUY fills in the 5 days before the announcement, abnormal vs 15-day volume baseline"),
the organiser will award full marks. A clear written explanation that matches the intent of the
actual violation gets the same score as an exact label match.

---

## Tips

- Start with the EDGAR scraper — get a working list of 8-K filing dates for the tickers before doing anything else. That is 30 minutes of work.
- Focus on M&A-related 8-Ks first. Merger announcements produce the clearest pre-announcement drift signals and are most common in enforcement actions.
- Use `trade_data.csv` to find the specific trader making the unusual move, not just the aggregate volume signal.

---

## Submission reminder

- Include a short `README.md` explaining your approach
- Make sure your code runs on a clean machine with standard libraries
- See `edgar_starter_snippet.md` for the EDGAR API setup
