#!/bin/bash
# Backstop for the cloud snapshot schedule. GitHub's cron for this repo has been unreliable (no runs during market
# hours on 2026-10-05 and 2026-10-06 despite an active workflow), so launchd on the Mac asks GitHub to run the
# snapshot workflow on the same half-hourly grid. It skips if any snapshot run started in the last 15 minutes, so it
# never doubles up when GitHub's own schedule does fire. The work itself still runs in the cloud.
export PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin
cd "$HOME/CODE/implied-odds" || exit 1
log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*"; }
last=$(gh run list -w snapshot.yml -L 1 --json createdAt -q '.[0].createdAt' 2>/dev/null)
if [ -n "$last" ]; then
  age=$(( $(date -u +%s) - $(date -j -u -f '%Y-%m-%dT%H:%M:%SZ' "$last" +%s) ))
  if [ "$age" -lt 900 ]; then log "skip: a run started ${age}s ago"; exit 0; fi
fi
# After a sleep/wake the network can take a few seconds to come back, so retry before giving up.
for try in 1 2 3; do
  if err=$(gh workflow run snapshot.yml --ref main 2>&1); then log "dispatched (try $try)"; exit 0; fi
  sleep 20
done
log "dispatch FAILED after 3 tries: $(echo "$err" | tail -1)"; exit 1
