#!/bin/bash
# Wait for the holdout download (kalshi_btc_daily.py) to finish, then fill the decision-time strikes: holdout first,
# then the development sample. Log: /tmp/l11_fill.log
cd "$HOME/CODE/implied-odds/collect" || exit 1
while ps aux | grep -v grep | grep -q "kalshi_btc_daily.py"; do sleep 60; done
LAYER11_HOLDOUT=1 ../.venv/bin/python -u kalshi_btc_fill.py
../.venv/bin/python -u kalshi_btc_fill.py
echo "ALL FILL DONE"
