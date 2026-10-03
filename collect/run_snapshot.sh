#!/bin/bash
# Takes one matched snapshot: SPX options and Kalshi markets, back to back.
# Run by launchd every 30 minutes during market hours (see collect/com.implied-odds.snapshot.plist).
cd "$(dirname "$0")" || exit 1
mkdir -p ../data/logs
LOG="../data/logs/snapshots.log"
{
  /usr/bin/python3 options_snapshot.py
  /usr/bin/python3 kalshi_snapshot.py
} >> "$LOG" 2>&1
