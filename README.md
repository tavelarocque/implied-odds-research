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

**Layer 7b, the hourly contracts.** Kalshi also lists hourly S&P and Nasdaq "at or above K at the hour" contracts
(KXINXU, KXNASDAQ100U). In their last hour they are close to a bet on the next few minutes of the index, so they are
where a slow quote would matter most. `research/PREREGISTRATION_LAYER7B.md` applies layer 7's method and decision rules
to every hourly event, 60 to 5 minutes before its close, on the same window; run with `--hourly`. Only strikes within
1% of each event's settled value are downloaded (`kalshi_history.py candles ... --near 1`), about 30 (S&P) to 60 (Nasdaq) files per event.
Data quality on one day (2026-10-08): all 14 events usable, the implied median defined in 51 to 56 of 56 minutes and
changing in about 95% of them. Prediction: the hourly contracts are faster than the daily ladder.

## Layer 5 on Bitcoin: pre-registered, collecting

The same three questions as layer 5, on Kalshi's hourly Bitcoin contracts (KXBTCD) against Deribit's BTC options.
Bitcoin trades all week, so the sample grows faster. `research/PREREGISTRATION_BTC.md` fixes the method before the
first counted snapshot (2026-10-10); `.github/workflows/crypto.yml` collects hourly at :07 (kept under the free Actions
minutes), all days, into `data/raw/deribit_btc/` and `data/raw/kalshi_crypto/` (kept apart from the stock snapshots, whose spacing
rule counts files).

The hard part is time. Deribit's options expire at 08:00 UTC and Kalshi's settle on the hour, so `implied/crypto.py`
fits Deribit's mark-volatility smile for the next expiry and moves it back to Kalshi's settlement, keeping its shape
in standard deviations and letting variance accrue evenly in calendar time. That assumption is the weakest link, and
the options probability's own calibration is reported as its check. `research/btc_options_vs_kalshi.py` reuses layer
5's quote filter, fee, trade rule and bootstrap; `SMOKE=1` reports data quality until 2026-11-30.

## Layer 9, exploratory: does public attention widen Kalshi's long-shot overpricing? No sign of it

Hypothesis (2026-10-09): retail money chases what is in the news and buys cheap long shots, so Kalshi's long-shot
overpricing should be larger after high-attention days. `collect/attention_history.py` pulls daily Wikipedia pageviews
(S&P 500, Nasdaq-100, Stock market crash, Recession, Stock market) from April 2022; `research/explore_attention.py`
compares overpricing (mid minus the 0/1 outcome) after the top fifth of abnormal-attention days with all other days,
on the development sample only (calibration quotes before the holdout; 15,099 S&P and 17,402 Nasdaq quotes). Attention
is the previous UTC day's views, because a UTC day runs past the close.

Result: 48 comparisons (2 indices x 4 measures x 3 horizons x long shots or all quotes); 2 intervals exclude 0, about
what chance gives, and their signs disagree across measures and horizons. On the S&P, long shots one hour out were if
anything less overpriced after high attention (-2.2 cents, -4.7 to +0.1). The closest to the hypothesis: Nasdaq
long shots one hour out after high Nasdaq-100 page views, +1.6 cents (-0.2 to +3.2), one cherry-pick among 48.

Verdict: not pursued. A forward test of the best of 48 would be a test of a selected fluke, and the 8-week window
would hold about 70 such quotes, too few to see a 1.6-cent effect. Daily Wikipedia views are one channel; intraday
news volume (GDELT) is untested, and is worth revisiting only if layer 5's forward test finds a gap to explain.

## Layer 10, exploratory: Kalshi's CPI markets vs the Cleveland Fed's inflation nowcast. Kalshi wins

Question (2026-10-09): Kalshi lists monthly "CPI above k%" contracts (KXCPI headline, KXCPICORE core). The Cleveland
Fed publishes a daily inflation nowcast that has historically beaten economists' consensus. When the two disagree, is
the nowcast right? `research/explore_cpi.py` compares them at 10:30 ET the day before each release (half an hour after
the nowcast updates), on releases before the holdout. The nowcast becomes a probability per contract through a normal
error whose spread is its own day-before error over 2013 to mid-2021, before Kalshi listed CPI markets (0.14 points
headline, 0.17 core). Data: the nowcast's chart file (daily paths since 2013) and Kalshi's hourly candles.

Result, 37 headline and 36 core releases (2023 to March 2026), 252 quoted contracts:

| | Brier, Kalshi mid | Brier, nowcast | Kalshi minus nowcast (95%, resampling releases) |
|---|---|---|---|
| Headline CPI | 0.109 | 0.156 | -0.048 (-0.084 to -0.013) |
| Core CPI | 0.113 | 0.150 | -0.037 (-0.068 to -0.003) |

Kalshi is significantly more accurate. When they disagree by more than 15 points, the nowcast is the closer one only
27 to 29% of the time. Trading toward the nowcast loses nothing on average but wins nothing either: means of -0.3 to
+3.3 cents per contract with intervals of about +/-8 cents, won 25 to 32% of the time. Reading: the market already
prices the nowcast plus whatever else traders know (the Fed's own paper found Kalshi beats the Bloomberg consensus on
headline CPI). Verdict: no edge from the public nowcast; not pursued. One caveat in the method: a single fixed error
spread for the nowcast is cruder than Kalshi's own distribution, which hurts its Brier score; a better-calibrated
nowcast distribution could narrow the gap, but not reverse which side the big disagreements resolve toward.

## Exploratory: public attention vs S&P volatility. Mostly the VIX's horizon

`research/explore_attention_vol.py` and `explore_attention_vol_robust.py` (2015-08 to 2026-03, 2,676 sessions): after
days when the "Stock market crash" Wikipedia page spikes (top fifth), the next session's realized variance beat the
30-day VIX's implied variance by 37% (8% to 75%, block bootstrap), and the next 5 sessions' by 19%. Against Cboe's
9-day VIX the 5-day effect vanishes (+5%) and the next-day effect falls to +20% (-5% to +51%), +24% (-1% to +58%) with
controls for recent moves. Reading: after a scare, short-dated options already price the jump the 30-day VIX averages
away. A weak next-day hint at most, and not tradable without same-day S&P options. Not pursued.

## Exploratory: predicting tomorrow's efficiency ratio. Real but tiny, and what helps is the trend

`research/explore_efficiency.py`: a day's efficiency ratio is |close - open| / (high - low), near 1 when the market
moved one way and held it, near 0 when it chopped. SPY daily bars 1993 to 2026-03 (Yahoo's ^GSPC opens before 2006 are
just the previous close, so they cannot be used). A logistic regression on 15 features known at the close (realized
volatility, efficiency today, its lags and 5/10/20-day means, variance ratio, false breakouts, distance from the 50-day
average, chop streak and share, volatility change, range vs its 20-day mean) predicts whether tomorrow is a clean day
(above the median). Walk-forward: train on all earlier years, test on the next, 1997 to 2026-03, 7,356 test days.

**Predicting efficiency.** Out-of-sample AUC 0.522 (0.50 is a coin flip). It beats today's efficiency alone (0.481,
difference +0.041, +0.020 to +0.063 by 20-day block bootstrap) and the 20-day mean (0.500; +0.022, +0.003 to +0.040).
Real, and too small to act on by itself.

**Does it beat the options?** On the days the model calls choppiest (its bottom fifth, cut-off from the training
years), the next close-to-close move was 8% smaller relative to the VIX's one-day move than on other days (-13% to -2%),
and 14% smaller relative to the 9-day VIX (-21% to -7%, 2011 on). That survives controlling for recent realized vs
implied volatility and the VIX level. It does not survive adding one feature on its own: distance from the 50-day
average. With that in the regression, the model's prediction adds nothing (VIX: +0.08, -0.51 to +0.66; VIX9D: +0.18,
-0.97 to +1.29). Above-average markets move less than the VIX implies, a known pattern (the variance premium is
larger in calm uptrends). The efficiency model's "choppy day" signal was mostly that.

## Layer 11, exploratory: Kalshi's Bitcoin long shots and crypto crowd mood. A candidate

`research/explore_btc_sentiment.py`, development sample only: Kalshi's 5pm ET Bitcoin sets (KXBTCD) from 2024-03-20 to
2026-03-31, 664 days, hourly candles for strikes within 4% of the settlement (`collect/kalshi_btc_daily.py`); Crypto
Fear & Greed, Binance funding and Wikipedia attention (`collect/crypto_sentiment.py`). A long shot is a side priced at
10 cents or less: YES on a high strike (upside) or NO on a low strike (downside).

**Base effect.** Long shots are overpriced on both sides: priced at 4 to 5 cents, they paid 1.5 to 2.3% of the time
1 to 3 hours out, about 2.7 cents too expensive (1.5 to 3.7). Selling them at the touch after fees: +0.5 to +0.8 cents,
intervals including 0. On average, not tradable.

**Mood, ten comparisons fixed before running.** Three pass, all the same story: when the crowd is bearish, downside long
shots are more overpriced. Fear (index at 25 or below): +2.3 cents more at 1h (+1.0 to +4.0) and at 3h (+0.8 to
+4.1). Funding in its bottom fifth: +1.8 cents at 1h (+0.4 to +3.4); +1.2 at 3h (-0.6 to +2.9). Greed, crowded longs and
attention: nothing. The two measures correlate (0.55 by day), so this is closer to one finding confirmed twice than
three. Selling the downside long shot on fear-or-short-funding days: 325 trades on 157 days at 1h, +2.35 cents per
contract, none of the 325 paid out; 441 trades at 3h, +1.87 cents (+0.82 to +2.64), 0.9% paid out. Other days: about 0.

**Why it is only a candidate.** The 1h interval is not meaningful: with no losses, the bootstrap has nothing to vary
(the same trap as the S&P long-shot holdout). The right yardstick is the loss rate: break-even is about 2.4%, and 0 in
325 trades bounds it below about 0.9%, but the trades cluster by day (0 losses on 157 days bounds the daily rate below
about 1.9%). Fear days also cluster in time (most fall in Nov 2025 to Mar 2026). It is one candidate out of ten, found
on the development sample. Next step: pre-register it with a loss-rate bar and test it out of sample.

## Exploratory: hidden Markov regimes. Nothing for the S&P; one Bitcoin candidate (layer 11b)

`research/explore_regimes.py`: a Gaussian hidden Markov model on each day's (return, log range), two or three states
labelled calmest first, refitted every year on earlier years only, and only filtered probabilities (the smoothed ones
most tutorials plot use the future). **S&P (SPY, 1997 to 2026-03):** on days the model calls turbulent, the next move
was larger relative to the VIX (0.69x vs 0.55x implied), but the effect shrinks once realized vs implied volatility is
controlled for and vanishes with the 50-day trend added (+0.08, -0.06 to +0.18; VIX9D +0.03, -0.14 to +0.19). The same
end as the efficiency model: nothing beyond the VIX and the trend. **Bitcoin long shots (layer 11's development
sample):** 3 hours out, downside long shots were more overpriced on turbulent days (+4.1 vs +1.6 cents; difference
+2.5, +0.8 to +4.7), including days without a fear-or-funding signal (selling them +2.0 vs -1.6 cents, 0.8% vs 4.3% paid
out). One hour out, nothing. One pick from several comparisons, pre-registered as layer 11b
(`research/PREREGISTRATION_LAYER11B.md`) before the layer 11 holdout was analysed, and tested on it with
`research/test_layer11b.py`.

## Robustness of layers 11 and 11b on the development sample: a plateau, but the mood timing is only borderline

`research/robust_layer11.py`, development data only, nothing pre-registered changed. **Grid** (3 hours out): all 64
combinations of Fear & Greed cut-off (10 to 50) and funding cut-off (off to bottom 40%) make money, +0.8 to +3.0 cents;
the pre-registered cell (+1.9 cents, 183 days) sits in the middle of a plateau (its 8 neighbours +1.5 to +2.3).
**Probability of backtest overfitting** (CSCV, 8 blocks, 70 splits): 17%. **Walk-forward:** re-picking the best cell
each half-year earned the same out of sample as the fixed rule (+1.85 cents per contract both); the fixed rule made
money in 4 of 5 half-years (2024H2: -1.3 cents). **But** a Monte Carlo that circularly shifts the signal days through
the calendar (keeping their number and clustering) gives the pre-registered cell p = 0.07, and the family-wise check
p = 0.53: selling these long shots made +0.56 cents on all days, and the signal days fall in a stretch when most days
paid. So the parameters are not fragile, but the evidence that mood rather than the period drives it is weak.
**Horizon:** 1 and 3 hours out are positive at every cut-off; 6 hours out loses at almost every cut-off, for both
layer 11 and 11b. Layer 11b's regime cut-off (0.3 to 0.7) is +1.7 to +2.3 cents at 3 hours, all with p < 0.05.

## Paper trading the layer 5 rule

`trade/paper.py` runs layer 5's trading rule live: after every collection run it fits the options, checks each
same-day Kalshi range against the rule (3 cents past the touch, at least 100 contracts shown, one trade per contract
per day, Kalshi's fee per 100-lot) and writes its decisions to `data/raw/paper/` on the data branch. Git timestamps
every decision when it is made, so the log cannot use later information, and each trade records the money it ties up
until settlement. It imports layer 5's constants and helpers, and `replay --check` confirms it fires exactly the
trades layer 5's backtest does (41 of 41 on the first five days). Each run also records Kalshi's result for every
unsettled trade (`data/raw/paper_results/`), and `digest` lists the latest trades and whether each won. Outcomes are
watched trade by trade from 2026-10-09; the rule stays frozen, and the pooled verdict (`report`, layer 5 rule 3) still
waits for 2026-11-30. `live --btc` runs the same rule on Bitcoin (`research/PREREGISTRATION_BTC.md`) after every crypto
snapshot, logging to `data/raw/paper_btc/`; `digest` shows both. The same step also runs layer 11's rule
(`research/PREREGISTRATION_LAYER11.md`, test B): at the one crypto snapshot 2.5 to 3.5 hours before the 5pm ET set
settles, it reads Fear & Greed and Binance funding and, on a signal day, buys YES at the ask on every contract with a
mid of 90 cents or more, logging to `data/raw/paper_l11/` (every evaluation, signal or not, with the mood readings).
The live log is a mirror for watching; test B itself is computed on or after 2027-02-01 from the histories.

Replay of the first five days (decisions only): 18 S&P and 23 Nasdaq trades. Capital tied up per day was a median of
about $200 per index: a 100-lot at these prices risks about $20 or less.
