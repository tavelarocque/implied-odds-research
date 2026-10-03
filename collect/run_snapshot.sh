#!/bin/bash
# Takes one matched snapshot: SPX options and Kalshi markets, back to back.
# Run by launchd every 30 minutes during market hours (see collect/com.implied-odds.snapshot.plist).
cd "$(dirname "$0")" || exit 1
mkdir -p ../data/logs
LOG="../data/logs/snapshots.log"
{
  /usr/bin/python3 options_snapshot.py
  /usr/bin/python3 kalshi_snapshot.py
  /usr/bin/python3 polymarket_snapshot.py
  # Once a day, on the first run after 1:30pm Pacific, save the week's one-minute index prices.
  TODAY_FILE="../data/raw/intraday/intraday_$(date -u +%Y-%m-%d).csv.gz"
  if [ "$(date +%H%M)" -ge 1330 ] && [ ! -e "$TODAY_FILE" ]; then
    /usr/bin/python3 intraday.py
  fi
} >> "$LOG" 2>&1
