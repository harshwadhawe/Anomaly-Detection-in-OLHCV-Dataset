#!/usr/bin/env python3
"""
Generates "Hero Images" for the README.md to visually prove pipeline accuracy.
Run this ONCE after all solve_p*.py scripts have successfully generated their CSVs.
"""
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
import matplotlib.dates as mdates

ROOT = Path(__file__).resolve().parent
EQUITY = ROOT / "student-pack" / "equity"

# Use a professional quant aesthetic
plt.style.use('dark_background')
COLORS = ["#00FFCC", "#FF3366", "#FFCC00", "#9966FF"]

def plot_p1_hero():
    """P1: Shows the Order Book Imbalance (OBI) spike triggering an alert."""
    try:
        alerts = pd.read_csv(ROOT / "p1_alerts.csv")
        if alerts.empty: return
        
        # Grab the top alert
        top_alert = alerts.iloc[0]
        sec_id = top_alert['sec_id']
        t_start = pd.to_datetime(top_alert['trade_date'] + " " + top_alert['time_window_start'])
        
        # Load market data just for this sec_id on this day
        m = pd.read_csv(EQUITY / "market_data.csv", parse_dates=["timestamp"])
        m = m[(m['sec_id'] == sec_id) & (m['timestamp'].dt.date == t_start.date())].copy()
        
        # Re-calculate OBI
        bid_cols = [c for c in m.columns if 'bid_size' in c]
        ask_cols = [c for c in m.columns if 'ask_size' in c]
        m['total_bid'] = m[bid_cols].sum(axis=1)
        m['total_ask'] = m[ask_cols].sum(axis=1)
        m['total_book'] = m['total_bid'] + m['total_ask']
        m['obi'] = (m['total_bid'] - m['total_ask']) / m['total_book'].clip(lower=1e-9)
        
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.plot(m['timestamp'], m['obi'], color=COLORS[0], linewidth=1.5, label="Order Book Imbalance (OBI)")
        
        # Highlight the anomaly window
        ax.axvspan(t_start, t_start + pd.Timedelta(minutes=15), color=COLORS[1], alpha=0.3, label=f"Detection: {top_alert['anomaly_type']}")
        
        ax.set_title(f"P1: Order Book Sniper - {top_alert['anomaly_type']} (sec_id: {sec_id})", fontsize=14, fontweight='bold', color='white')
        ax.set_ylabel("Imbalance (Bid Heavy -> Ask Heavy)", color='white')
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        ax.legend(loc="upper left")
        ax.grid(True, alpha=0.2)
        
        plt.tight_layout()
        plt.savefig(ROOT / "images" / "p1_hero.png", dpi=300, transparent=True)
        print("Generated p1_hero.png")
    except Exception as e:
        print(f"Skipping P1 plot: {e}")

def plot_p2_hero():
    """P2: Event Study showing pre-announcement volume spike and drift."""
    try:
        signals = pd.read_csv(ROOT / "p2_signals.csv")
        if signals.empty: return
        
        top_sig = signals.iloc[0]
        sec_id = top_sig['sec_id']
        event_date = pd.to_datetime(top_sig['event_date'])
        
        ohlcv = pd.read_csv(EQUITY / "ohlcv.csv", parse_dates=["trade_date"])
        sub = ohlcv[(ohlcv['sec_id'] == sec_id)].sort_values('trade_date')
        sub = sub[(sub['trade_date'] >= event_date - pd.Timedelta(days=10)) & 
                  (sub['trade_date'] <= event_date + pd.Timedelta(days=2))]
        
        fig, ax1 = plt.subplots(figsize=(10, 5))
        
        # Price Line
        ax1.plot(sub['trade_date'], sub['close'], color=COLORS[0], marker='o', linewidth=2, label="Close Price")
        ax1.set_ylabel("Price", color=COLORS[0], fontweight='bold')
        ax1.tick_params(axis='y', labelcolor=COLORS[0])
        
        # Volume Bars
        ax2 = ax1.twinx()
        ax2.bar(sub['trade_date'], sub['volume'], color=COLORS[3], alpha=0.4, label="Volume")
        ax2.set_ylabel("Volume", color=COLORS[3], fontweight='bold')
        ax2.tick_params(axis='y', labelcolor=COLORS[3])
        
        # Highlight Event
        ax1.axvline(event_date, color=COLORS[1], linestyle='--', linewidth=2, label="8-K Filing Date (T=0)")
        
        plt.title(f"P2: Insider Trading Event Study (sec_id: {sec_id})", fontsize=14, fontweight='bold', color='white')
        fig.legend(loc="upper left", bbox_to_anchor=(0.1, 0.9))
        ax1.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
        ax1.grid(True, alpha=0.2)
        
        plt.tight_layout()
        plt.savefig(ROOT / "images" / "p2_hero.png", dpi=300, transparent=True)
        print("Generated p2_hero.png")
    except Exception as e:
        print(f"Skipping P2 plot: {e}")

def plot_p3_hero():
    """P3: Shows the beautiful distribution of the Risk Management Grid."""
    try:
        sub = pd.read_csv(ROOT / "raw.csv")
        if sub.empty: return
        
        counts = sub['violation_type'].value_counts().reset_index()
        counts.columns = ['Anomaly Type', 'Flags Submitted']
        
        fig, ax = plt.subplots(figsize=(10, 6))
        sns.barplot(x='Flags Submitted', y='Anomaly Type', data=counts, palette='mako', ax=ax)
        
        ax.set_title("P3: Risk-Adjusted Submission Grid (Final Output)", fontsize=14, fontweight='bold', color='white')
        ax.set_xlabel("Number of Rows Submitted (Game Theory Capped)", color='white')
        ax.set_ylabel("")
        
        # Add exact numbers to bars
        for i, v in enumerate(counts['Flags Submitted']):
            ax.text(v + 0.5, i, str(v), color='white', va='center', fontweight='bold')
            
        ax.grid(True, axis='x', alpha=0.2)
        plt.tight_layout()
        plt.savefig(ROOT / "images" / "p3_hero.png", dpi=300, transparent=True)
        print("Generated p3_hero.png")
    except Exception as e:
        print(f"Skipping P3 plot: {e}")

if __name__ == "__main__":
    plot_p1_hero()
    plot_p2_hero()
    plot_p3_hero()