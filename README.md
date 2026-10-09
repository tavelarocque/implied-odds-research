# Implied Odds

Do prediction markets and options markets agree on the odds of the same event? This project compares
Kalshi's S&P 500 and Nasdaq-100 contracts against probabilities implied by SPX option prices, and studies
where, when and why they disagree. Every claimed edge goes through one shared robustness layer.

## Layers

| Layer | Folder | Question |
|---|---|---|
| Robustness | `robustness/` | Is a backtest result real, or the luckiest of many tries? Deflated Sharpe ratio, probability of backtest overfitting (CSCV), minimum track record length. Tested in `tests/`. |
| Strategy discovery | `research/strategy_discovery.py` | Search 2,120 rule-based strategies on SPY and nine sector ETFs: how much of the best backtest survives out of sample? |
| Implied Odds | `research/calibration.py`, `research/cross_venue.py` and later phases | Are Kalshi's S&P contracts calibrated, do they agree with Polymarket and with option-implied probabilities? |

## Code map

```
implied-odds/
├── robustness/          Layer 2: is a result real or luck?
│   └── overfitting.py     deflated Sharpe, probabilistic Sharpe, PBO via CSCV, minimum track record
├── strategies/          Layer 3's library
│   ├── rules.py           momentum, moving-average cross, mean reversion, breakout
│   └── backtest.py        signals -> positions (shifted a day) -> returns after costs
├── implied/             Layer 5: option-implied probabilities
│   ├── bl.py              forward from put-call parity, SVI smile fit, Breeden-Litzenberger probabilities
│   └── kalshi_ladder.py   Kalshi range ladder -> P(close > K), and the cost of trading it
├── collect/             Layer 1: data
│   ├── options_snapshot.py, kalshi_snapshot.py, run_snapshot.sh   live snapshots every 30 min
│   ├── kalshi_history.py, polymarket_history.py, etf_prices.py    history pullers
│   ├── intraday.py        daily one-minute S&P prices for layer 7
│   ├── validate_kalshi.py data checks
│   └── status.sh          download progress
├── research/            one script per study; each writes to research/output/
│   ├── config.py          the locked holdout
│   ├── strategy_discovery.py, calibration.py, cross_venue.py, fair_value_snapshot.py
├── tests/               python3 run_tests.py runs them all
└── notebooks/tour.ipynb a guided walk through the code
```

Start with `notebooks/tour.ipynb`. Every research script is also split into `# %%` cells, so VS Code can run
it cell by cell like a notebook.

### Research discipline

- **Locked holdout.** Kalshi data from 2026-04-01 onward is reserved for the final test of any trading rule
  or model. It was fixed on 2026-10-03, before any calibration result was seen (`research/config.py`).
- **Data checks.** `collect/validate_kalshi.py` confirms no duplicate contracts, one winner per trading day
  (2 of 1,131 days fail and are excluded), and that every Kalshi settlement value matches the S&P 500 close
  (1,126 of 1,126 within 5 cents). Run with `KXNASDAQ100`, it checks the Nasdaq-100 history the same way: 1 of 1,146
  days excluded, 1,137 of 1,139 settlements match ^NDX within 5 cents.
- **Live snapshot checks.** `collect/check_snapshots.py --cloud` inspects the latest cloud snapshot of every kind:
  crossed quotes, option-smile fits that integrate to one with no negative mass, Kalshi ladders that are contiguous
  and can't be bought or sold as a whole for free, sorted Polymarket books. It also lines the three sources up on the
  same moment (option-implied probabilities against Kalshi bid-ask and the Polymarket Up price). Its first run caught
  the Nasdaq option fit failing: see `tests/test_sparse_wing.py`.
- **Tested tools.** The fifth test, `test_sparse_wing`, rebuilds a real failure: Nasdaq upside calls are cheap
  with wide spreads, so the smile was fitted with almost no upside quotes and bent into an impossible density (mass
  2.2). The fit now penalizes butterfly arbitrage (Durrleman's condition), Lee's wing bound and negative variance
  across the whole range probabilities are read from, and the forward survives a parity slope just above 1.
- **More on tests.** `python3 run_tests.py` runs seven tests, including the Kalshi ladder maths (exact on range
  boundaries, within 0.16 pp between them, correct basket costs and fees). The other three: the robustness layer rejects pure noise and finds a
  planted edge; Breeden-Litzenberger recovers known probabilities from noisy quotes (within 0.01 pp on a flat
  smile, 0.63 pp on a skewed one); and no strategy rule can see future prices (864 perturbation checks).

### Result: Kalshi vs Polymarket (layer 6)

Polymarket's daily "SPX up or down" market and Kalshi's S&P range ladder price the same event: from 2025-10-16
both settle on the official close versus the previous close (Polymarket's first market, 2025-10-15, compared with
the same day's open and is excluded). Over 103 trading days (Oct 2025 to Mar 2026, holdout excluded), the two
venues' settlement data agree on all 113 outcomes.

- **They agree.** Kalshi's probability, built from bids on its range ladder, tracks Polymarket's closely; the
  average gap falls from 9 points six hours before the close to 4 points in the final hour.
- **Neither forecasts better.** Brier scores are statistically tied at every hour (day-level bootstrap).
- **No arbitrage.** A package guaranteed to pay $1 (Polymarket on one side, every Kalshi range on the other)
  never cost less than $1.045, median $1.47. Kalshi has no single up/down contract, so the trade needs a basket
  of about 17 range contracts, and their spreads cost about 40 cents.
- **A methodology trap, caught.** Valuing Kalshi's ladder at bid-ask midpoints puts about 20% of probability in
  far-out ranges nobody bids on, which drags estimates toward 50% and made Polymarket look more accurate near
  the close. Using bids only removes the artifact; both versions are reported in `research/cross_venue.py`.

### Result: calibration (layer 4)

Kalshi's S&P 500 daily range contracts are well calibrated. Across 1,129 trading days (April 2022 to March 2026,
holdout excluded) and 15,000+ quotes, contracts priced at p paid out close to p of the time at every horizon from
1 to 24 hours before the close. There is a small favourite-longshot bias in the last hours: the calibration slope is
1.09 one hour before the close (95% interval 1.01 to 1.20, resampling whole days) and 1.11 three hours before,
meaning cheap contracts win slightly less often than priced. It is too small to exploit: no price bucket made money
for a taker after the bid-ask spread and Kalshi's fee. The bias was strongest in 2022 (slope 1.44 at one hour) and
has faded toward 1.0 since 2024, consistent with a market that became more efficient as it grew.

### Result: Nasdaq-100 replication (pre-registered)

Both studies were rerun on the Nasdaq-100 with the series switched and nothing else changed. The pass criteria were
committed in `research/PREREGISTRATION.md` before any Nasdaq result existed. **4 of 6 criteria pass; 2 fail.**

| Criterion | Nasdaq-100 | Verdict |
|---|---|---|
| Calibration: slope b > 1 at 1h or 3h, 95% interval excluding 1 | 1h: 1.07 (0.99 to 1.15); 3h: 1.09 (1.01 to 1.17) | Pass (3h) |
| Calibration: no price bucket profitable for a taker after spread and fees | Selling the 0 to 2 cent long shots 1h before the close: +0.72 cents per contract (0.13 to 0.93), 473 quotes | **Fail** |
| Calibration: 2025-26 1h slope closer to 1 than 2022 | 2022: 1.38; 2025: 0.94; 2026: 0.99 | Pass |
| Cross-venue: bids-only gap smaller at 1h than 6h | 6.8pp vs 11.1pp (lowest at 2h, 5.0pp) | Pass |
| Cross-venue: no significant Brier difference at any horizon | Bids-only Kalshi is significantly more accurate at 1h (Brier 0.033 vs 0.058) and 4h | **Fail** |
| Cross-venue: no package paying $1 costs under $1 after fees | Cheapest $1.07, median $1.45, never under $1 | Pass |

Data: 1,146 Kalshi trading days (1 excluded, 1,137 of 1,139 settlements match ^NDX); 386 matched cross-venue
observations over 98 days; Polymarket's outcome agrees with Kalshi's settlement on 113 of 113 days.

How to read the failures:
- *The profitable bucket* is small and may be chance. The study tests about 100 bucket, side and horizon
  combinations, so a few would clear a 95% bar by luck; the S&P study found none. It is now a specific, written-down
  hypothesis (sell Nasdaq contracts priced under 2 cents one hour before the close), and the untouched holdout from
  2026-04-01 is where it gets one clean test.
- *The accuracy difference* goes the opposite way to the S&P midpoint artifact: with the bids-only estimator, Kalshi's
  Nasdaq ladder beat Polymarket's single up/down market at two of six horizons. Both venues still price the same
  information within a few points and leave no arbitrage, which is the core layer-6 finding, and that replicated.

**Holdout test of the long-shot rule (run once, 2026-10-03).** The rule and pass bar were committed
(`research/PREREGISTRATION.md`, addendum) before the holdout was opened; `research/holdout_longshot.py` ran it.
195 qualifying contracts over 91 trading days (April to October 2026), all with a 1 cent bid; **none settled YES**.
Every trade earned the same +0.93 cents, so by the letter of the pre-registered bar it **passes**.

That verdict is weaker than it looks, and the bar I wrote is why. With zero losses, a bootstrap has no variation to
resample, so its interval collapses to a single point. The real question is the hit rate: the rule breaks even if
more than 0.93% of these contracts settle YES, and 0 hits in 195 only bounds the true rate below 1.87% (exact 95%
interval). So the holdout cannot rule out a losing rule. Before the holdout the rate was 1 in 473. This is the
classic short-option profile: steady pennies, rare 99-cent losses, and a sample too small to see the tail. Verdict:
consistent with a small edge, not yet shown; the live snapshots keep counting, and the right test is a hit-rate
bound that falls below 0.93%, which needs several hundred more contracts. Lesson for future pre-registrations: for
rare-loss strategies, set the bar on the loss rate, not on a bootstrap of the mean.

**Post hoc: why Kalshi beat Polymarket on the Nasdaq-100** (`research/posthoc_venue_accuracy.py`; added after the
results were seen, so it explains and does not test). Polymarket's Nasdaq market is about 20 times thinner than its
S&P market: median volume $7,316 per day vs $143,222. Its price moves on 74% of 10-minute steps in the last six hours,
vs 86% for the S&P. Pooled over horizons, Kalshi's Brier score is 0.078 vs Polymarket's 0.092 on the Nasdaq
(difference -0.014, 95% interval -0.021 to -0.006); on the S&P the two are tied (+0.002, -0.007 to +0.011). Within the
Nasdaq, Polymarket's busier days don't close the gap (-0.013 vs -0.016 on quieter days), but even its busier Nasdaq days
are far thinner than a typical S&P day, so that split can't separate the explanations. Reading: thin markets price
less accurately, which is consistent with the data but not proven by it.

### Result so far: strategy discovery

Searching harder makes the in-sample winner look better and perform worse. Picking the best of 1,000 rules
by 2000–2012 Sharpe gives an average in-sample Sharpe of 1.02 and an out-of-sample (2013–2026) Sharpe of 0.05,
against 0.92 for simply holding SPY. The single best rule (a consumer-staples mean-reversion rule, in-sample 1.06)
lost money out of sample; its deflated Sharpe of 0.70 had already flagged it as not significant.

### Result: who leads price discovery, Kalshi or Polymarket? (layer 3, pre-registered)

`research/PREREGISTRATION_LAYER3.md` was committed (2026-10-04 12:12) before any minute-level result. When the venues
disagree about "will the index close above yesterday's close?", which one moves to meet the other? Regress each venue's
next 10-minute change on the gap 10 minutes earlier (lagged so quote noise can't fake a follower); Kalshi's share of
the adjustment above 0.5 means Polymarket leads. Data: 1-minute Kalshi candles (14,580 contracts), Polymarket's
10-minute history, 113 days per index before the holdout.

| | S&P 500 | Nasdaq-100 |
|---|---|---|
| Gap closes (bK - bP, 95% interval) | 0.084 (0.046 to 0.127) | 0.098 (0.058 to 0.153) |
| Permutation p (1,000 day shuffles) | 0.001 | 0.001 |
| Kalshi's share of the adjustment | 0.42 (-0.09 to 0.76) | 0.53 (0.05 to 0.82) |
| **Verdict** | **no detectable leader** | **no detectable leader** |
| Implied half-life of a disagreement | about 80 minutes | about 70 minutes |

Both venues move toward each other in roughly equal measure. The prediction that Kalshi would lead on the thin
Polymarket Nasdaq market was not supported. Table shows the alignment-corrected run.

**An alignment error, found and fixed.** The pre-registered run gave the same verdicts (shares 0.42 and 0.49), but its
lead-lag table was wrong: the venues' changes were uncorrelated in the same window (0.02) and strongly correlated with
a 10-minute shift (0.66). Two venues on the same index shouldn't behave that way. `research/diag_poly_timing.py` checked
alignment minute by minute and found Polymarket's prices stamped a few seconds after each 10-minute mark, so the
pre-registered rule "last price at or before each grid time" always picked the price from about 9.8 minutes earlier.
The corrected run (`ALIGN=poly`) reads Kalshi at Polymarket's exact stamps and changes nothing else; same-window
correlation becomes 0.66 (S&P) and 0.53 (Nasdaq). At minute resolution Kalshi may lead by up to a minute, which
10-minute Polymarket data can't resolve.

### Result: Masters' permutation tests (layer 2, third method)

`robustness/permutation.py` adds Timothy Masters' Monte Carlo permutation tests. They shuffle the order of daily
returns, which keeps the first and last price, volatility, skew and same-day correlation across the 10 ETFs but
destroys any real pattern, and then rerun the *entire* search on each shuffled history. Tested in
`tests/test_permutation.py` (keeps what it should, misses nothing planted, flags nothing in noise). Caveat: shuffling
also destroys volatility clustering, so strategies that live on it look better than they are, never worse.
`research/permutation_tests.py`, 1,000 shuffles each, data before the holdout:

| Test | Real data | Shuffled histories | p |
|---|---|---|---|
| In-sample (1999-2012): best Sharpe of ~2,000 rules | 1.06 | median 0.80, 95th pct 1.02 | 0.031 |
| Walk-forward (2005-2026): re-pick the best rule every month on the trailing 5 years | Sharpe 0.19 (SPY 0.62) | median 0.17, 95th pct 0.49 | 0.45 |

Search luck alone produces an in-sample Sharpe of about 0.8, so most of the winner's 1.06 is the search. It misses
Masters' 1% bar. Walked forward the way it would really trade, the search is indistinguishable from a worthless
one, and earns a third of buy-and-hold's Sharpe. Three independent methods agree: deflated Sharpe 0.70, PBO 0.20,
and now both permutation tests.

**Post hoc: fair-market Monte Carlo of the Kalshi bucket search** (`research/posthoc_longshot_mc.py`). Simulate
2,000 histories in which every quote is exactly fair at its midpoint (you still pay spread and fee), rerun the full
bucket x side x horizon search on each, and compare the best result with the real best. Profit is scaled by the noise
the fair price implies, the same in both worlds.

| Series | Combinations searched | Real best | Fair-market best (median, 95th pct) | Family-wise p |
|---|---|---|---|---|
| Nasdaq-100 | 58 | sell under-2-cent contracts 1h out: 1.19 | 0.86, 1.78 | 0.26 |
| S&P 500 | 66 | buy 80-90 cent contracts 1h out: 1.02 | 1.05, 1.98 | 0.54 |

The Nasdaq long-shot bucket is what a 58-way search of a fair market finds about a quarter of the time. The usual
t-statistic says otherwise (p 0.003), but it estimates noise from data with one loss in 473 trades, the same
failure that collapsed the holdout bootstrap; the script prints both so the difference is visible.

## Research plan

1. **Data pipeline.** Live matched snapshots of SPX options and Kalshi markets (running now), plus Kalshi's
   historical candlesticks for settled markets.
2. **Calibration.** Do Kalshi contracts priced at p resolve with frequency p? Tests for favourite–longshot bias.
3. **Options-implied fair value.** Breeden–Litzenberger: the risk-neutral density is the second derivative of
   call prices with respect to strike, discounted. Integrate it over each Kalshi contract's strike range and
   compare with the contract's price.
4. **Price discovery.** When the index moves, how quickly do Kalshi prices respond, and does the lag depend on
   time to expiry, volume or contract horizon (15-minute, hourly, daily)?
5. **Robustness.** Every trading rule built on the gap is tested out-of-sample, with fees, and checked with the
   deflated Sharpe ratio and probability of backtest overfitting.

Note that options-implied probabilities are risk-neutral, not real-world, so a gap is not automatically a
mispricing. Separating risk premium from genuine disagreement is part of the analysis.

## Data collection

Every 30 minutes on weekdays, a GitHub Actions job (`.github/workflows/snapshot.yml`) takes one matched snapshot and commits it to the `data` branch; `collect/run_snapshot.sh` does the same on the Mac as a backup:

| Source | What | Notes |
|---|---|---|
| Cboe delayed quotes | SPX and NDX options (including PM-settled SPXW and NDXP) expiring within 14 days: bid, ask, IV, Greeks, volume, open interest | About 15 minutes delayed. The header row stores the feed timestamp for alignment. |
| Kalshi public API | Open daily ladders: KXINX, KXINXW, KXNASDAQ100 | Real time. Strike ranges, bid/ask, volume, close time. |
| Polymarket CLOB API | Live order books (top 10 levels, both outcomes) for the daily S&P and Nasdaq-100 up/down markets | Real time. Replaces the assumed spread in layer 6 with real ones. |

Files land in `data/raw/<source>/<date>/` as gzipped JSON lines, timestamped in UTC. `data/` is git-ignored.

### Schedule

A launchd agent runs the snapshot on weekdays every 30 minutes from 6:45am to 1:45pm Pacific. The Mac must be
awake; if it's asleep at a scheduled time, launchd runs the job once when it wakes, and the stored timestamps
show the real collection time.

```
launchctl list | grep implied-odds        # is it loaded?
tail -f data/logs/snapshots.log           # watch runs
launchctl unload ~/Library/LaunchAgents/com.implied-odds.snapshot.plist   # stop
```

## Requirements

Collectors use only the Python standard library. Analysis notebooks will need `numpy`, `pandas`, `scipy`
and `matplotlib` (see `requirements.txt`).

## Microstructure: is Kalshi ladder activity self-exciting? (Hawkes)

Pre-registered in `research/PREREGISTRATION_HAWKES.md` (commit 3532455) before any real-data fit. Model:
`microstructure/hawkes.py`, discrete-time Hawkes with a jointly fitted intraday baseline and a 30-minute half-life cap;
simulation tests in `tests/test_hawkes.py`. Data: 115 pre-holdout days, the last 360 minutes before the close, counts
per minute of contracts with a 1-minute candle ("activity") and with a trade ("trades").

**Pre-registered result: all four verdicts CONFIRMED** (95% day-bootstrap intervals, 1,000 resamples):

| | n (branching ratio) | half-life |
|---|---|---|
| S&P activity | 0.875 (0.799 to 0.964) | 4.5 min (3.6 to 6.1) |
| S&P trades | 0.905 (0.869 to 0.939) | 7.6 min (6.3 to 9.6) |
| Nasdaq activity | 0.976 (0.944 to 0.983) | 5.5 min (4.6 to 6.6) |
| Nasdaq trades | 0.951 (0.853 to 0.999) | 16.8 min (11.4 to 22.8) |

**Why those numbers overstate it (post hoc, addendum committed c96b975 before the bootstrap finished).** The
pre-registered model shares one baseline across days. Days differ in overall level far more than chance allows (daily
totals vary 29 to 72% against 2 to 11% for Poisson), and on simulated data with that kind of variation and *no*
self-excitation the pre-registered fit returns n = 0.999. Refitting with a level per day (500 resamples):

| | n with day effects | half-life |
|---|---|---|
| S&P activity | 0.676 (0.531 to 0.768) | 3.1 min (2.0 to 3.9) |
| S&P trades | 0.463 (0.405 to 0.505) | 2.8 min (2.1 to 3.6) |
| Nasdaq activity | 0.827 (0.739 to 0.955) | 4.3 min (3.6 to 6.2) |
| Nasdaq trades | 0.273 (0.205 to 0.333) | 1.6 min (1.0 to 2.2) |

Self-excitation survives everywhere, but the trade numbers halve or more, and the bursts are short (2 to 4 minutes).
S&P trades excite more than Nasdaq trades (+0.19, +0.11 to +0.27); for quote activity it is the other way round.

**Reading it honestly.** Quote activity is the weaker evidence: one index tick re-prices many contracts, and index
volatility clusters on its own, so a high n for activity is largely the index, not Kalshi traders. Trades are closer
to "trading begets trading", and even there a common driver can't be ruled out. Fit quality is uneven: residual
dispersion is 1.3 to 1.4 for trades (close to Poisson) but far above 1 for activity, and the S&P activity estimate
moves from 0.42 (Oct to Dec) to 0.94 (Jan to Mar) under the pre-registered model. Pre-registered prediction: activity
n well above 0.10 with half-life under 10 minutes held, except Nasdaq trades (16.8 min, pre-registered model);
"trades less self-exciting than activity" failed on S&P under the pre-registered model and held with day effects.
Any later use of n is pre-registered with the day-effects model.

## Layer 5, options-implied fair value vs Kalshi: pre-registered, collecting

Pre-registered in `research/PREREGISTRATION_LAYER5.md` (commit 54aafdd) before any live statistic: agreement,
accuracy (Brier) and a fee-inclusive trading rule, per index, on the live forward sample 2026-10-05 to 2026-11-27.
`research/options_vs_kalshi.py` runs in `SMOKE=1` mode (data quality only) until then and refuses the full run
before 2026-11-30. First smoke run, 5 days in: 37 snapshots per index, 36 with a valid options fit, about 170
quoted contract-snapshots per index. At that rate the window should give roughly 1,300 per index.

## Layer 7, how fast Kalshi prices an index move: pre-registered, collecting

Pre-registered in `research/PREREGISTRATION_LAYER7.md` (commit d138dab) before any live statistic. For each minute
from 6 hours to 10 minutes before the close, Kalshi's implied median close (from the bids-only range ladder) is
regressed on the index's minute changes at lags -5 to +10. Verdicts per index: speed (minutes to 90% of the
response), completeness (total response vs 1) and whether Kalshi leads, with day-bootstrap intervals, on the same
forward window as layer 5 (2026-10-05 to 2026-11-27). A slow ladder would be the most direct edge a small trader could
have; the prediction written down in advance is that the S&P ladder is fast and the Nasdaq one slower.

`collect/intraday.py` now also saves ^GSPC and ^NDX minutes. `research/kalshi_reaction.py` runs in `SMOKE=1` mode
until 2026-11-30; the Kalshi minute candles are downloaded after the window. First smoke run: 1,756 S&P index minutes
on 5 days; ^NDX starts with the next collection run.

## Paper trading the layer 5 rule

`trade/paper.py` runs layer 5's trading rule live: after every collection run it fits the options, checks each
same-day Kalshi range against the rule (3 cents past the touch, at least 100 contracts shown, one trade per contract
per day, Kalshi's fee per 100-lot) and writes its decisions to `data/raw/paper/` on the data branch. Git timestamps
every decision when it is made, so the log cannot use later information, and each trade records the money it ties up
until settlement. It imports layer 5's constants and helpers, and `replay --check` confirms it fires exactly the
trades layer 5's backtest does (41 of 41 on the first five days). Profit is sealed like layer 5: `report` refuses to
run before 2026-11-30.

Replay of the first five days (decisions only): 18 S&P and 23 Nasdaq trades. Capital tied up per day was a median of
about $200 per index, because most trades are in cheap tail ranges.
