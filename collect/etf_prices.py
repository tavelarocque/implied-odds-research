"""Daily adjusted closes for SPY and the nine original sector SPDRs (all trading since Dec 1998).

Usage (from collect/):  python3 etf_prices.py
Writes data/history/etf/prices.csv.gz, one column per ticker. Uses yfinance (Yahoo Finance).
"""
import os
import yfinance as yf
from common import ROOT

TICKERS = ["SPY", "XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"]
OUT = os.path.join(ROOT, "data", "history", "etf")

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    df = yf.download(TICKERS, start="1999-01-01", auto_adjust=True, progress=False)["Close"]
    df = df[TICKERS].dropna(how="all")
    path = os.path.join(OUT, "prices.csv.gz")
    df.to_csv(path)
    print(f"{len(df):,} days, {df.index.min().date()} to {df.index.max().date()}, missing values: {int(df.isna().sum().sum())} -> {path}")
