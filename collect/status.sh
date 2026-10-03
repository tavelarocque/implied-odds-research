#!/bin/bash
# Shows progress of the history downloads. Run from anywhere:  bash ~/CODE/implied-odds/collect/status.sh
D="$(cd "$(dirname "$0")/.." && pwd)/data"
echo "== Running downloads"
RUN=$(ps -axo command | grep "_history.py" | grep -v -e grep -e "while " | grep -o "[a-z_]*_history.py.*")
[ -n "$RUN" ] && echo "$RUN" | sed 's/^/  /' || echo "  none: everything has finished"
echo
echo "== Kalshi markets (settled contracts per series)"
for f in "$D"/history/kalshi/markets_*.jsonl.gz; do
  [ -e "$f" ] && printf "  %-16s %s\n" "$(basename "$f" .jsonl.gz | sed 's/markets_//')" "$(gzip -dc "$f" | wc -l | tr -d ' ')"
done
echo
echo "== Hourly price files (calibration needs KXINX)"
for s in "$D"/history/kalshi/candles_60m/*/; do
  [ -d "$s" ] || continue
  name=$(basename "$s"); have=$(ls "$s" | wc -l | tr -d ' ')
  total=$(gzip -dc "$D/history/kalshi/markets_$name.jsonl.gz" 2>/dev/null | wc -l | tr -d ' ')
  pct=$(( total > 0 ? 100 * have / total : 0 ))
  printf "  %-16s %s of %s (%s%%)\n" "$name" "$have" "$total" "$pct"
done
echo
echo "== Polymarket daily S&P markets"
P="$D/history/polymarket/events.jsonl.gz"
[ -e "$P" ] && echo "  $(gzip -dc "$P" | wc -l | tr -d ' ') markets found" || echo "  still searching"
echo
echo "== Last lines of each log"
for l in "$D"/logs/history_*.log; do echo "  $(basename "$l"): $(tail -1 "$l")"; done
