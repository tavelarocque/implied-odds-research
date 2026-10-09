"""Daily public attention, for layer 9 (does attention widen Kalshi's mispricing?).

Wikipedia pageviews (Wikimedia REST API, users only, all access) for a few articles that retail attention to the
markets lands on. Daily counts per UTC day, from 2022-04-01 (the start of Kalshi's index history) to yesterday.
Writes data/history/attention/wikipedia_daily.csv (date, article, views). Standard library only.

Run from collect/:  python3 attention_history.py
"""
import csv, os, sys, time, urllib.parse
from datetime import datetime, timedelta, timezone
from common import ROOT, get_json

ARTICLES = ["S&P_500", "Nasdaq-100", "Bitcoin", "Stock_market_crash", "Recession", "Stock_market"]
BASE = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user"
OUT = os.path.join(ROOT, "data", "history", "attention")


def main():
    os.makedirs(OUT, exist_ok=True)
    end = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y%m%d")
    rows = []
    for a in ARTICLES:
        url = f"{BASE}/{urllib.parse.quote(a, safe='')}/daily/20220401/{end}"
        try:
            items = get_json(url)["items"]
        except Exception as e:
            print(f"  {a}: failed {e!r}", file=sys.stderr)
            continue
        rows += [(f"{i['timestamp'][:4]}-{i['timestamp'][4:6]}-{i['timestamp'][6:8]}", a, i["views"]) for i in items]
        print(f"{a:20} {len(items)} days")
        time.sleep(0.5)
    path = os.path.join(OUT, "wikipedia_daily.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "article", "views"])
        w.writerows(sorted(rows))
    print(f"-> {path}")


if __name__ == "__main__":
    main()
