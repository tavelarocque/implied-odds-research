#!/bin/bash
# Weekly refresh: pull newly settled Kalshi and Polymarket markets, their prices, re-check the data, and
# report how many live snapshots were captured each weekday. Safe to run any time; it only adds what's new.
# Usage:  bash ~/CODE/implied-odds/collect/weekly_update.sh
cd "$(dirname "$0")" || exit 1
PY=/usr/bin/python3
SINCE=$(date -v-21d +%Y-%m-%d 2>/dev/null || date -d '21 days ago' +%Y-%m-%d)
echo "== Kalshi: newly settled markets"
$PY kalshi_history.py markets --series KXINX KXINXZ KXNASDAQ100 KXNASDAQ100Z
echo; echo "== Kalshi: hourly prices for markets closed since $SINCE"
$PY kalshi_history.py candles --period 60 --series KXINX --since "$SINCE"
echo; echo "== Polymarket: new daily S&P markets and their prices"
$PY polymarket_history.py events --start 2025-01-01
$PY polymarket_history.py prices --fidelity 60
echo; echo "== Data checks"
$PY validate_kalshi.py 2>/dev/null | grep -v -i warn
echo; echo "== Live snapshots captured, last 10 days (15 scheduled per weekday)"
for d in $(ls ../data/raw/spx_options 2>/dev/null | tail -10); do
  n=$(ls ../data/raw/spx_options/$d 2>/dev/null | wc -l | tr -d ' ')
  dow=$(date -j -f %Y-%m-%d "$d" +%a 2>/dev/null || date -d "$d" +%a)
  printf "  %s %s  %2s snapshots %s\n" "$d" "$dow" "$n" "$( [ "$n" -lt 12 ] && [ "$dow" != Sat ] && [ "$dow" != Sun ] && echo '<- gaps: was the Mac asleep?')"
done
echo; echo "Done. Intraday files: $(ls ../data/raw/intraday 2>/dev/null | wc -l | tr -d ' ')"
