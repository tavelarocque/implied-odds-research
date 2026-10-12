"""Layer 14 (research/PREREGISTRATION_LAYER14.md): an LLM review committee on layer 13b's live trades.

Four roles, each one call to xAI's Grok through its Responses API: a news scout (once per run, with X and web
search), and per trade an analyst, a skeptic and a risk manager who outputs take or skip. The committee only logs;
layer 13b takes every trade, so the committee's choices can be scored against the same trades. Everything here
(roles, prompts, model name, timeouts) is frozen by the commit that adds it. Standard library only, so the cloud
runner needs nothing new. Without XAI_API_KEY in the environment the committee is skipped and logged as such.
"""
import concurrent.futures as cf
import hashlib, json, os, re, time, urllib.request

MODEL = "grok-4.7"                       # requested name; the model id the API reports back is logged on every call
URL = "https://api.x.ai/v1/responses"
CALL_TIMEOUT = 75                         # seconds per call
DEADLINE = 200                            # seconds for the whole committee; past it, unfinished trades are 'timeout'

PRINCIPLES = """You are on a review committee for a paper-trading research project, Implied Odds.
The rule under review (layer 13b) trades Kalshi's daily Bitcoin contracts ("Bitcoin at or above $K at 5pm ET",
settled on CF Benchmarks' real-time index averaged over the last minute before 5pm ET), about 3 hours before
settlement. It blends two probabilities: Kalshi's own mid price and a lognormal model built from the last 24 hours of
realized Bitcoin volatility (logit P = 0.846 logit(mid) + 0.432 logit(lognormal)). It trades only when the blend
beats the price by more than 3 cents after Kalshi's fee. The rule passed a pre-registered holdout test (April to
September 2026): about +5.7 cents per contract over 414 trades. Its edge is a calibration error: Kalshi prices are too
timid near 0% and 100%, so the rule mostly buys favourites and sells long shots.
The committee cannot change the rule. Its only output is TAKE or SKIP for each proposed trade. The default is TAKE:
the rule has a tested edge and you do not. Recommend SKIP only for a concrete reason the rule cannot see, for example:
a scheduled event before 5pm ET likely to move Bitcoin by more than the distance to the strike (a Fed decision, a US
inflation or jobs release, a major ETF or regulatory announcement), an exchange outage or index problem, breaking
news already moving the price, or an order book too thin to fill. Vague unease, chart patterns and opinions about
Bitcoin's direction are not reasons."""

SCOUT = """{principles}

Your role: NEWS SCOUT. It is now {now_utc} UTC; the contracts settle at {close_utc} UTC ({hours:.1f} hours from now).
Bitcoin is about ${spot:,.0f}. Search X and the web for anything from the last 24 hours, or scheduled before
settlement, that could move Bitcoin sharply in the next {hours:.1f} hours: macro releases and Fed speakers, ETF
flows, exchange or stablecoin incidents, regulation, large liquidations, and whatever crypto traders on X are
reacting to right now. Report in at most 150 words: (1) scheduled events before settlement, with times in UTC;
(2) breaking news already moving the price; (3) your one-line judgement: QUIET, ELEVATED or HIGH risk of a large move
before settlement. Do not recommend trades."""

TRADE = """Proposed trade: {action} 100 contracts of "Bitcoin at or above ${strike:,.0f} at 5pm ET" at {price:.0f} cents.
Bitcoin now: ${spot:,.0f} ({dist:+.2%} from the strike). Hours to settlement: {hours:.1f}.
Typical move from now to settlement at the last 24 hours' volatility: about ${move:,.0f}
(the strike is {z:.1f} typical moves away). Kalshi bid / ask: {bid:.0f} / {ask:.0f} cents; contracts shown at the
price we would take: {size}. Blend probability that Bitcoin finishes at or above the strike: {p_blend:.1%};
Kalshi mid {mid:.1%}; lognormal {p_ln:.1%}. This trade wins if Bitcoin finishes {win_side} ${strike:,.0f}.

News scout's brief:
{brief}"""

ANALYST = """{principles}

Your role: ANALYST. Explain in at most 100 words what this trade is betting on, what has to happen for it to lose, and
whether anything in the scout's brief bears on that.

{trade}"""

SKEPTIC = """{principles}

Your role: SKEPTIC. Make the strongest specific case, in at most 100 words, that this trade should be SKIPPED, using
only the facts below and the scout's brief. If you cannot find a concrete reason of the kind listed above, say so
plainly; inventing one is a failure of your role.

{trade}"""

RISK = """{principles}

Your role: RISK MANAGER. You have read the analyst and the skeptic. Decide TAKE or SKIP under the committee's rules
(default TAKE; SKIP only for a concrete reason the rule cannot see), and give your own probability that the trade
wins.

{trade}

Analyst:
{analyst}

Skeptic:
{skeptic}

Answer with one JSON object and nothing else:
{{"decision": "take" or "skip", "p_win": number between 0 and 1, "reason": "one sentence"}}"""

PROMPT_HASH = hashlib.sha256("\n".join([MODEL, PRINCIPLES, SCOUT, TRADE, ANALYST, SKEPTIC, RISK]).encode()).hexdigest()[:12]


def _call(prompt, tools=None):
    """One Responses API call. Returns {"text", "model", "usage", "secs"}; raises on failure."""
    body = {"model": MODEL, "input": [{"role": "user", "content": prompt}]}
    if tools:
        body["tools"] = tools
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {os.environ['XAI_API_KEY']}"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=CALL_TIMEOUT) as r:
        resp = json.loads(r.read().decode("utf-8"))
    text = resp.get("output_text") or ""
    if not text:
        parts = []
        for item in resp.get("output", []) or []:
            if item.get("type") == "message":
                for c in item.get("content", []) or []:
                    if c.get("type") in ("output_text", "text") and c.get("text"):
                        parts.append(c["text"])
        text = "\n".join(parts)
    if not text and resp.get("choices"):                       # chat-completions-shaped fallback
        text = resp["choices"][0].get("message", {}).get("content", "") or ""
    if not text:
        raise ValueError("empty response")
    return {"text": text.strip(), "model": resp.get("model"), "usage": resp.get("usage"), "secs": round(time.time() - t0, 1)}


def _decision(text):
    m = re.search(r"\{.*\}", text, re.S)
    d = json.loads(m.group(0)) if m else {}
    dec = str(d.get("decision", "")).strip().lower()
    if dec not in ("take", "skip"):
        raise ValueError(f"no decision in: {text[:200]}")
    p = d.get("p_win")
    p = float(p) if isinstance(p, (int, float)) and 0 <= float(p) <= 1 else None
    return dec == "take", p, str(d.get("reason", ""))[:300]


def review(ctx, trades):
    """ctx: spot, sigma_1h, tau, close_utc, now_utc. trades: layer 13b trade dicts. Returns (run_log, per_trade) where
    per_trade[i] = {"committee_take": bool|None, "p_committee": float|None, "committee_status": str}."""
    if not trades:
        return {"status": "no trades"}, []
    if not os.environ.get("XAI_API_KEY"):
        return {"status": "no_key", "prompt_hash": PROMPT_HASH}, [{"committee_take": None, "p_committee": None,
                                                                   "committee_status": "no_key"} for _ in trades]
    start = time.time()
    log = {"status": "ok", "model_requested": MODEL, "prompt_hash": PROMPT_HASH, "trades": []}
    hours = ctx["tau"]
    try:
        s = _call(SCOUT.format(principles=PRINCIPLES, now_utc=ctx["now_utc"], close_utc=ctx["close_utc"],
                               hours=hours, spot=ctx["spot"]), tools=[{"type": "x_search"}, {"type": "web_search"}])
        brief = s["text"]
        log["scout"] = s
    except Exception as e:
        brief = "(The scout could not be reached; no news brief is available.)"
        log["scout"] = {"error": str(e)[:300]}

    def one(t):
        k, spot = t["strike"], ctx["spot"]
        move = spot * ctx["sigma_1h"] * hours ** 0.5
        buy = t["side"] == "buy"
        trade = TRADE.format(action="BUY YES" if buy else f"SELL YES (= buy NO at {100 - 100 * t['price']:.0f} cents)", strike=k, price=100 * t["price"],
                             spot=spot, dist=spot / k - 1, hours=hours, move=move, z=abs(spot - k) / move,
                             bid=100 * t["bid"], ask=100 * t["ask"],
                             size=t.get("ask_size") if buy else t.get("bid_size"),
                             p_blend=t["p_blend"], mid=t["mid"], p_ln=t["p_lognormal"],
                             win_side="at or above" if buy else "below", brief=brief)
        with cf.ThreadPoolExecutor(2) as ex:
            fa = ex.submit(_call, ANALYST.format(principles=PRINCIPLES, trade=trade))
            fs = ex.submit(_call, SKEPTIC.format(principles=PRINCIPLES, trade=trade))
            a, sk = fa.result(), fs.result()
        r = _call(RISK.format(principles=PRINCIPLES, trade=trade, analyst=a["text"], skeptic=sk["text"]))
        take, p, reason = _decision(r["text"])
        return {"ticker": t["ticker"], "analyst": a, "skeptic": sk, "risk": r, "take": take, "p_win": p, "reason": reason}

    out = []
    ex = cf.ThreadPoolExecutor(min(4, len(trades)))
    futs = [ex.submit(one, t) for t in trades]
    if True:
        for t, f in zip(trades, futs):
            left = DEADLINE - (time.time() - start)
            try:
                res = f.result(timeout=max(left, 1))
                log["trades"].append(res)
                out.append({"committee_take": res["take"], "p_committee": res["p_win"], "committee_status": "ok"})
            except cf.TimeoutError:
                log["trades"].append({"ticker": t["ticker"], "error": "timeout"})
                out.append({"committee_take": None, "p_committee": None, "committee_status": "timeout"})
            except Exception as e:
                log["trades"].append({"ticker": t["ticker"], "error": str(e)[:300]})
                out.append({"committee_take": None, "p_committee": None, "committee_status": "error"})
    ex.shutdown(wait=False, cancel_futures=True)
    log["secs"] = round(time.time() - start, 1)
    models = {x.get("model") for x in [log.get("scout", {})] + [y.get(r_, {}) for y in log["trades"] for r_ in
                                                                  ("analyst", "skeptic", "risk")] if x.get("model")}
    log["models_reported"] = sorted(models)
    return log, out


if __name__ == "__main__":
    # Smoke test with today's (2026-10-11) layer 13b trade, to check the key and the API before the first live run.
    # Not part of layer 14's data: nothing is saved.  Usage: XAI_API_KEY in the environment, then
    #   python3 trade/committee.py
    t = dict(ticker="KXBTCD-26OCT1117-T83999.99", strike=83999.99, side="sell", price=0.19, bid=0.19, ask=0.20,
             bid_size=2834, ask_size=793, p_blend=0.146, mid=0.195, p_lognormal=0.213)
    ctx = dict(spot=83737, sigma_1h=0.00227, tau=3.0, close_utc="2026-10-11T21:00:00+00:00",
               now_utc="2026-10-11T18:05:50+00:00")
    log, out = review(ctx, [t])
    print(json.dumps({"status": log.get("status"), "secs": log.get("secs"), "models": log.get("models_reported"),
                      "scout": (log.get("scout") or {}).get("text") or log.get("scout"), "result": out,
                      "trade": log.get("trades")}, indent=1, default=str)[:6000])
