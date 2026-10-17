"""High-frequency Kalshi KXBTCD quotes and trades, with the Deribit BTC index, for market-making research.

The hourly crypto snapshot (kalshi_snapshot.py) sees each hourly contract once, which is enough to compare prices
but not to ask how a market maker would fare: that needs what happened in the minutes after each quote and each
trade (markouts). This collector polls, every HF_TICK seconds (default 5):
  - the Deribit BTC index (one call),
  - the top of book of every KXBTCD market closing in the next HF_HOURS hours (default 26) whose strike is within
    HF_BAND (default 5%) of the index, one call per event, recording a market only when its quote changed
    (plus a full keyframe every 10 minutes),
and, 4 markets a tick in turn, every trade print of up to 40 markets within HF_TRADE_BAND (default 2%) of the
index (each asks for all trades since that market's last one, so none are missed between visits). Rows go to
data/raw/kalshi_hf/<day>/kalshi_hf_<HHMMSS>Z.jsonl.gz, one file per 5 minutes. tools/export_hf_for_ocaml.py turns
them into CSVs for the OCaml contracts project.

It needs a process that stays up (the cloud workflows are hourly). Best on an always-on server: see
collect/server/README.md. On the Mac, from collect/:
    caffeinate -s python3 kalshi_hf.py                    until stopped (Ctrl-C saves the open chunk)
    HF_SECONDS=60 HF_OUT=/tmp/hf python3 kalshi_hf.py     a one-minute test into /tmp/hf
caffeinate -s stops sleep on AC power only; a Mac on battery with its lid closed still sleeps, and the book and index
have gaps for as long as it does (trades are backfilled on waking).

Seal: KXBTCD quotes from 2026-10-05 to 2026-11-27 fall inside layer 5's window. Collecting them is fine; comparing
them with option fair values before 2026-11-30 would look at layer 5's answer, so the analysis waits (see
research/PREREGISTRATION_LAYER16_DRAFT.md). Standard library only.
"""
import os, re, signal, time, urllib.error, urllib.parse
from datetime import datetime, timedelta
from common import DATA, get_json, now_utc, write_jsonl_gz

BASE = "https://api.elections.kalshi.com/trade-api/v2"
DERIBIT = "https://www.deribit.com/api/v2/public/get_index_price?index_name=btc_usd"
SERIES = "KXBTCD"
KIND = "kalshi_hf"
TICK = float(os.environ.get("HF_TICK", "5"))
HOURS = float(os.environ.get("HF_HOURS", "26"))
BAND = float(os.environ.get("HF_BAND", "0.05"))
TRADE_BAND = float(os.environ.get("HF_TRADE_BAND", "0.02"))
SECONDS = float(os.environ.get("HF_SECONDS", "0"))        # 0 = run until stopped
OUT = os.environ.get("HF_OUT", os.path.join(DATA, KIND))
REFRESH_EVERY, FLUSH_EVERY, MAX_TRADE_TICKERS, TRADES_PER_TICK = 600, 300, 40, 4
PAUSE = 0.08                                             # between quote calls
TRADE_PAUSE = 0.15                                       # between trade calls: a first test hit Kalshi's limit at 0.08


def num(x):
    try:
        return None if x is None or x == "" else float(x)
    except (TypeError, ValueError):
        return None


def utc(s):
    # Python 3.9's fromisoformat wants exactly 3 or 6 fractional digits; Kalshi sends any number.
    s = s.replace("Z", "+00:00")
    m = re.match(r"(.*T\d\d:\d\d:\d\d)(\.\d+)?(.*)$", s)
    if m and m.group(2):
        s = m.group(1) + (m.group(2) + "000000")[:7] + m.group(3)
    return datetime.fromisoformat(s)


def log(msg):
    print(f"{now_utc().isoformat(timespec='seconds')} {msg}", flush=True)


def open_markets():
    out, cursor = [], None
    while True:
        q = {"series_ticker": SERIES, "status": "open", "limit": 1000}
        if cursor:
            q["cursor"] = cursor
        page = get_json(f"{BASE}/markets?{urllib.parse.urlencode(q)}", retries=2, timeout=20)
        out += page.get("markets", [])
        cursor = page.get("cursor")
        if not cursor:
            return out


def upcoming_events(now):
    """Event tickers of KXBTCD 'above' markets closing within HOURS, nearest first."""
    closes = {}
    for m in open_markets():
        if m.get("strike_type") != "greater" or not m.get("close_time"):
            continue
        close = utc(m["close_time"])
        if now < close <= now + timedelta(hours=HOURS):
            closes[m["event_ticker"]] = close
    return sorted(closes, key=closes.get)


def recent_trades(ticker, min_ts, max_pages=20):
    """Every trade in [ticker] since [min_ts], following Kalshi's cursor: after a gap (the machine slept, the
    network dropped) a busy market can have more than one page of 1,000."""
    out, cursor = [], None
    for _ in range(max_pages):
        q = {"ticker": ticker, "min_ts": min_ts, "limit": 1000}
        if cursor:
            q["cursor"] = cursor
        page = get_json(f"{BASE}/markets/trades?{urllib.parse.urlencode(q)}", retries=1, timeout=10)
        out += page.get("trades", [])
        cursor = page.get("cursor")
        if not cursor:
            break
        time.sleep(TRADE_PAUSE)
    return out


def book_row(t, m):
    return {"type": "book", "t": t, "ticker": m["ticker"], "event": m.get("event_ticker"),
            "strike": num(m.get("floor_strike")), "close_time": m.get("close_time"),
            "yes_bid": num(m.get("yes_bid_dollars")), "yes_bid_size": num(m.get("yes_bid_size_fp")),
            "yes_ask": num(m.get("yes_ask_dollars")), "yes_ask_size": num(m.get("yes_ask_size_fp")),
            "last": num(m.get("last_price_dollars")), "volume": num(m.get("volume_fp")), "status": m.get("status")}


class Chunk:
    """Rows waiting to be written, saved every FLUSH_EVERY seconds and on exit."""

    def __init__(self):
        self.rows, self.started = [], time.time()

    def add(self, row):
        self.rows.append(row)

    def flush(self, force=False):
        if not self.rows or (not force and time.time() - self.started < FLUSH_EVERY):
            return
        ts = now_utc()
        d = os.path.join(OUT, ts.strftime("%Y-%m-%d"))
        os.makedirs(d, exist_ok=True)
        path = write_jsonl_gz(os.path.join(d, f"{KIND}_{ts.strftime('%H%M%S')}Z.jsonl.gz"), self.rows)
        log(f"saved {len(self.rows)} rows -> {path}")
        self.rows, self.started = [], time.time()


def main():
    chunk = Chunk()
    stop = {"now": False}

    def on_signal(*_):
        stop["now"] = True
    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)

    t0 = time.time()
    events, last_refresh, rr = [], 0.0, 0
    last_quote = {}           # ticker -> quote tuple: record changes only
    trade_since = {}          # ticker -> unix seconds of the newest trade already saved
    seen_trades = set()
    index = None
    chunk.add({"type": "header", "collected_utc": now_utc().isoformat(), "series": SERIES, "tick_s": TICK,
               "hours": HOURS, "band": BAND, "trade_band": TRADE_BAND})
    while not stop["now"] and (SECONDS <= 0 or time.time() - t0 < SECONDS):
        tick_start = time.time()
        now = now_utc()
        t = now.isoformat()
        try:
            if tick_start - last_refresh >= REFRESH_EVERY:
                events = upcoming_events(now)
                last_refresh = tick_start
                last_quote.clear()                # write every quote once more: a keyframe
                chunk.add({"type": "events", "t": t, "events": events})
        except Exception as e:
            log(f"event refresh failed: {e!r}")
        try:
            r = get_json(DERIBIT, retries=1, timeout=10)["result"]
            index = float(r["index_price"])
            chunk.add({"type": "index", "t": t, "index": index,
                       "estimated_delivery": num(r.get("estimated_delivery_price"))})
        except Exception as e:
            log(f"deribit index failed: {e!r}")
        near_trade = []
        for ev in events:
            try:
                ms = get_json(f"{BASE}/markets?{urllib.parse.urlencode({'event_ticker': ev, 'limit': 1000})}",
                              retries=1, timeout=10).get("markets", [])
            except Exception as e:
                log(f"{ev}: quotes failed: {e!r}")
                continue
            for m in ms:
                k = num(m.get("floor_strike"))
                if m.get("strike_type") != "greater" or k is None or index is None or abs(k / index - 1) > BAND:
                    continue
                row = book_row(t, m)
                key = (row["yes_bid"], row["yes_bid_size"], row["yes_ask"], row["yes_ask_size"], row["status"])
                if last_quote.get(m["ticker"]) != key:
                    last_quote[m["ticker"]] = key
                    chunk.add(row)
                if abs(k / index - 1) <= TRADE_BAND:
                    near_trade.append(m["ticker"])
            time.sleep(PAUSE)
        # Trades for a few markets each tick, round-robin, so a full sweep never stalls the quote polling. Each
        # call asks for everything since that market's last saved trade, so a slower revisit loses nothing.
        near_trade = near_trade[:MAX_TRADE_TICKERS]
        for _ in range(min(TRADES_PER_TICK, len(near_trade))):
            tk = near_trade[rr % len(near_trade)]
            rr += 1
            since = trade_since.get(tk, int(tick_start) - 60)
            try:
                trades = recent_trades(tk, since - 1)
            except urllib.error.HTTPError as e:
                log(f"{tk}: trades failed: {e!r}")
                if e.code == 429:                 # rate limited: back off, carry on next tick
                    time.sleep(5)
                    break
                continue
            except Exception as e:
                log(f"{tk}: trades failed: {e!r}")
                continue
            for tr in trades:
                tid = tr.get("trade_id")
                if tid in seen_trades:
                    continue
                seen_trades.add(tid)
                created = tr.get("created_time")
                chunk.add({"type": "trade", "t": created, "ticker": tk, "trade_id": tid,
                           "yes_price": num(tr.get("yes_price_dollars")), "count": num(tr.get("count_fp")),
                           "taker_side": tr.get("taker_outcome_side") or tr.get("taker_side")})
                if created:
                    trade_since[tk] = max(trade_since.get(tk, 0), int(utc(created).timestamp()))
            time.sleep(TRADE_PAUSE)
        if len(seen_trades) > 200_000:
            seen_trades = set(list(seen_trades)[-50_000:])
        chunk.flush()
        time.sleep(max(0.0, TICK - (time.time() - tick_start)))
    chunk.flush(force=True)
    log("stopped")


if __name__ == "__main__":
    main()
