#!/bin/sh
# Stale-quote data: Kalshi sample + Coinbase now; Kalshi 1-minute candles once the 5pm-candle download has finished.
cd "$(dirname "$0")"
../.venv/bin/python -u btc_stale_data.py sample && ../.venv/bin/python -u btc_stale_data.py coinbase
while ps ax -o command | grep -v grep | grep -q "kalshi_btc_daily.py"; do sleep 30; done
../.venv/bin/python -u btc_stale_data.py kalshi
