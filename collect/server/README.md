# Running the high-frequency collector on an always-on server

`collect/kalshi_hf.py` needs a process that never sleeps. On the Mac it stops whenever the lid closes. The first day
of collection (2026-10-17) lost most of 19:03–19:50 UTC that way. A small Linux server runs it without gaps, and
the Mac pulls the files when it wants them.

The collector is standard-library Python, so any Ubuntu server works. It writes about 50 KB per 5 minutes (about
15 MB a day), so the smallest size of any provider is plenty.

## One-time setup (about 15 minutes)

1. **An SSH key on the Mac**, if you don't have one (`ls ~/.ssh/id_ed25519.pub` shows one if you do):

       ssh-keygen -t ed25519
       cat ~/.ssh/id_ed25519.pub        # copy this line

2. **A server.** On DigitalOcean (or Hetzner, Vultr, Linode: any works):
   - Create a Droplet with Ubuntu 24.04 LTS, Basic plan, the smallest size, any US or Canadian region.
   - Under authentication choose SSH key and paste the line from step 1.
   - Note its IP address.

3. **Connect once**, to accept the server's fingerprint:

       ssh root@SERVER_IP 'python3 --version'

4. **Deploy**, from the Mac:

       cd ~/CODE/implied-odds
       bash collect/server/deploy.sh root@SERVER_IP

   This creates a user `hf`, copies `kalshi_hf.py` and `common.py`, installs the `kalshi-hf` service and starts it.
   It restarts on its own if it crashes or the server reboots.

5. **Stop the Mac's collector** (Ctrl-C in its Terminal window), so two copies don't write into the same folder.

## Day to day

    bash collect/server/pull.sh root@SERVER_IP                 copy new files to the Mac's data/raw/kalshi_hf
    ssh root@SERVER_IP journalctl -u kalshi-hf -n 20           the last 20 log lines ("saved N rows" every 5 min)
    ssh root@SERVER_IP systemctl status kalshi-hf              running or not
    bash collect/server/deploy.sh root@SERVER_IP               after changing kalshi_hf.py: copy it and restart

Then export and check as before:

    .venv/bin/python tools/export_hf_for_ocaml.py --days 7
    cd ~/CODE/contracts && dune exec bin/check_hf.exe -- ~/CODE/implied-odds/data/export/ocaml_hf

A good habit is to add the pull to the Sunday routine, before `weekly_update.sh`.

## Notes

- The server only reads public market data. It holds no keys, tokens or Kalshi account, so there is nothing on it to
  steal beyond the collected files.
- Times are UTC everywhere. `deploy.sh` turns on the server's clock sync.
- The seal is unchanged. Collecting is fine anywhere; comparing the data with option fair values waits for the dates
  in `research/PREREGISTRATION_LAYER16_DRAFT.md`.
