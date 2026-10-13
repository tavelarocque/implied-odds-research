"""Layer 14b (research/PREREGISTRATION_LAYER14B.md): a daily Grok news scout scored on fixed Bitcoin questions.

Once a day, at the crypto run at 18:05 UTC (the run nearest 18:00 UTC), whether or not layer 13b trades: one Grok call
with X and web search answers three pre-written questions about the next 24 hours, and the baselines it is scored
against are logged beside it. Every Monday, one extra fixed prompt without search (the drift probe). Logging only.
Layer 14's committee (trade/committee.py) is untouched. Writes data/raw/paper_l14b/. Standard library + numpy/pandas.
Hard cap: at most one scout call and one probe per UTC day, enforced by the files already on the data branch.
"""
import gzip, hashlib, json, math, os, re, sys, time, urllib.request
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "trade"), os.path.join(ROOT, "research")]
import options_vs_kalshi as L5
RAW = os.path.join(ROOT, "data", "raw")
MODEL = "grok-4.7"
URL = "https://api.x.ai/v1/responses"
RUN_HOUR_UTC = 18
TIMEOUT = 120

PROMPT = """You are a forecasting scout for a research project. It is now {now} UTC. Bitcoin (Coinbase BTC-USD) is at
${spot:,.0f}. Use X search and web search for news, scheduled events (US CPI, jobs, FOMC and Fed speakers, ETF flows,
exchange or regulatory news) and market conditions that bear on the next 24 hours. Then give calibrated probabilities.

Questions, all about the 24 hours from now ({now} to {end} UTC):
Q1. Will realized volatility over the next 24 hours (from hourly Coinbase returns) be above {rv_med:.2f}% (the
    median of the last 30 days' 24-hour values)? Recent context: the last 24 hours' value was {rv_last:.2f}%.
Q2. Will Bitcoin move more than {move_pct:.2f}% (up or down) between now and {end} UTC (two standard deviations of the
    last 30 days' 24-hour returns)?
Q3. Will Bitcoin be at or above ${k3:,.2f} at 5pm ET today ({close3} UTC), as settled by Kalshi's KXBTCD contract?

Rules: use only information published before now; do not guess what happens later. List every source you relied on
with its URL and publish time. List scheduled events inside the 24 hours. Answer with one JSON object and nothing else:
{{"q1": <0-1>, "q2": <0-1>, "q3": <0-1>, "events": [{{"time_utc": "...", "event": "..."}}],
  "sources": [{{"url": "...", "published_utc": "..."}}], "reasoning": "<at most 120 words>"}}"""

PROBE = """Answer in one JSON object, no search: {"a": the product of 17 and 23, "b": the capital of Australia,
"c": a one-sentence definition of the Brier score, "d": your model name and version as you know it}"""

PROMPT_HASH = hashlib.sha256("\n".join([MODEL, PROMPT, PROBE]).encode()).hexdigest()[:12]


def _call(prompt, tools=None):
    body = {"model": MODEL, "input": [{"role": "user", "content": prompt}]}
    if tools:
        body["tools"] = tools
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {os.environ['XAI_API_KEY']}"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        resp = json.loads(r.read().decode("utf-8"))
    text = resp.get("output_text") or ""
    if not text:
        text = "\n".join(c.get("text", "") for it in resp.get("output", []) or [] if it.get("type") == "message"
                         for c in it.get("content", []) or [] if c.get("type") in ("output_text", "text"))
    cites = resp.get("citations") or [a for it in resp.get("output", []) or [] if it.get("type") == "message"
                                       for c in it.get("content", []) or [] for a in c.get("annotations", []) or []]
    return {"text": text.strip(), "model": resp.get("model"), "usage": resp.get("usage"),
            "api_citations": cites, "secs": round(time.time() - t0, 1)}


def daily_stats(now):
    """From ~120 days of hourly Coinbase candles: 24-hour windows ending at the call's time of day. Returns the Q1/Q2
    thresholds and the logged baselines (climatology for Q1/Q2 over the trailing 90 days; for Q1 also a logistic
    regression of the event on log of the previous window's realized vol, fitted on the trailing 90 days)."""
    from l13d import coinbase_hourly
    end = now.floor("h")
    c = coinbase_hourly(end, 125 * 24)
    lr = np.log(c.close).diff()
    W = []                                                   # (window end, rv %, |ret| %) for each day
    for d in range(122, 0, -1):
        e = end - pd.Timedelta(days=d - 1)
        w = lr[(lr.index >= e - pd.Timedelta(hours=24)) & (lr.index < e)].dropna()
        if len(w) >= 22:
            W.append((e, 100 * math.sqrt(float((w ** 2).sum())), 100 * float(w.sum())))
    W = pd.DataFrame(W, columns=["end", "rv", "ret"]).set_index("end")
    rv, ret = W.rv, W.ret
    med30 = rv.rolling(30).median().shift(1)                 # median of the 30 windows before each window
    sd30 = ret.rolling(30).std().shift(1)
    e1 = (rv > med30).astype(float).where(med30.notna())
    e2 = (ret.abs() > 2 * sd30).astype(float).where(sd30.notna())
    last90 = W.index[-90:]
    clim1, clim2 = float(e1.loc[last90].mean()), float(e2.loc[last90].mean())
    x = np.log(rv.shift(1)).loc[last90].values; y = e1.loc[last90].values
    ok = ~(np.isnan(x) | np.isnan(y)); x, y = x[ok], y[ok]
    beta = np.zeros(2)                                       # logistic regression by Newton's method
    X = np.c_[np.ones_like(x), x]
    for _ in range(25):
        p = 1 / (1 + np.exp(-X @ beta)); w = p * (1 - p) + 1e-9
        beta += np.linalg.solve(X.T @ (X * w[:, None]) + 1e-6 * np.eye(2), X.T @ (y - p))
    rv_last = float(rv.iloc[-1])
    logit1 = float(1 / (1 + math.exp(-(beta[0] + beta[1] * math.log(rv_last)))))
    return {"rv_med30": float(rv.iloc[-30:].median()), "ret_sd30": float(ret.iloc[-30:].std()), "rv_last": rv_last,
            "spot": float(c.close.iloc[-1]), "clim_q1": clim1, "clim_q2": clim2, "logit_q1": logit1,
            "logit_beta": beta.tolist(), "n_windows": int(ok.sum())}


def q3_contract(krows, now):
    """Today's 5pm ET KXBTCD set: the strike nearest spot, and its Kalshi mid (Q3's baseline)."""
    ms = [m for m in krows if m.get("type") == "market" and m.get("series") == "KXBTCD"
          and m.get("strike_type") == "greater" and m["event_ticker"].endswith("17")
          and 0 < (L5.utc(m["close_time"]) - now).total_seconds() / 3600 <= 12]
    return ms


def already(day, kind):
    d = os.path.join(RAW, "paper_l14b", day)
    import subprocess
    try:
        names = subprocess.run(["git", "ls-tree", "-r", "--name-only", "origin/data", f"data/raw/paper_l14b/{day}/"],
                               cwd=ROOT, capture_output=True, text=True).stdout.split()
    except Exception:
        names = []
    local = os.listdir(d) if os.path.isdir(d) else []
    return any(kind in os.path.basename(n) for n in names + local)


def live(krows, kpath, now):
    now = pd.Timestamp(now)
    if now.hour != RUN_HOUR_UTC:
        return
    day = now.strftime("%Y-%m-%d")
    out_dir = os.path.join(RAW, "paper_l14b", day)
    stamp = os.path.basename(kpath).split("_")[-1]
    keyed = bool(os.environ.get("XAI_API_KEY"))
    recs = []
    if not already(day, "scout"):
        rec = {"type": "scout", "day": day, "decided_utc": now.isoformat(), "model_requested": MODEL,
               "prompt_hash": PROMPT_HASH, "commit": os.environ.get("GITHUB_SHA", "local")}
        try:
            st = daily_stats(now)
            rec.update(st)
            ms = q3_contract(krows, now)
            spot = st["spot"]
            m3 = min(ms, key=lambda m: abs(float(m["floor_strike"]) - spot)) if ms else None
            if m3 is not None:
                bid, ask, _, _ = L5.kalshi_quote(m3)
                rec.update(q3_ticker=m3["ticker"], q3_strike=float(m3["floor_strike"]), q3_close=m3["close_time"],
                           q3_kalshi_mid=(bid + ask) / 2 if bid > 0 and ask is not None else None)
            end = (now + pd.Timedelta(hours=24)).isoformat()
            rec["window_end_utc"] = end
            if not keyed:
                rec["status"] = "no_key"
            elif m3 is None:
                rec["status"] = "no_q3_contract"
            else:
                prompt = PROMPT.format(now=now.isoformat(), end=end, spot=spot, rv_med=st["rv_med30"],
                                       rv_last=st["rv_last"], move_pct=2 * st["ret_sd30"], k3=rec["q3_strike"],
                                       close3=rec["q3_close"])
                r = _call(prompt, tools=[{"type": "x_search"}, {"type": "web_search"}])
                rec["response"] = r
                m = re.search(r"\{.*\}", r["text"], re.S)
                ans = json.loads(m.group(0)) if m else {}
                for q in ("q1", "q2", "q3"):
                    v = ans.get(q)
                    rec[f"scout_{q}"] = float(v) if isinstance(v, (int, float)) and 0 <= float(v) <= 1 else None
                rec["events"], rec["sources"] = ans.get("events"), ans.get("sources")
                late = []
                for s in ans.get("sources") or []:
                    try:
                        ts = pd.Timestamp(s.get("published_utc"))
                        ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts
                        if ts > now:
                            late.append(s.get("url"))
                    except Exception:
                        pass
                rec["late_sources"] = late                      # any entry here excludes the day (leakage)
                rec["status"] = "ok" if all(rec.get(f"scout_{q}") is not None for q in ("q1", "q2", "q3")) else "parse_error"
        except Exception as e:
            rec["status"] = "error"; rec["error"] = str(e)[:300]
        recs.append(rec)
    if now.dayofweek == 0 and keyed and not already(day, "probe"):
        try:
            recs.append({"type": "probe", "day": day, "decided_utc": now.isoformat(), "prompt_hash": PROMPT_HASH,
                         "response": _call(PROBE)})
        except Exception as e:
            recs.append({"type": "probe", "day": day, "error": str(e)[:300]})
    if not recs:
        return
    os.makedirs(out_dir, exist_ok=True)
    for r in recs:
        with gzip.open(os.path.join(out_dir, f"{r['type']}_{stamp}"), "wt") as f:
            f.write(json.dumps(r, default=str) + "\n")
        print(f"paper l14b: {r['type']} {r.get('status', 'logged')}"
              + (f" q1 {r.get('scout_q1')} q2 {r.get('scout_q2')} q3 {r.get('scout_q3')}" if r["type"] == "scout" else ""))
