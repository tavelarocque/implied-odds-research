# Pre-registered: layer 14b, a daily Grok news scout scored on fixed Bitcoin questions

DRAFT 2026-10-13. Not registered until committed; must be committed before the first scout call. Layer 14 (the
committee on 13b trades) is unchanged.

## Why

Layer 14 only fires when 13b trades (at most once a day, none so far), so its sample grows slowly. Extra bots would
add correlated opinions, not independent data: the sample is days x questions. Following ForecastBench (Karger et al.
2024) and Halawi et al. (2024), one scout answers the same pre-written questions every day, scored against baselines.

## The scout, fixed now

- **When:** once a day, at the crypto run nearest 18:00 UTC (11:00 PT), whether or not 13b trades.
- **Model and tools:** xAI Grok as in layer 14 (`grok-4.7`, Responses API, `x_search` and `web_search`). Model id,
  prompt hash and every retrieved URL with its publish time are logged; a retrieved item published after the call is
  flagged and the day is excluded.
- **Questions (probabilities 0-1), horizon = the next 24 hours from the call:**
  - Q1: next-24h realized volatility (hourly Coinbase returns) above the median of the previous 30 days' daily values.
  - Q2: |24h log return| greater than 2 standard deviations of the previous 30 days' daily returns.
  - Q3: today's 5pm ET Kalshi KXBTCD contract with the strike nearest spot at the call settles YES.
  It also lists scheduled events in the window (logged, not scored).
- **Drift probe:** every Monday, the same fixed prompt with no search, logged, to detect silent model changes.

## Baselines, fixed now

Q1, Q2: climatology (the event's frequency over the trailing 90 days) and, for Q1, a logistic regression of the event
on log yesterday's realized volatility, fitted on the trailing 90 days each day. Q3: Kalshi's mid at the call.

## Verdict, on or after 2027-05-01

Days 2026-10-20 to 2027-04-30. Primary: Q1 Brier of the scout minus the logistic baseline, 95% interval from 2,000
resamples of 5-day blocks. **Scout adds value** if the whole interval is below 0 with at least 120 scored days;
**worse** if entirely above 0; otherwise **no difference shown**. Reported: Q2 and Q3 the same way; calibration;
Q1-Q2 on days with a scheduled CPI or FOMC release vs not; failure rate; cost.

## Prediction

No difference on Q1 and Q3. A small gain on Q2 on CPI/FOMC days only. Ledger: L14b (Q1 primary); Q2, Q3 reported.

## Cost

One search-enabled call a day plus one probe a week; xAI's $5 prepaid balance with auto top-up off caps the spend.

2026-10-16, bug fix (transport only): on 2026-10-15 the scout's reply was cut off in transit (IncompleteRead) and the day was lost. A reply cut off or reset in transit is now retried once, 5 s later. The cut-off reply is never read, so no answer is chosen over another; the one-call-per-day cap is otherwise unchanged.
