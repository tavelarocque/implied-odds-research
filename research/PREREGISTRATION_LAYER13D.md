# Pre-registered: layer 13d, a shadow layer 13 with hour-of-week volatility

DRAFT 2026-10-13. Not registered until committed; must be committed before the first logged forecast. Layer 13 and
13b are unchanged and keep trading; 13d only logs a second probability beside them.

## Why

Layer 13's lognormal uses the standard deviation of the last 24 hourly Coinbase returns, so every hour weighs the same.
Bitcoin volatility has strong hour-of-day and weekday patterns (Hansen, Kim & Kimbrough 2021; Dumitru, Hizmeri &
Izzeldin, HARP). A 1-3 hour contract spanning the US open is not an average hour.

## The shadow forecast, fixed now

- **Seasonal factors:** 48 buckets (hour of day UTC x weekday/weekend). s(h) = mean squared hourly Coinbase log return
  in bucket h over the trailing 90 days, divided by the mean over all hours in those 90 days. Recomputed each run from
  data before the forecast only.
- **Base variance:** mean of r_t^2 / s(h_t) over the last 24 completed hours.
- **Forecast variance to settlement:** base variance x the sum of s(h) over the hours to settlement (the current
  partial hour weighted by its remaining fraction).
- **Probability:** layer 13's lognormal and frozen blend, logit P = 0.846 logit(mid) + 0.432 logit(P_lognormal), with
  only the variance replaced.
- **Logged:** at every hourly crypto run, for every KXBTCD contract within 6% of spot settling 0.5 to 3.5 hours later:
  the layer 13 probability, the 13d probability, Kalshi's mid. Logging only; no trade.

## Verdict, on or after 2027-02-01

Contracts settling 2026-10-15 to 2027-01-31. Primary: mean log-loss of 13d minus layer 13 on the same contracts, 95%
interval from 2,000 resamples of whole UTC days. **13d better** if the whole interval is below 0 with at least 60 days;
**worse** if entirely above 0; otherwise **no difference shown**. Reported: Brier, split by 1 h vs 3 h, US hours vs not.

## Prediction

13d better, by a small amount, mostly on contracts spanning 13:30-16:00 UTC; no difference overnight. Ledger: L13d.
