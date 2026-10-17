"""Export high-frequency Kalshi data (collect/kalshi_hf.py) for the OCaml contracts project's market-making replay.

Writes into data/export/ocaml_hf/ (git-ignored):
  surfaces.csv, contracts.csv  the hourly Deribit smiles for the same days, exactly as tools/export_for_ocaml.py
  books.csv                    every recorded change of a KXBTCD top of book
  trades.csv                   every trade print collected
  index.csv                    the Deribit BTC index at each poll
  README.txt                   columns

    .venv/bin/python tools/export_hf_for_ocaml.py --date 2026-10-20
    .venv/bin/python tools/export_hf_for_ocaml.py --days 7

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

index.csv: t, index (Deribit BTC index, USD)
"""


def rows_for(day):
    for path in sorted(glob.glob(os.path.join(SRC, day, "kalshi_hf_*.jsonl.gz"))):
        with gzip.open(path, "rt") as f:
            for line in f:
                yield json.loads(line)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--date")
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
            for r in rows_for(d):
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
