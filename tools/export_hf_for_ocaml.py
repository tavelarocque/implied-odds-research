"""Export high-frequency Kalshi data (collect/kalshi_hf.py) for the OCaml contracts project's market-making replay.

Writes into data/export/ocaml_hf/ (git-ignored):
  surfaces.csv, contracts.csv  the hourly Deribit smiles for the same days, exactly as tools/export_for_ocaml.py
  books.csv                    every recorded change of a KXBTCD top of book
  trades.csv                   every trade print collected
  index.csv                    the Deribit BTC index at each poll
  README.txt                   columns

    .venv/bin/python tools/export_hf_for_ocaml.py --date 2026-10-20
    .venv/bin/python tools/export_hf_for_ocaml.py --days 7
    .venv/bin/python tools/export_hf_for_ocaml.py --days 7 --source backfill

--source live (default) reads collect/kalshi_hf.py's files: quotes every 5 s, trades, the Deribit index.
--source backfill reads collect/kalshi_trades_backfill.py's files instead: every trade of the markets kept, for
events that closed on those days, with Kraken's last XBT/USD trade price each second as the index, and no quotes
(books.csv then only carries each market's event, strike and close). Both feed the same OCaml tools.

The OCaml side moves each hourly smile along with the index between snapshots, so it can mark any quote or trade
against an options-implied fair value at any moment. Before 2026-11-30 it refuses to compare data from layer 5's
window (2026-10-05 to 2026-11-27) with those fair values; see research/PREREGISTRATION_LAYER16_DRAFT.md.
"""
import argparse, csv, glob, gzip, json, os, subprocess, sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "tools")]
import export_for_ocaml as E

SRC = os.environ.get("HF_SRC", os.path.join(ROOT, "data", "raw", "kalshi_hf"))   # HF_SRC: e.g. a test run
OUT = os.path.join(ROOT, "data", "export", "ocaml_hf")
F17 = E.F17

README = """Implied Odds -> OCaml high-frequency export (Kalshi KXBTCD top of book and trades, Deribit BTC index)

surfaces.csv, contracts.csv: the hourly smiles for the same days; see data/export/ocaml/README.txt.

books.csv: one row per recorded change of a market's top of book (and a full set every 10 minutes)
  t            poll time (ISO 8601, UTC)
  event ticker strike close_utc
  bid ask      Kalshi YES bid and ask in dollars (0..1); empty when absent
  bid_size ask_size   contracts at the touch

trades.csv: one row per trade print
  t            the trade's time (ISO 8601, UTC)
  ticker
  price        YES price in dollars
  count        contracts
  taker_side   yes | no: the side the aggressor bought. A taker buying YES lifted the YES ask.

index.csv: t, index (USD): the Deribit BTC index (live source) or Kraken's last XBT/USD trade (backfill). The OCaml
  side moves each smile by the index's own change since the snapshot, so the two sources' level difference cancels.
"""


BACKFILL = os.path.join(ROOT, "data", "history", "kalshi", "trades", "KXBTCD")
KRAKEN = os.path.join(ROOT, "data", "history", "crypto", "kraken_1s")


def backfill_rows(days):
    """The live collector's row shapes, made from the backfill's files."""
    wanted = set(days)
    for path in sorted(glob.glob(os.path.join(BACKFILL, "*.jsonl.gz"))):
        with gzip.open(path, "rt") as f:
            rows = [json.loads(line) for line in f]
        markets = {r["ticker"]: r for r in rows if r["type"] == "market"}
        if not markets or next(iter(markets.values()))["close_time"][:10] not in wanted:
            continue
        for m in markets.values():
            yield {"type": "book", "t": m["open_time"], "event": m["event"], "ticker": m["ticker"],
                   "strike": m["strike"], "close_time": m["close_time"]}
        for r in rows:
            if r["type"] == "trade":
                yield r
    prev = str(datetime.fromisoformat(min(days)).date() - timedelta(days=1))
    for d in [prev] + sorted(days):
        path = os.path.join(KRAKEN, f"{d}.json.gz")
        if os.path.exists(path):
            with gzip.open(path, "rt") as f:
                for sec, price in json.load(f):
                    t = datetime.fromtimestamp(int(sec), timezone.utc).isoformat()
                    yield {"type": "index", "t": t, "index": float(price)}


def rows_for(day):
    for path in sorted(glob.glob(os.path.join(SRC, day, "kalshi_hf_*.jsonl.gz"))):
        with gzip.open(path, "rt") as f:
            for line in f:
                yield json.loads(line)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--date")
    ap.add_argument("--source", choices=["live", "backfill"], default="live")
    args = ap.parse_args()
    subprocess.run(["git", "fetch", "-q", "origin", "+refs/heads/data:refs/remotes/origin/data"], cwd=ROOT)
    today = datetime.now(timezone.utc).date()
    days = [args.date] if args.date else [str(today - timedelta(days=i)) for i in range(args.days - 1, -1, -1)]
    os.makedirs(OUT, exist_ok=True)
    counts = {"surfaces": 0, "contracts": 0, "bad_fit": 0, "books": 0, "trades": 0, "index": 0}
    with open(os.path.join(OUT, "surfaces.csv"), "w", newline="") as fs, \
         open(os.path.join(OUT, "contracts.csv"), "w", newline="") as fc, \
         open(os.path.join(OUT, "books.csv"), "w", newline="") as fb, \
         open(os.path.join(OUT, "trades.csv"), "w", newline="") as ft, \
         open(os.path.join(OUT, "index.csv"), "w", newline="") as fi:
        sw, cw, bw, tw, iw = (csv.writer(f) for f in (fs, fc, fb, ft, fi))
        sw.writerow(["snap_utc", "event", "close_utc", "kind", "hours_to_close", "spot", "F", "T",
                     "a", "b", "rho", "m", "s", "k_min", "k_max"])
        cw.writerow(["snap_utc", "event", "ticker", "strike", "bid", "ask", "bid_size", "ask_size", "in_range", "p_opt"])
        bw.writerow(["t", "event", "ticker", "strike", "close_utc", "bid", "ask", "bid_size", "ask_size"])
        tw.writerow(["t", "ticker", "price", "count", "taker_side"])
        iw.writerow(["t", "index"])
        seen = set()
        for d in days:
            E.export_day(d, sw, cw, counts)
        source = backfill_rows(days) if args.source == "backfill" else (r for d in days for r in rows_for(d))
        for r in source:
            kind = r.get("type")
            if kind == "book" and r.get("strike") is not None:
                bw.writerow([r["t"], r["event"], r["ticker"], F17(r["strike"]), r["close_time"],
                             F17(r.get("yes_bid")), F17(r.get("yes_ask")), F17(r.get("yes_bid_size")),
                             F17(r.get("yes_ask_size"))])
                counts["books"] += 1
            elif kind == "trade" and r.get("trade_id") not in seen and r.get("yes_price") is not None:
                seen.add(r.get("trade_id"))
                tw.writerow([r["t"], r["ticker"], F17(r["yes_price"]), F17(r.get("count")), r.get("taker_side")])
                counts["trades"] += 1
            elif kind == "index":
                iw.writerow([r["t"], F17(r["index"])])
                counts["index"] += 1
    open(os.path.join(OUT, "README.txt"), "w").write(README)
    print(f"export: {', '.join(days)} -> {os.path.relpath(OUT, ROOT)}: " +
          ", ".join(f"{v} {k}" for k, v in counts.items()))


if __name__ == "__main__":
    main()
