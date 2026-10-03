# Implied Odds

Do prediction markets and options markets agree on the odds of the same event? This project compares
Kalshi's S&P 500 and Nasdaq-100 contracts against probabilities implied by SPX option prices, and studies
where, when and why they disagree. Every claimed edge goes through one shared robustness layer.

## Layers

| Layer | Folder | Question |
|---|---|---|
| Robustness | `robustness/` | Is a backtest result real, or the luckiest of many tries? Deflated Sharpe ratio, probability of backtest overfitting (CSCV), minimum track record length. Tested in `tests/`. |
| Strategy discovery | `research/strategy_discovery.py` | Search 2,120 rule-based strategies on SPY and nine sector ETFs: how much of the best backtest survives out of sample? |
| Implied Odds | `research/calibration.py` and later phases | Are Kalshi's S&P contracts calibrated, and do they agree with option-implied probabilities? |

## Code map

```
implied-odds/
├── robustness/          Layer 2: is a result real or luck?
│   └── overfitting.py     deflated Sharpe, probabilistic Sharpe, PBO via CSCV, minimum track record
├── strategies/          Layer 3's library
│   ├── rules.py           momentum, moving-average cross, mean reversion, breakout
│   └── backtest.py        signals -> positions (shifted a day) -> returns after costs
├── implied/             Layer 5: option-implied probabilities
│   └── bl.py              forward from put-call parity, SVI smile fit, Breeden-Litzenberger probabilities
├── collect/             Layer 1: data
│   ├── options_snapshot.py, kalshi_snapshot.py, run_snapshot.sh   live snapshots every 30 min
│   ├── kalshi_history.py, polymarket_history.py, etf_prices.py    history pullers
│   ├── intraday.py        daily one-minute S&P prices for layer 7
│   ├── validate_kalshi.py data checks
│   └── status.sh          download progress
├── research/            one script per study; each writes to research/output/
│   ├── config.py          the locked holdout
│   ├── strategy_discovery.py, calibration.py, fair_value_snapshot.py
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
  (1,126 of 1,126 within 5 cents).
- **Tested tools.** `python3 run_tests.py` runs three tests: the robustness layer rejects pure noise and finds a
  planted edge; Breeden-Litzenberger recovers known probabilities from noisy quotes (within 0.01 pp on a flat
  smile, 0.63 pp on a skewed one); and no strategy rule can see future prices (864 perturbation checks).

### Result so far: strategy discovery

Searching harder makes the in-sample winner look better and perform worse. Picking the best of 1,000 rules
by 2000–2012 Sharpe gives an average in-sample Sharpe of 1.02 and an out-of-sample (2013–2026) Sharpe of 0.05,
against 0.92 for simply holding SPY. The single best rule (a consumer-staples mean-reversion rule, in-sample 1.06)
lost money out of sample; its deflated Sharpe of 0.70 had already flagged it as not significant.

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

`collect/run_snapshot.sh` takes one matched snapshot:

| Source | What | Notes |
|---|---|---|
| Cboe delayed quotes | SPX options expiring within 14 days: bid, ask, IV, Greeks, volume, open interest | About 15 minutes delayed. The header row stores the feed timestamp for alignment. |
| Kalshi public API | Open markets in KXINX, KXINXU, KXINXW, KXNASDAQ100, KXNASDAQ100U | Real time. Strike ranges, bid/ask, volume, close time. |

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
