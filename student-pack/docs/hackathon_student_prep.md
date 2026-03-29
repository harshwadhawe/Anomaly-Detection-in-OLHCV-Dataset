# Hackathon Preparation Guide

This guide is to help you prepare before the event. You will not receive data until the day itself. Use this time to build your knowledge and set up your environment so you can hit the ground running.

One day event, teams of 1-4, your own machine, any language. Problem 3 is compulsory — problems 1 and 2 are bonus. You can attempt both bonus problems if you want. The scoring across all problems rewards both accuracy and speed, so preparation matters a lot.

---

## Scoring Strategy — Read This First

This is worth thinking about before the day, not during it.

Problem 3 is where the bulk of points are — 450 maximum versus 50 each for Problems 1 and 2. The temptation is to spend the entire day on it. That is not always the right call.

Problems 1 and 2 use the same equity data files. If your team splits well — one or two people anchoring Problem 3 while others tackle a bonus problem — you can accumulate points on multiple fronts simultaneously. Problems 1 and 2 are also more deterministic. The injections are fewer, the signals are cleaner, and a methodical team can get full marks on them in a couple of hours. Problem 3 has 50 violations across 8 pairs and 77 days. Getting from 35 correct to 50 correct in the final hour is genuinely hard. Picking up 30 points from Problem 1 in that same hour might be a better use of time.

The flip side is that Problem 3 rewards depth. A team that really understands the manipulation patterns and builds a solid detection pipeline will pull significantly ahead. Spreading too thin across all three problems means solving none of them well.

**Suggested approaches by team size**

- *Solo or 2 people* — commit to Problem 3 fully. Only pivot to a bonus problem once you have a working submission covering most of the violations. Do not split attention early.
- *3 people* — two on Problem 3, one starts a bonus problem independently. Sync at the halfway mark and decide whether to merge effort or keep splitting.
- *4 people* — two on Problem 3, one on Problem 1, one on Problem 2. Reassign at the halfway mark based on where each thread stands. If Problem 3 is going well, converge all four people on it to push the score higher.

The worst thing you can do is drift — spending time on a problem without a clear decision to commit to it. Agree on a strategy at the start and set a concrete decision point at the halfway mark to reassess.

---

## Part 1 — Background: Financial Markets and Trade Surveillance

If you have a quantitative or computer science background but have not worked in finance before, read this section carefully. If you already know this, skim it.

### Equity Markets

Equities are stocks — shares of ownership in a publicly listed company. In the US, they trade on exchanges like NYSE and NASDAQ. Trading happens continuously during market hours (9:30am–4:00pm Eastern) in what is called a continuous double auction. Buyers submit bids and sellers submit asks, and the exchange matches them.

Every trade has a price and a quantity. Price is what one share costs. Quantity is how many shares. The product of the two is the notional value of the trade.

**Key terms you will encounter**

- *Ticker / sec_id* — a unique identifier for a security. AAPL is Apple. In the data you will see a numeric sec_id that maps to a ticker.
- *Trade date* — the calendar date the trade happened.
- *Side* — BUY or SELL from the perspective of the initiating party.
- *OHLCV* — Open, High, Low, Close, Volume. A standard summary of price and volume activity for a given time period (usually daily or per minute).
- *ADV (Average Daily Volume)* — the average number of shares traded per day over a rolling window, typically 20-30 days. Used as a normalisation baseline. A trade representing 10% of ADV is large. One representing 0.1% of ADV is small.
- *VWAP (Volume-Weighted Average Price)* — average price weighted by trade size. Standard benchmark for execution quality.
- *Spread* — the difference between the best ask price and the best bid price at any moment. A tight spread (e.g. $0.01) means the market is liquid. A wide spread means it is illiquid or someone is manipulating quotes.

### The Order Book

The order book is a real-time list of all outstanding limit orders on an exchange for a given security. It has two sides:

- *Bid side* — buy orders, sorted highest price first. Level 1 bid is the best (highest) buy price.
- *Ask side* — sell orders, sorted lowest price first. Level 1 ask is the best (lowest) sell price.

Each level has a price and a size (number of shares available at that price). When you see market_data in Problem 1 you will have up to 10 levels on each side per minute.

```
Level    Bid Price    Bid Size    Ask Price    Ask Size
  1       149.98       1,200       150.02        800
  2       149.95       2,500       150.05      1,400
  3       149.90       3,800       150.10      2,200
  ...
  10      149.50      15,000       150.60      9,000
```

When a large market buy order comes in, it eats through ask levels from level 1 upward. This is called a sweep. When the order book becomes heavily skewed — say 90% of the volume sitting on the bid side — it can signal that someone is artificially supporting the price.

**Derived metrics you should know how to compute**

*Order book imbalance (OBI)*
```
OBI = (total_bid_size - total_ask_size) / (total_bid_size + total_ask_size)
```
Ranges from -1 (all volume on ask side) to +1 (all volume on bid side). A sustained value above 0.7 or below -0.7 is unusual and worth investigating.

*Depth ratio*
```
depth_ratio = bid_size_level01 / ask_size_level01
```
Specifically at the top of the book. If the best bid has 50,000 shares and the best ask has 200, that asymmetry is suspicious.

*Weighted mid price*
```
mid = (bid_price_level01 * ask_size_level01 + ask_price_level01 * bid_size_level01)
      / (bid_size_level01 + ask_size_level01)
```
A more stable mid-price estimate than the simple average of bid and ask.

*Price impact of a sweep*
Simulate eating through the order book with a given order size. How much does the price move? Large price impact from a small order means thin liquidity.

### Crypto Markets

Crypto exchanges work similarly to equity exchanges but with some important differences:

- Trading is 24/7, no defined session. Off-hours trades exist any time.
- Pairs are quoted against a base currency. BTCUSDT means BTC priced in USDT (a stablecoin pegged to $1).
- Wallets replace trader accounts. A wallet_id is a pseudonymous identifier — one person can control many wallets.
- There is no central regulatory authority like the SEC. Manipulation is more rampant and takes more extreme forms.
- Liquidity varies enormously. BTC/ETH pairs are extremely liquid. Low-cap or illiquid pairs can be moved significantly by a single large trade.

**Stablecoins** like USDC (USDCUSDT pair) are designed to always trade at $1.00. They are backed by cash reserves and should never deviate significantly. Any meaningful deviation from $1.00 in price combined with abnormal volume is a strong signal something unusual is happening.

---

## Part 2 — Market Manipulation: Concepts and Detection

This is the core intellectual content of all three problems. Study these patterns carefully — they are what you are looking for.

### Wash Trading

**What it is**

Wash trading is when a trader (or two coordinated traders) buy and sell the same asset back and forth with no genuine change of ownership. The purpose is to artificially inflate trading volume, creating the appearance of activity and interest in an asset. It is illegal in equity markets and prevalent in crypto.

**What it looks like in data**

- The same wallet_id (or two wallet_ids linked to the same entity) appears on both sides of multiple trades within a short time window
- Buy and sell quantities are nearly identical
- The net position change is close to zero
- Prices on the buy and sell legs are similar — no real profit or loss is taken
- In an illiquid market, the round-trips happen at the same price level repeatedly

**Detection approaches**

- Group trades by wallet_id, compute buy_qty and sell_qty per symbol per time window. If buy_qty ≈ sell_qty and the window is short, flag it.
- Look for pairs of wallet_ids that consistently trade with each other (buyer in one trade, seller in the next) on the same symbol at similar prices.
- Compute net directional volume per wallet. Wash traders have near-zero net direction over any meaningful window.

### Spoofing

**What it is**

Spoofing is placing large orders on one side of the order book with no intention of filling them. The goal is to create a false impression of supply or demand, move the price, then cancel the order and trade at the manipulated price.

**What it looks like in data**

- A large order appears at bid level 1 or ask level 1, significantly larger than anything else in the book
- Other market participants react — price moves toward the large order
- The large order is cancelled before it gets filled
- The spoofer then trades in the opposite direction at the now-manipulated price
- This pattern repeats — often multiple times in succession on the same ticker

**Detection approaches**

- In order book data: look for sudden large size appearing at level 1 then disappearing the following minute without a corresponding price move that would indicate it was filled
- Compute size at level 1 as a ratio of the total 10-level depth. A sudden spike to 60%+ of total depth followed by an immediate return to normal is a spoofing signal.
- Look for the sequence: large bid appears → ask side gets hit (price ticks up) → large bid disappears → large sell executes

### Layering

**What it is**

Layering is a variant of spoofing where multiple orders at different price levels are placed on one side of the book to create a false wall of support or resistance. The layers are cancelled once the price moves.

**What it looks like in data**

- Multiple levels on one side of the book suddenly fill up with unusual size simultaneously
- The size distribution across levels changes sharply — normally level 1 has the most size and it thins out. Layering reverses this or makes all levels similar.
- After the price moves, all the layered orders vanish at once

### Pump-and-Dump

**What it is**

Coordinated buying drives the price of an asset up (the pump). Once the price is elevated and retail investors start buying in on the momentum, the manipulators sell their entire position at the inflated price (the dump), leaving everyone else holding a devalued asset.

**What it looks like in data**

- A sequence of 3-10 consecutive minutes where close price rises consistently and volume increases each bar — this is the pump
- Trade count per minute rises sharply during the pump phase
- Followed by 1-2 minutes of very high volume and falling price — this is the dump
- After the dump, price often falls below the pre-pump level and volume collapses

**Detection approaches**

- Compute the rolling return over a 10-minute window. Sustained positive returns above 2-3x the normal volatility combined with volume 3x+ the ADV is a pump signal.
- Look for the asymmetry: slow rise over many minutes, fast fall over 1-2 minutes. Natural price moves are more symmetric.
- Tradecount spikes during the pump phase are a strong signal — more individual trades means coordinated retail involvement.

### AML Structuring (Smurfing)

**What it is**

In anti-money laundering (AML) regulation, certain transaction sizes trigger mandatory reporting to authorities. Structuring is the practice of breaking large transactions into many smaller ones specifically designed to stay below those reporting thresholds. Also called smurfing.

**What it looks like in data**

- A wallet submits many trades in a short window that are all suspiciously similar in size — particularly when the sizes are just below a round number threshold
- The trades are spread across multiple minutes but the cumulative amount would constitute a large reportable transaction
- In illiquid pairs (like BATUSDT), this stands out because the pair normally has very little activity. Suddenly seeing 20 trades of 990 USDT each in an hour when the pair normally does 200 USDT an hour is obvious.
- Multiple wallets executing the same pattern simultaneously suggests coordination

**Detection approaches**

- Compute standard deviation of trade sizes per wallet per day. Structuring produces very low std (all trades are similar size) combined with high frequency.
- Flag wallets where (max_trade_size / min_trade_size) < 1.1 across 10+ trades in a day — this means they are deliberately keeping sizes in a tight band.
- Compute cumulative wallet volume per hour and compare to the pair's historical hourly average. Structuring wallets will stand out.

### Marking the Close

**What it is**

Executing trades near the end of a trading session specifically to influence the closing price. Closing prices are used in fund valuations, index calculations, and derivatives settlement. Moving the close even slightly can have large financial implications.

**What it looks like in data**

- One or a few large trades in the final minutes of the session (or final minutes of a daily window in crypto)
- These trades are at prices that push the close significantly above or below the prior minute's price
- After the window closes, the price would naturally revert without these trades
- Volume in the final 5-10 minutes is anomalously high relative to the rest of the session

**Detection approaches**

- Define the last N minutes of each day as the "close window" (e.g. last 10 minutes of the 24-hour period)
- Compare volume and price impact in this window against the rest of the day
- Flag days where a single trade in the close window represents more than 20% of the day's total volume

### Ramping / Advancing the Bid

**What it is**

Systematically executing trades at progressively higher (or lower) prices to move the market in a desired direction, usually to create paper profits on an existing position or to set up a future trade.

**What it looks like in data**

- A sequence of trades from the same wallet_id at consistently rising prices
- Each trade is slightly above the prior trade's price — artificially walking the price up
- Volume at each step is just enough to move the market without drawing too much attention
- Once the target price is reached, the wallet exits its position

**Detection approaches**

- For each wallet, compute the sequence of trade prices over time. Flag wallets where more than 70% of their trades in a given window are in the same direction with monotonically changing prices.
- Compare the wallet's average trade price against the OHLCV close for that minute. If they consistently trade at the high of each bar, that is suspicious.

### Peg Break (Stablecoin Specific)

**What it is**

A stablecoin like USDC is designed to always be worth exactly $1.00. A peg break is any event where the trading price deviates materially from this value. In a surveillance context, suspicious peg breaks are often associated with wash trading (creating artificial volume) or deliberate price manipulation in illiquid conditions.

**What it looks like in data**

- USDCUSDT close price deviates more than 0.5% from 1.0000 in any given minute
- The deviation is accompanied by unusually high volume — if the peg breaks with no volume, it is a data artifact; if it breaks with high volume, someone traded it there deliberately
- A peg break that corrects in the very next minute (snaps back to 1.0000) is suspicious because it suggests someone briefly moved the price for a purpose

**Detection approaches**

- This one is simple: `abs(close - 1.0) > 0.005` on USDCUSDT flags the peg break
- The interesting part is context — combine with volume z-score to determine if it is meaningful
- Cross-reference with BTCUSDT or ETHUSDT — a USDC peg break that coincides with a major move in BTC might be a broader market event rather than manipulation

---

## Part 3 — Technical Preparation

### Recommended Stack

You can use any language but Python is strongly recommended. The data is CSV-based and you will spend most of your time on data manipulation, statistics, and optional ML. Python's ecosystem handles all of this cleanly.

```bash
pip install pandas numpy scipy matplotlib seaborn scikit-learn requests beautifulsoup4 jupyter
```

Install these before the event. Do not rely on event WiFi for package installs.

### Pandas Skills You Will Definitely Use

```python
import pandas as pd
import numpy as np

df = pd.read_csv("data.csv", parse_dates=["timestamp"])

# Rolling statistics — critical for baseline comparison
df["qty_rolling_mean"] = df.groupby("symbol")["quantity"].transform(
    lambda x: x.rolling(window=20).mean()
)
df["qty_z_score"] = (df["quantity"] - df["qty_rolling_mean"]) / df.groupby("symbol")["quantity"].transform(
    lambda x: x.rolling(window=20).std()
)

# Group by wallet and compute behavioural features
wallet_stats = df.groupby("wallet_id").agg(
    total_trades=("trade_id", "count"),
    avg_qty=("quantity", "mean"),
    std_qty=("quantity", "std"),
    buy_qty=("quantity", lambda x: x[df.loc[x.index, "side"] == "BUY"].sum()),
    sell_qty=("quantity", lambda x: x[df.loc[x.index, "side"] == "SELL"].sum())
)

# Time-based filtering
df["hour"] = df["timestamp"].dt.hour
df["minute"] = df["timestamp"].dt.minute
after_hours = df[~df["hour"].between(9, 16)]  # adjust for crypto

# Resampling OHLCV from tick data
ohlcv = df.set_index("timestamp").groupby("symbol")["price"].resample("1min").ohlc()
volume = df.set_index("timestamp").groupby("symbol")["quantity"].resample("1min").sum()
```

### Feature Engineering for Order Book Data

When you receive order book snapshots (top 10 levels), here are the features worth computing:

```python
# Order book imbalance
df["total_bid"] = df[[f"bid_size_level{i:02d}" for i in range(1, 11)]].sum(axis=1)
df["total_ask"] = df[[f"ask_size_level{i:02d}" for i in range(1, 11)]].sum(axis=1)
df["obi"] = (df["total_bid"] - df["total_ask"]) / (df["total_bid"] + df["total_ask"])

# Spread
df["spread"] = df["ask_price_level01"] - df["bid_price_level01"]
df["spread_bps"] = df["spread"] / df["bid_price_level01"] * 10000  # in basis points

# Top-of-book depth ratio
df["depth_ratio"] = df["bid_size_level01"] / df["ask_size_level01"].replace(0, np.nan)

# Depth concentration — how much of total depth is at level 1?
df["bid_concentration"] = df["bid_size_level01"] / df["total_bid"]
df["ask_concentration"] = df["ask_size_level01"] / df["total_ask"]

# Rolling z-scores — compare current snapshot to recent history
for col in ["obi", "spread_bps", "depth_ratio"]:
    df[f"{col}_z"] = df.groupby("sec_id")[col].transform(
        lambda x: (x - x.rolling(60).mean()) / x.rolling(60).std()
    )
```

### Clustering Approaches

**When to use DBSCAN**

DBSCAN (Density-Based Spatial Clustering of Applications with Noise) is good when you do not know how many clusters to expect and when anomalies are the thing you care about — noise points are exactly what you are looking for.

```python
from sklearn.cluster import DBSCAN
from sklearn.preprocessing import StandardScaler

features = df[["obi_z", "spread_bps_z", "depth_ratio_z"]].dropna()
scaler = StandardScaler()
X = scaler.fit_transform(features)

db = DBSCAN(eps=0.5, min_samples=5)
labels = db.fit_predict(X)

# Label -1 means the point is an outlier — these are your candidates
df.loc[features.index, "cluster"] = labels
anomalies = df[df["cluster"] == -1]
```

Tune `eps` (neighbourhood radius) and `min_samples` by looking at the k-distance graph. Too small an eps and everything is noise. Too large and anomalies get absorbed into clusters.

**When to use Isolation Forest**

Isolation Forest is better for high-dimensional data and when you want an anomaly score rather than a binary label. It works by randomly isolating points — anomalies are isolated faster (fewer splits needed) than normal points.

```python
from sklearn.ensemble import IsolationForest

clf = IsolationForest(n_estimators=200, contamination=0.05, random_state=42)
# contamination is your estimate of the fraction of anomalies in the data
# 0.05 means you expect about 5% to be anomalous

features = df[["qty_z_score", "price_deviation", "wallet_frequency"]].dropna()
scores = clf.fit_predict(features)  # -1 is anomaly, 1 is normal
anomaly_scores = clf.score_samples(features)  # continuous score, lower = more anomalous

df.loc[features.index, "anomaly_score"] = anomaly_scores
df.loc[features.index, "is_anomaly"] = (scores == -1)
```

**When to use k-means**

k-means is straightforward when you have a rough sense of how many behaviour clusters to expect. It does not naturally identify anomalies but you can flag points far from their cluster centroid.

```python
from sklearn.cluster import KMeans

kmeans = KMeans(n_clusters=5, random_state=42, n_init=10)
df["cluster"] = kmeans.fit_predict(X)
df["distance_to_centroid"] = kmeans.transform(X).min(axis=1)

# Points far from any centroid are anomalous
threshold = df["distance_to_centroid"].quantile(0.95)
df["is_anomaly"] = df["distance_to_centroid"] > threshold
```

Always scale your features before clustering. Raw quantities in crypto vary by many orders of magnitude across BTC and BAT — without scaling, BTC will dominate every distance metric.

### Anomaly Detection Without ML

Sometimes simple statistics beat ML for this kind of problem, especially within a single day.

```python
# Z-score method — straightforward and fast
def flag_by_zscore(series, threshold=3.0):
    z = (series - series.mean()) / series.std()
    return abs(z) > threshold

# IQR method — more robust to outliers in the baseline
def flag_by_iqr(series, multiplier=3.0):
    q1, q3 = series.quantile(0.25), series.quantile(0.75)
    iqr = q3 - q1
    return (series < q1 - multiplier * iqr) | (series > q3 + multiplier * iqr)

# Modified z-score — uses median, more robust than mean
def modified_zscore(series):
    median = series.median()
    mad = (series - median).abs().median()
    return 0.6745 * (series - median) / mad
```

### Working with Time in Anomaly Detection

Context window matters a lot. A trade that is 10x normal size is more suspicious at 3:58pm than at 10:00am, because end-of-day activity has different baseline statistics. Always compute your baselines per time-of-day bucket if you can.

```python
# Compute intraday baseline per hour
df["hour"] = df["timestamp"].dt.hour
hourly_baseline = df.groupby(["symbol", "hour"])["quantity"].agg(["mean", "std"])

# Join back to compute hour-adjusted z-score
df = df.merge(hourly_baseline, on=["symbol", "hour"], how="left")
df["intraday_z"] = (df["quantity"] - df["mean"]) / df["std"]
```

---

## Part 4 — Problem-Specific Preparation

### Problem 1 — Order Book Concentration (Equity)

**What to study**

You will receive per-minute order book snapshots (top 10 bid and ask levels) for equity tickers alongside OHLCV and trade data. Your task is to identify where unusual concentration is happening in the order book, cluster those observations, and produce structured alerts.

Think carefully about what features capture concentration. Single-minute spikes are less interesting than sustained patterns — a spoofing echo repeating 10 times is more concerning than one large order. Your clustering should group time windows by the type of anomaly they represent, not just flag individual minutes.

**Suggested feature set for clustering**

- Rolling 10-minute average OBI and its standard deviation
- Spread in basis points relative to its 30-day average
- Level 1 concentration ratio (what fraction of total depth sits at level 1)
- Consecutive minutes where OBI is above/below a threshold
- Trade volume as a fraction of total bid depth (how aggressively is someone buying into the book)
- Cross-level depth asymmetry — is the distribution of size across levels unusual compared to the ticker's normal profile

**Alert output you will be asked to generate**

Your alerts should identify specific (ticker, date, time window) combinations along with the anomaly type, severity, and a plain-English remark explaining what was found. Think about what would be useful to a compliance analyst reviewing your output — they need enough context to take action.

**One practical tip**

Compute a per-ticker, per-day baseline first before looking for anomalies. A spread of $0.50 is normal for a $10 stock and unusual for a $500 stock. Normalise everything relative to the ticker's own history before comparing across tickers.

---

### Problem 2 — News Scraper + Insider Trading Signal (Equity)

**What to study**

You get the same OHLCV and trade data as Problem 1. Your additional task is to build a news event scraper targeting SEC EDGAR and produce a timeline of material corporate announcements. You then cross-reference that timeline against trade activity to find suspicious pre-announcement activity.

**How SEC EDGAR works**

EDGAR is the SEC's public filing database. Every US-listed company must file an 8-K form whenever a material event occurs. Material events include:
- Mergers and acquisitions
- Earnings results (if not in the regular 10-Q/10-K schedule)
- CEO or senior leadership changes
- Major contracts won or lost
- Restatements of prior financial results
- Bankruptcy filings

The key field you care about is the filing date. That is the moment the information became public. Any trading in the window before that date is potentially informed by non-public information.

**EDGAR API basics**

The full-text search API does not require authentication:

```
GET https://efts.sec.gov/LATEST/search-index?q="merger"&forms=8-K&dateRange=custom&startdt=2026-01-01&enddt=2026-02-28
```

Key parameters:
- `q` — search term (e.g. "merger", "acquisition", "restatement")
- `forms` — always use `8-K` for material events
- `dateRange=custom` with `startdt` and `enddt`
- `entity` — filter by company name

The response is JSON. The `hits.hits` array contains individual filings. Each has `_source.period_of_report`, `_source.entity_name`, `_source.file_date`, and `_source.form_type`.

You will also need to map company names to the sec_id in the trade data. The `get_tickers_at_date` lookup is your bridge — a ticker like AAPL maps to a numeric sec_id. Build that mapping early.

**The insider trading signal**

Once you have a list of (ticker, event_date) pairs from EDGAR, compute for each:

*Abnormal return*
```
normal_return = mean daily return over prior 15 trading days
abnormal_return_T-1 = return on T-1 - normal_return
abnormal_return_T-2 = return on T-2 - normal_return
```
If the cumulative abnormal return over T-5 to T-1 is more than 2 standard deviations above the 15-day baseline, flag it.

*Abnormal volume*
```
normal_volume = mean daily volume over prior 15 trading days
volume_z_T-1 = (volume_T-1 - normal_volume) / std_volume_15days
```
A volume z-score above 3 on T-1 or T-2 is a strong signal.

*Trade-level evidence (in the trade data)*
- Look for specific traders placing unusually large orders in the T-5 to T-1 window relative to their own history on that ticker
- A trader who normally does 500 shares/day suddenly doing 50,000 shares two days before an M&A announcement is textbook insider trading

**NLP for event classification**

You do not need a trained model. Simple keyword matching gets you most of the way:

```python
event_keywords = {
    "merger":      ["merger", "acquisition", "acquired", "takeover", "combine"],
    "earnings":    ["earnings", "revenue", "quarterly results", "guidance"],
    "leadership":  ["ceo", "chief executive", "resign", "appoint", "board"],
    "restatement": ["restate", "restatement", "correction", "material weakness"]
}

def classify_event(headline):
    headline_lower = headline.lower()
    for event_type, keywords in event_keywords.items():
        if any(kw in headline_lower for kw in keywords):
            return event_type
    return "other"
```

**Practical tip**

Insider trading on M&A events is the easiest to detect and the most common in enforcement actions. Focus your scraper on 8-K filings that contain merger or acquisition language. These produce the cleanest pre-announcement drift signals.

---

### Problem 3 — Crypto Blind Anomaly Hunt (Compulsory)

**What to study**

You get 8 crypto pairs with 1-minute OHLCV market data from Jan 1 to Mar 18 2026 and a synthetic individual trades file for each pair. No labels, no hints. You find the suspicious trades and submit a ranked list. Highest score wins.

**Understanding the 8 pairs**

| Pair | What to know going in |
|---|---|
| BTCUSDT | Highest liquidity. Normal volume is very high so genuine anomalies are proportionally large. Subtle manipulation requires careful baseline work. BTC was around $87k at start of 2026 in this dataset. |
| ETHUSDT | Similar to BTC in liquidity. More sensitive to order flow patterns. ETH price around $3-4k range. |
| SOLUSDT | More volatile than BTC/ETH. Volume spikes are more common so you need a tighter z-score threshold. |
| XRPUSDT | Watch for end-of-session behaviour. Low-cost per unit means large quantities are involved. |
| DOGEUSDT | Community-driven. Coordinated pumps leave clear volume and tradecount signatures. Very low price per unit (~$0.30-0.40 range) so quantities are large. |
| LTCUSDT | Moderate liquidity. Similar to BTC in structure but smaller. Good pair to look for round-trip wash trades. |
| BATUSDT | Very low liquidity. Many 1-minute bars will have zero trades. Any activity here is notable. Price around $0.10. Pay very close attention to this one — AML patterns in low-liquidity pairs are textbook exam material. |
| USDCUSDT | Always $1.00. Start here. Any deviation from $1.00 combined with volume is immediately suspicious. This is the most straightforward pair in the dataset. |

**Scoring strategy**

- Correct suspicious trade identified: +5 points
- False positive: −2 points
- Correct violation_type on a true positive: +2 bonus
- True positive detected in under 1 minute of runtime: +2 bonus, but false positives in that window cost −1

The penalty for false positives is real. Do not shotgun every unusual trade. Use a two-pass approach — first pass uses loose thresholds to identify candidates, second pass applies stricter criteria to confirm before adding to your submission.

**Suggested day-of workflow**

1. Load all 8 pairs' market and trade data. Print basic stats (mean, std, min, max for quantity and price per symbol). This takes 10 minutes and gives you a mental model of each pair.

2. Start with USDCUSDT — flag any row in the trades file where `abs(price - 1.0) > 0.005`. Cross-check with volume. You will get quick points here.

3. Move to BATUSDT — compute the hourly volume baseline per day. Flag any hour with volume more than 5x the pair's median hourly volume. Then look at the trades in those hours.

4. For DOGE, LTC, SOL — run Isolation Forest on (quantity_z, price_deviation_from_ohlcv_mid, wallet_frequency). These pairs have cleaner anomaly signatures.

5. For BTC and ETH — you need tighter feature engineering. Add intraday z-scores (compute baseline per hour of day, not just per day). Wash trading in BTC requires wallet-level analysis — look for wallet pairs that consistently trade with each other.

6. Build your submission CSV as you go. Do not leave all submissions to the last 10 minutes.

**Feature importance guide**

Some features are worth more than others for this dataset. In rough order of signal strength:

High signal:
- Quantity z-score (per symbol, rolling)
- Wallet round-trip detection (buy and sell within N minutes at similar price)
- USDCUSDT price deviation from 1.0000
- BATUSDT volume in otherwise-dead minutes

Medium signal:
- Tradecount spike (in market data) — indicates coordinated small trades
- End-of-day trade timing combined with unusually large quantity
- Sequential trades from same wallet in same direction

Lower signal (contextual):
- Price deviation from OHLCV mid within bar — real for large trades but many false positives
- Side imbalance per wallet over a full day — directional bias is normal for informed traders

---

## Part 5 — Setup Checklist

Complete this before the event. Do not do it on the day.

**Environment**
- [ ] Python 3.10 or higher installed
- [ ] `pip install pandas numpy scipy matplotlib seaborn scikit-learn requests beautifulsoup4 jupyter` completed and tested
- [ ] A working IDE or editor (VSCode, PyCharm, Jupyter — whichever you are fastest in)
- [ ] GitHub account set up, you can create a repo and push code

**Practice runs**
- [ ] Load a CSV with 100k+ rows in pandas and compute groupby rolling statistics — make sure it runs in under 30 seconds on your machine
- [ ] Run DBSCAN and Isolation Forest on a toy dataset from sklearn.datasets to confirm your setup works
- [ ] For Problem 2 only: run the EDGAR API curl call below and confirm you get a JSON response back

```bash
curl "https://efts.sec.gov/LATEST/search-index?q=%22acquisition%22&forms=8-K&dateRange=custom&startdt=2026-01-01&enddt=2026-02-28" | python3 -m json.tool | head -50
```

**Background reading (30-60 minutes total — worth doing)**
- Wikipedia: Wash trading, Spoofing (finance), Pump and dump scheme, Structuring (money laundering), Market manipulation
- SEC investor bulletins on insider trading — very readable, gives you the enforcement mindset
- Skim one or two real SEC enforcement press releases on spoofing (search "SEC charges spoofing 2024") — understanding what regulators actually flag helps you calibrate your thresholds

---

## Part 6 — On the Day

- Problem statements, data files, and the EDGAR starter snippet will be distributed at kickoff via GitHub or USB
- External APIs (Binance, CoinGecko, EDGAR) are allowed but not required — everything you need is in the provided files
- If something in the data looks genuinely broken, ask. If it just looks weird or unusual, that is probably intentional.
- Submission format is a GitHub repo link or a ZIP file by end of day. Include a short README explaining your approach per problem — judges read these and it can help your score if a borderline call goes your way.
- For Problem 3, include your scoring submission CSV at the root of your repo as `submission.csv` with columns: `symbol, date, trade_id, violation_type`
- Time to run matters for bonus points in all three problems. Write efficient code from the start — vectorised pandas operations over loops, no redundant recomputation.
