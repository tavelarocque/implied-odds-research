# Pre-registered: layer 13c, a meta-labeling filter on layer 13b's trades

Written 2026-10-10, before the filter has been fitted and before any layer 13b trade after 2026-10-10 is used for
anything. The git commit that adds this file, and `research/fit_layer13c.py` with it, is the timestamp; the fitted
coefficients are committed separately afterwards (`research/layer13c_model.json`) and nothing below changes then.

## Idea

Meta-labeling (López de Prado, *Advances in Financial Machine Learning*, ch. 3): a simple rule proposes trades, and a
second model, trained on the outcomes of that rule's past trades, predicts which of them will win; only those are
taken. Here the proposing rule is layer 13b (`research/PREREGISTRATION_LAYER13B.md`). It buys mostly expensive
favourites, so it wins small and sometimes loses big; the filter's job is to recognise the setups that produce the
losses.

## The filter, fixed before fitting

- **Training trades:** layer 13's trading description on the development window only, 5pm KXBTCD sets settling
  2025-09-01 to 2026-03-31, 3 hours out, from `research/test_layer13_lognormal.py`'s quotes (hourly candle quotes):
  every contract where blend - ask - fee > 3 cents (buy YES) or bid - blend - fee > 3 cents (sell YES). Label = 1 if
  the trade made money after the fee. The holdout (2026-04-01 to 2026-09-30) is not used.
- **Four features, all known at the decision:**
  1. distance to the strike in volatility units, |ln(S / K)| / (sigma x sqrt(tau)), with S, sigma and tau as in the
     layer 13 lognormal;
  2. the quoted spread, ask - bid;
  3. Bitcoin's efficiency ratio over the 24 hourly candles before the quote, |last close - first open| /
     (highest high - lowest low);
  4. Deribit's DVOL (30-day Bitcoin implied volatility) at the last completed hour.
- **Model:** logistic regression on the four features standardized with the training trades' means and standard
  deviations, fitted by maximum likelihood, no regularization, no interactions. Chosen over the random forest of the
  usual meta-labeling examples because about 400 training trades is too few for trees to be stable, and because the
  cloud runner that makes live decisions has numpy but not scikit-learn.
- **Rule:** take a 13b trade if the model's probability of a win is above 0.5. No other threshold is tried.
- **Live:** the probability is computed and logged on every layer 13b trade (`p_meta` in `data/raw/paper_l13/`) with
  the frozen coefficients; 13b itself still takes every trade, so the comparison is within the same trades.

## The verdict

Layer 13b trades on sets settling 2026-10-11 to 2027-01-31, analysed once on or after 2027-02-01, alongside 13b.

- **Primary:** mean profit per contract of the trades the filter takes minus that of the trades it rejects, 95%
  interval from 2,000 resamples of whole settlement days. **The filter adds value** if the whole interval is above 0
  and each group has at least 20 trades; **it subtracts value** if the whole interval is below 0; **no difference
  shown** otherwise.
- Reported alongside: the taken trades on their own against layer 13b's edge bar (lower end of the profit interval
  above 0); the share of trades taken; the in-sample and leave-one-month-out fit on the development trades.

## Prediction, written so it can be wrong

No difference shown. Four features and a few hundred trades rarely produce a stable filter, and most of 13b's profit
comes from the calibration correction itself, which the filter cannot add to.

Nothing above changes after the coefficients are fitted or after any forward trade is seen.

## Amendment 1, 2026-10-10 (after fitting on the development trades; before any forward trade exists)

The first fit showed the 0.5 threshold is a design error: the development trades win 91.5% of the time, so the model's
probability of a win is above 0.5 for every trade and the filter would take 100% of them, in sample and leave one
month out. The rule becomes the one the trade's own economics imply: **take a 13b trade if the model's probability of
a win is above the price paid plus the fee** (the ask plus fee for a bought YES, one minus the bid plus fee for a sold
YES), i.e. if the filter's expected profit per contract is positive. Coefficients, features and the verdict are
unchanged. This is the only change; whatever the development check below shows with it, nothing else is tried.
Development fit (in sample, logistic, standardized): intercept +2.902, distance +1.290, spread -0.102, efficiency
ratio -0.416, DVOL +0.012; 400 trades on 136 days, 91.5% winners, +5.63 cents each.
