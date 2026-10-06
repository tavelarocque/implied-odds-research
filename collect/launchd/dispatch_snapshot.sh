#!/bin/bash
# Backstop for the cloud snapshot schedule. GitHub's cron for this repo has been unreliable (no runs during market
# hours on 2026-10-05 and 2026-10-06 despite an active workflow), so launchd on the Mac asks GitHub to run the
# snapshot workflow on the same half-hourly grid. It skips if any snapshot run started in the last 20 minutes, so it
# never doubles up when GitHub's own schedule does fire. The work itself still runs in the cloud.
export PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin
cd "$HOME/CODE/implied-odds" || exit 1
log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*"; }
last=$(gh run list -w snapshot.yml -L 1 --json createdAt -q '.[0].createdAt' 2>/dev/null)
if [ -n "$last" ]; then
  age=$(( $(date -u +%s) - $(date -j -u -f '%Y-%m-%dT%H:%M:%SZ' "$last" +%s) ))
  if [ "$age" -lt 1200 ]; then log "skip: a run started ${age}s ago"; exit 0; fi
fi
if gh workflow run snapshot.yml --ref main >/dev/null 2>&1; then log "dispatched"; else log "dispatch FAILED"; exit 1; fi
