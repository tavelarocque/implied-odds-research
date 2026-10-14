"""Layer 5m (research/PREREGISTRATION_LAYER5M.md): a real-money mirror of layer 5's Bitcoin paper trades.

An execution study, not a new rule: every new layer 5 BTC paper trade is copied to Kalshi as a 2-contract
immediate-or-cancel limit order at the paper trade's own price (buy YES at the ask -> bid at that price; sell YES at the
bid -> ask at that price). Unfilled contracts are cancelled by the exchange and logged as misses. The paper trader is
unchanged. Brakes, checked every run before any order and enforced here, not by hand:
  - kill switch: trades live only if the GitHub variable KALSHI_LIVE is "on"; KALSHI_DEMO="on" trades the demo exchange;
  - total stop: realized mirror P&L <= -$100 (or account equity below MIRROR_START_EQUITY - $100 on live) -> no orders;
  - daily stop: realized mirror P&L on trades placed today (UTC) <= -$25 -> no new orders today;
  - exposure cap: worst-case loss of open mirror positions plus the new order <= $60.
Logs to data/raw/mirror/ (fills as "trade" rows, so paper.py's settle/pnl/digest work on them) and mirror_results/.
Keys come only from the environment (GitHub secrets). Needs the `cryptography` package for request signing.
"""
import base64, gzip, json, os, time, urllib.error, urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")
URLS = {"live": "https://external-api.kalshi.com/trade-api/v2", "demo": "https://external-api.demo.kalshi.co/trade-api/v2"}
COUNT = 2                       # contracts per order
DAILY_STOP = -25.0              # dollars, realized, trades placed today (UTC)
TOTAL_STOP = -100.0             # dollars, realized since the mirror started
MAX_EXPOSURE = 60.0             # dollars, worst-case loss of open positions incl. the new order
START_EQUITY = float(os.environ.get("MIRROR_START_EQUITY", "200"))


def mode():
    if os.environ.get("KALSHI_LIVE", "").strip().lower() == "on":
        return "live"
    if os.environ.get("KALSHI_DEMO", "").strip().lower() == "on":
        return "demo"
    return "off"


def _key(env):
    from cryptography.hazmat.primitives import serialization
    pem = os.environ["KALSHI_PRIVATE_KEY" if env == "live" else "KALSHI_DEMO_PRIVATE_KEY"].replace("\\n", "\n")
    kid = os.environ["KALSHI_KEY_ID" if env == "live" else "KALSHI_DEMO_KEY_ID"]
    return kid, serialization.load_pem_private_key(pem.encode(), password=None)


def _sign(pk, msg):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    if isinstance(pk, Ed25519PrivateKey):
        sig = pk.sign(msg.encode())
    else:
        sig = pk.sign(msg.encode(), padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
                      hashes.SHA256())
    return base64.b64encode(sig).decode()


class Client:
    def __init__(self, env):
        self.env, self.base = env, URLS[env]
        self.kid, self.pk = _key(env)

    def req(self, method, path, body=None):
        full = "/trade-api/v2" + path
        ts = str(int(time.time() * 1000))
        h = {"KALSHI-ACCESS-KEY": self.kid, "KALSHI-ACCESS-TIMESTAMP": ts,
             "KALSHI-ACCESS-SIGNATURE": _sign(self.pk, ts + method + full.split("?")[0]),
             "Content-Type": "application/json"}
        r = urllib.request.Request(self.base + path, method=method, headers=h,
                                   data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(r, timeout=20) as resp:
                return resp.status, json.loads(resp.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            return e.code, {"error": e.read().decode()[:500]}


def order_body(t, coid):
    """Paper trade -> Kalshi V2 order. Prices are YES prices in dollars; bid = buy YES, ask = sell YES (buy NO)."""
    p = float(t["price"])
    assert 0.01 <= p <= 0.99 and t["series"] == "KXBTCD"
    return {"ticker": t["ticker"], "side": "bid" if t["side"] == "buy" else "ask", "count": str(COUNT),
            "price": f"{p:.4f}", "time_in_force": "immediate_or_cancel",
            "self_trade_prevention_type": "taker_at_cross", "client_order_id": coid}


def worst_loss(side, price, qty, fee):
    return qty * (price if side == "buy" else 1 - price) + fee


def state(day):
    """Realized P&L (total, today) and worst-case open exposure from the mirror's own logs on the data branch."""
    import paper as P
    trades, results = P.all_trades("mirror", "mirror_results")
    total = today = expo = 0.0
    for d, ts in trades.items():
        for t in ts:
            r = results.get(d, {}).get(t["ticker"])
            if r in ("yes", "no"):
                pnl = P.pnl_of(t, r)
                total += pnl
                today += pnl if d == day else 0.0
            else:
                expo += worst_loss(t["side"], t["price"], t["qty"], t["fee"])
    return total, today, expo


def live(paper_trades, kpath, now):
    env = mode()
    if env == "off" or not paper_trades:
        return
    day = now.strftime("%Y-%m-%d")
    run = {"type": "run", "env": env, "decided_utc": now.isoformat(), "commit": os.environ.get("GITHUB_SHA", "local"),
           "paper_trades": len(paper_trades)}
    rows = []
    try:
        cl = Client(env)
        total, today, expo = state(day)
        run.update(realized_total=round(total, 2), realized_today=round(today, 2), open_exposure=round(expo, 2))
        st, bal = cl.req("GET", "/portfolio/balance")
        run["balance"] = bal if st == 200 else {"status": st, **bal}
        equity = (bal.get("balance", 0) + bal.get("portfolio_value", 0)) / 100 if st == 200 else None
        run["equity"] = equity
        halt = None
        if total <= TOTAL_STOP:
            halt = f"total stop: realized {total:.2f}"
        elif env == "live" and equity is not None and equity < START_EQUITY + TOTAL_STOP:
            halt = f"total stop: equity {equity:.2f} < {START_EQUITY + TOTAL_STOP:.2f}"
        elif today <= DAILY_STOP:
            halt = f"daily stop: realized today {today:.2f}"
        run["halt"] = halt
        for t in ([] if halt else paper_trades):
            fee_guess = 0.07 * t["price"] * (1 - t["price"]) * COUNT + 0.02
            new = worst_loss(t["side"], t["price"], COUNT, fee_guess)
            if expo + new > MAX_EXPOSURE:
                rows.append({"type": "skip", "ticker": t["ticker"], "reason": f"exposure {expo:.2f}+{new:.2f} > {MAX_EXPOSURE}"})
                continue
            coid = f"io5m-{t['ticker']}-{t['snap'][:19].replace(':', '')}"[:60]
            body = order_body(t, coid)
            st, resp = cl.req("POST", "/portfolio/events/orders", body)
            filled = float(resp.get("fill_count", 0) or 0) if st in (200, 201) else 0.0
            base = {"ticker": t["ticker"], "day": t["day"], "snap": t["snap"], "series": "KXBTCD", "side": t["side"],
                    "paper_price": t["price"], "paper_p_opt": t.get("p_opt"), "kind": t.get("kind"),
                    "hours_to_close": t.get("hours_to_close"), "request": body, "status": st, "response": resp}
            if filled > 0:
                px = float(resp.get("average_fill_price", t["price"]))
                fee = float(resp.get("average_fee_paid", 0) or 0) * filled
                rows.append({**base, "type": "trade", "rule": "layer5m", "price": px, "qty": filled, "fee": fee,
                             "slippage_c": round(100 * ((px - t["price"]) if t["side"] == "buy" else (t["price"] - px)), 2)})
                expo += worst_loss(t["side"], px, filled, fee)
            rows.append({**base, "type": "order", "filled": filled, "missed": COUNT - filled})
    except Exception as e:
        run["error"] = str(e)[:300]
    d = os.path.join(RAW, "mirror", day)
    os.makedirs(d, exist_ok=True)
    out = os.path.join(d, f"mirror_{os.path.basename(kpath).split('_')[-1]}")
    with gzip.open(out, "wt") as f:
        for r in [run] + rows:
            f.write(json.dumps(r, default=str) + "\n")
    n_fill = sum(1 for r in rows if r["type"] == "trade")
    print(f"mirror [{env}]: {run.get('error') or run.get('halt') or ''} {n_fill}/{len(paper_trades)} filled, "
          f"realized {run.get('realized_total')}, today {run.get('realized_today')}, exposure {run.get('open_exposure')}")
