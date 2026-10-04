"""POST HOC (written after the Nasdaq calibration found one profitable bucket; not part of the pre-registration).

The calibration study checks every price bucket x side (buy YES / buy NO) x horizon with at least 100 quotes,
about 100 combinations, and found one where a taker made money. How often would a search that size find a
"winner" this strong if Kalshi's prices were exactly fair?

Monte Carlo (Masters' logic applied to outcomes instead of prices): simulate thousands of fake histories in which
each quote settles YES with probability equal to its own midpoint (the market is fair; you still pay the spread and
the fee). Run the full bucket search on each and record the strongest result, measured as a t-stat
with standard errors clustered by trading day. The share of fake histories whose best t-stat beats the real best
is a family-wise p-value: the chance of a winner this strong across the whole search, by luck alone.

Assumption: simulated outcomes are independent across contracts. Real ladders have exactly one winner a day,
which makes same-day outcomes slightly negatively correlated; the day-clustered t-stat is computed the same way in
both worlds.

Run from the project root:  python3 research/posthoc_longshot_mc.py [SERIES] [n_sims]   (default KXNASDAQ100, 2000)
"""
import os, sys
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERIES = sys.argv[1] if len(sys.argv) > 1 else "KXNASDAQ100"
N = int(sys.argv[2]) if len(sys.argv) > 2 else 2000
SRC = os.path.join(ROOT, "research", "output", "calibration" if SERIES == "KXINX" else f"calibration_{SERIES}", "quotes.csv.gz")
OUT = os.path.join(ROOT, "research", "output", f"posthoc_longshot_mc_{SERIES}")
BINS = [0, .02, .05, .10, .20, .30, .40, .50, .60, .70, .80, .90, .95, .98, 1.0]   # as research/calibration.py
FEE_RATE, MIN_N = 0.07, 100
rng = np.random.default_rng(42)

q = pd.read_csv(SRC)                                   # pre-holdout quotes written by research/calibration.py
q["bin"] = pd.cut(q.mid, BINS, include_lowest=True).astype(str)
q["combo"] = q.h.astype(str) + "h " + q.bin
sizes = q.groupby("combo").size()
q = q[q.combo.isin(sizes[sizes >= MIN_N].index)].reset_index(drop=True)

# Fair probability under the null: each quote's own midpoint, and each quote gets its own simulated outcome.
# (Using one outcome per contract drawn from its last price would replay the real price path in every simulated
# world and hand earlier-horizon buckets a fixed, fake edge. Independent draws across horizons make the search
# look like more independent tries than it really is, so this null is, if anything, conservative.)
p_fair = q.mid.values

combo_codes, combos = pd.factorize(q.combo)
day_codes, days = pd.factorize(q.event)
K, D = len(combos), len(days)
cd = combo_codes * D + day_codes                        # (combo, day) cell for clustered sums
G = (np.bincount(cd, minlength=K * D).reshape(K, D) > 0).sum(axis=1)   # trading days per combo


# Profit scaled by the outcome noise the fair-price null implies, sqrt(sum p(1-p)), identical in both worlds.
# A t-stat estimates its noise from the data, and with 1-2 cent contracts that settle YES once in hundreds of
# trades, the data badly understates the noise (the same failure that collapsed the holdout bootstrap).
NULL_SD = np.sqrt(np.bincount(combo_codes, weights=p_fair * (1 - p_fair), minlength=len(combos)))


def max_scaled(y):
    best = (-np.inf, None, None)
    for side, pnl in (("yes", y - q.ask.values - FEE_RATE * q.ask.values * (1 - q.ask.values)),
                      ("no", q.bid.values - y - FEE_RATE * q.bid.values * (1 - q.bid.values))):
        z = np.bincount(combo_codes, weights=pnl, minlength=len(combos)) / NULL_SD
        k = int(np.argmax(z))
        if z[k] > best[0]:
            best = (float(z[k]), combos[k], side)
    return best


def max_t(y):
    """Strongest buy-YES or buy-NO result across all combos, as a day-clustered t-stat. Returns (t, combo, side)."""
    best = (-np.inf, None, None)
    for side, pnl in (("yes", y - q.ask.values - FEE_RATE * q.ask.values * (1 - q.ask.values)),
                      ("no", q.bid.values - y - FEE_RATE * q.bid.values * (1 - q.bid.values))):
        n_k = np.bincount(combo_codes, minlength=K)
        mean_k = np.bincount(combo_codes, weights=pnl, minlength=K) / n_k
        resid = pnl - mean_k[combo_codes]
        cell = np.bincount(cd, weights=resid, minlength=K * D).reshape(K, D)
        se = np.sqrt((cell ** 2).sum(axis=1) * G / np.maximum(G - 1, 1)) / n_k
        t = np.where(se > 1e-9, mean_k / se, -np.inf)
        k = int(np.argmax(t))
        if t[k] > best[0]:
            best = (float(t[k]), combos[k], side)
    return best


real_t, real_combo, real_side = max_t(q.y.values.astype(float))
real_z, z_combo, z_side = max_scaled(q.y.values.astype(float))
sims, simz = [], []
for _ in range(N):
    y = (rng.random(len(q)) < p_fair).astype(float)
    sims.append(max_t(y)[0]); simz.append(max_scaled(y)[0])
sims, simz = np.array(sims), np.array(simz)
p = (1 + np.sum(sims >= real_t)) / (1 + N)
pz = (1 + np.sum(simz >= real_z)) / (1 + N)

print(f"POST HOC Monte Carlo, {SERIES}: {K} bucket x horizon combos with >= {MIN_N} quotes, x 2 sides = {2 * K} tested")
print(f"real data: strongest result {real_side.upper()} in {real_combo}, t = {real_t:.2f}")
print(f"fair-price world ({N} simulations): strongest t median {np.median(sims):.2f}, 95th pct {np.percentile(sims, 95):.2f}")
print(f"family-wise p = {p:.3f}  (t-stat noise estimated from the data: unreliable for rare losses)")
print(f"PRIMARY, profit scaled by fair-price noise: strongest {z_side.upper()} in {z_combo}, score {real_z:.2f}; "
      f"fair-price world median {np.median(simz):.2f}, 95th pct {np.percentile(simz, 95):.2f}")
print(f"family-wise p = {pz:.3f}  ->  {'unlikely to be search luck' if pz < 0.05 else 'consistent with search luck'}")
os.makedirs(OUT, exist_ok=True)
pd.DataFrame({"sim_max_t": sims}).to_csv(os.path.join(OUT, "sims.csv"), index=False)
pd.DataFrame([{"series": SERIES, "combos": K, "real_max_t": real_t, "combo": real_combo, "side": real_side,
               "p_familywise_t": p, "real_max_scaled": real_z, "scaled_combo": z_combo,
               "scaled_side": z_side, "p_familywise_scaled": pz, "n_sims": N}]).to_csv(os.path.join(OUT, "summary.csv"), index=False)
