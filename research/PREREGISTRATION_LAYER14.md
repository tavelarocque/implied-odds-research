# Pre-registered: layer 14, an LLM review committee on layer 13b's live trades

Written 2026-10-11, before the committee has made a single call. The git commit that adds this file, together with
`trade/committee.py` (roles, prompts, model name, timeouts) and its call from `live_l13` in `trade/paper.py`, is the
timestamp. The committee starts making decisions on the first layer 13b run after `XAI_API_KEY` is added to the cloud
runner; nothing below changes after that.

## Idea

Multi-agent LLM trading setups (e.g. TradingAgents, Xiao et al. 2024) give language models roles such as analyst,
news reader, skeptic and risk manager and let them debate a trade. Their published backtests are not trustworthy,
because the models have read the news from the period being backtested (look-ahead bias; Glasserman and Lin 2023).
This layer tests the idea the only clean way: forward only, on top of a rule that already has a tested edge, as a
filter. The question is whether a committee of LLMs with live access to X and the web can tell which of layer 13b's
trades to skip.

## The committee, fixed before any call

- **Model:** xAI Grok, requested as `grok-4.7` through the Responses API. The model id the API reports back is logged
  on every call; if it changes during the test, results are reported for each id as well as pooled.
- **Roles (one call each):** a news scout, once per run, with xAI's `x_search` and `web_search` tools, asked for
  scheduled events and breaking news that could move Bitcoin before settlement; then per trade an analyst and a
  skeptic (in parallel, both given the trade's numbers and the scout's brief), then a risk manager who reads both and
  outputs JSON: take or skip, its own win probability, one reason.
- **Principles given to every role:** the description of layer 13b, its holdout result, where its edge comes from,
  and the committee's rule: default TAKE; SKIP only for a concrete reason the rule cannot see (a scheduled event
  likely to move Bitcoin by more than the distance to the strike, an exchange or index problem, breaking news already
  moving the price, a book too thin to fill). The exact text is in `trade/committee.py`; its prompt hash is logged on
  every run.
- **Logged only.** Layer 13b still takes every trade. Each 13b trade row gets `committee_take`, `p_committee` and
  `committee_status`; full transcripts go to `data/raw/paper_l14/`. A trade whose committee call fails or times out
  (200 seconds for the whole committee) has no decision and is left out of the primary comparison; the failure rate is
  reported.

## The verdict

Layer 13b trades on sets settling from the committee's first decision to 2027-04-30, analysed once on or after
2027-05-01.

- **Primary:** mean profit per contract (after fees) of the trades the committee takes minus that of the trades it
  skips, 95% interval from 2,000 resamples of whole settlement days. **The committee adds value** if the whole
  interval is above 0 and each group has at least 20 trades; **it subtracts value** if the whole interval is below 0
  (same minimum); **no difference shown** otherwise, including when it skips fewer than 20 trades.
- **Reported alongside:** total profit of raw 13b vs committee-filtered 13b vs 13c-filtered 13b on the same trades;
  skip rate; agreement with layer 13c's filter; Brier score of the committee's own win probability against the
  13b blend's; the failure rate; what the skipped trades had in common (the reasons, read once).

## Prediction, written so it can be wrong

No difference shown, most likely because the committee rarely skips. Layer 13b's edge is a calibration correction,
which reading the news does not improve, and the trades are 3 hours from settlement, when most news is already in
the price.

## Limits

API models change without notice and the same prompt does not always give the same answer, so this tests "Grok as it
was served during the window", not a fixed model. The committee and 13c both filter the same trades, so they are
compared, not counted as independent evidence. Its primary result enters the multiple-testing ledger as claim L14a when it is analysed.
