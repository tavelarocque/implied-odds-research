#!/bin/bash
# Copy the collector to a fresh Ubuntu server and run it there as a service. Run from the Mac:
#     bash collect/server/deploy.sh root@SERVER_IP
# Safe to run again after changing kalshi_hf.py: it re-copies the code and restarts the service.
set -euo pipefail
host="${1:?usage: deploy.sh root@SERVER_IP}"
here="$(cd "$(dirname "$0")" && pwd)"
collect="$(dirname "$here")"
ssh "$host" 'id hf >/dev/null 2>&1 || useradd -m -s /bin/bash hf
             mkdir -p /home/hf/implied-odds/collect /home/hf/implied-odds/data/raw/kalshi_hf
             timedatectl set-ntp true || true'
scp "$collect/kalshi_hf.py" "$collect/common.py" "$host:/home/hf/implied-odds/collect/"
scp "$here/kalshi-hf.service" "$host:/etc/systemd/system/kalshi-hf.service"
ssh "$host" 'chown -R hf:hf /home/hf/implied-odds
             systemctl daemon-reload
             systemctl enable kalshi-hf
             systemctl restart kalshi-hf
             sleep 3; systemctl --no-pager --lines=5 status kalshi-hf'
echo "Running. Watch it with: ssh $host journalctl -u kalshi-hf -f"
