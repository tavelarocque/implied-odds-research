#!/bin/bash
# Copy the server's collected files into the Mac's data/raw/kalshi_hf (only new or changed files). Run from the Mac:
#     bash collect/server/pull.sh root@SERVER_IP
set -euo pipefail
host="${1:?usage: pull.sh root@SERVER_IP}"
root="$(cd "$(dirname "$0")/../.." && pwd)"
mkdir -p "$root/data/raw/kalshi_hf"
rsync -a "$host:/home/hf/implied-odds/data/raw/kalshi_hf/" "$root/data/raw/kalshi_hf/"
echo "pulled: $(find "$root/data/raw/kalshi_hf" -name '*.jsonl.gz' | wc -l | tr -d ' ') files in data/raw/kalshi_hf"
