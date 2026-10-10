#!/bin/bash
# Backstop for the hourly Bitcoin schedule (.github/workflows/crypto.yml). GitHub's cron never fired it on its own on
# 2026-10-09 (every run that day was a manual dispatch, and the stock snapshot's scheduled runs arrived up to 90 minutes
# late), so launchd on the Mac asks GitHub to run it every hour at :09. It skips if any crypto run started in the last
# 30 minutes, so it never doubles up when GitHub's own schedule fires. The work itself still runs in the cloud.
export PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin
cd "$HOME/CODE/implied-odds" || exit 1
log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*"; }
last=$(gh run list -w crypto.yml -L 1 --json createdAt -q '.[0].createdAt' 2>/dev/null)
if [ -n "$last" ]; then
  age=$(( $(date -u +%s) - $(date -j -u -f '%Y-%m-%dT%H:%M:%SZ' "$last" +%s) ))
  if [ "$age" -lt 1800 ]; then log "skip: a run started ${age}s ago"; exit 0; fi
fi
for try in 1 2 3; do
  if err=$(gh workflow run crypto.yml --ref main 2>&1); then log "dispatched (try $try)"; exit 0; fi
  sleep 20
done
log "dispatch FAILED after 3 tries: $(echo "$err" | tail -1)"; exit 1
