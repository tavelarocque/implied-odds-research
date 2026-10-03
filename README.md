# Implied Odds

Do prediction markets and options markets agree on the odds of the same event? This project compares
Kalshi's S&P 500 and Nasdaq-100 contracts against probabilities implied by SPX option prices, and studies
where, when and why they disagree.

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
