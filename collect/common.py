"""Shared helpers for the snapshot collectors. Standard library only, so it runs on the system Python."""
import gzip, json, os, ssl, time, urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "raw")
UA = {"User-Agent": "Mozilla/5.0 (implied-odds research collector)"}


def get_json(url, retries=3, timeout=40):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # network hiccups: back off and retry
            last = e
            time.sleep(2 * (attempt + 1))
    raise last


def now_utc():
    return datetime.now(timezone.utc)


def out_path(kind, ts, ext="jsonl.gz"):
    """data/raw/<kind>/<YYYY-MM-DD>/<kind>_<HHMMSS>Z.<ext>, all in UTC."""
    d = os.path.join(DATA, kind, ts.strftime("%Y-%m-%d"))
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{kind}_{ts.strftime('%H%M%S')}Z.{ext}")


def write_jsonl_gz(path, rows):
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
    return path
