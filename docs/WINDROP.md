# windrop: predicting which horses' WIN price will shorten (落飛) before the close

Read this first if you work on `windrop.py`, the `windrop*` fields of a race record, or `research/windrop/`.
Everything here was built and verified in one session on 2026-11-18/19 from two race days (16 races); the numbers are
exploratory, see "Limits". Terms: 落飛 = the WIN price ends **shorter** than it is now; 孖寶 = Double (DBL); 連贏 = Quinella (QIN);
蝕水 = a Double combination priced below the product of the two WIN prices.

## What is predicted

For each horse at a prediction point (`first`, `t5`, `t3`, `t2` before the off): will its WIN price at the close (`after_start`,
the first closed board after stop-sell) be shorter than now? Target used everywhere: **shortened by 10% or more**
(`shorten_prob_10pct`), also "shortened at all" (`shorten_prob_any`). It is not "who wins" and says nothing about value or profit.

The user's decision rule (adopted): **flag a horse when its predicted close price is at least 5% below its price now**
(`predicted_close_odds <= win_odds x 0.95`, `predicted_drop_pct >= 5`). No top-N: a race may have 0 or 5 flagged horses.

## Three predictions + one flag, all in `windrop.py`

| prediction | points | score | notes |
|---|---|---|---|
| Quinella `windrop_v1` | t5, t3, t2 (every race) | linear: favourite-ness `fav` = ln WIN-implied probability, `winmom` = WIN shortening t5 -> point (not at t5), `lead` = Quinella support / WIN-implied - 1 | coefficients in `COEFS` |
| Double `windrop_dbl_v1` | first, t5, t2 (race 2+) | z(`edge`) only | `edge` below |
| Combined `windrop_dbl_v1_combined` | t5, t2 (race 2+) | z(`edge`) + z(`lead`), equal weights | best calibrated |
| Longshot `windrop_longshot_v1` | t2 | a flag, no price/chance | horses at 20x+; see below |

Quinella support of a horse = sum of `1/(odds-1)` over its combinations / (2 x sum over all combinations) (`qin_shares`).
Features are z-scored inside the race. Chance = logistic in the score; price = `win odds now x exp(-(c0 + c1 x score))` with the
25-75% band of the fit residuals (`price_block`, parameters in `PROB`).

**Double `edge`.** The Double of legs (N-1, N) freezes when race N-1 stops selling. Its price for (a, b) should be about
W1(a) x W2(b) (W1 = race N-1 WIN price **after the close**, `after_start`). `DBL(a,b) / W1(a)` is the race-N price the Double bettors had
in mind; average it over leg-1 horses a at **10x or less**, weighted 1/W1(a) (`dbl_edges`). `edge(b) = ln(W2(b) / implied)`. W2 is
taken at `first` = race N's first WIN board after race N-1 stopped selling (`before_rollover`), about 30 minutes before race N, for all
three points. High edge = WIN is longer than the Double implies = expected to shorten. Frozen Double = `last_open` board, else its t2 board
(`dbl_frozen`). Capped Double prices (999) are common for long shots; restricting to leg-1 horses at 10x or less avoids most of them.

**Longshot flag.** The score models lean on favourite-ness, so a 20x+ horse is never ranked high (0 of 74 in 16 races). The Quinella trend
itself does see them: flag a 20x+ horse if it is in the race top 3 by mean Quinella-combination drop t5 -> t2 (all horses ranked together).
13 flagged -> 4 shortened 10%+; 61 not flagged -> 0. Only 4 longshots fell: low confidence, so it is a separate flag.

## Quinella 飛 filter (qin share vs WIN share)

The user's rule: at a given moment, a horse whose share of the Quinella pool (`qin_pct`, as in `qin_shares`) is **larger** than its WIN-implied
share (`win_pct`, normalised over the same horses) has "Quinella 飛" (this is the sign of `lead`). Three states, per point (t5, t3, t2):

| state | gap = qin_pct - win_pct | meaning |
|---|---|---|
| `fly` 有飛 | > 0 | Quinella keener on the horse than WIN |
| `tie` 打和 | -1.0 to 0 percentage points | nearly equal: **never excluded** (user's decision) |
| `no_fly` 冇飛 | below -1.0 | Quinella clearly less keen: the exclusion list `qin_no_fly` |

Fields on every Quinella, Double and combined row (t5, t3 for Quinella, t5 and t2 for Double/combined): `qin_gap_pp`, `qin_fly_state`,
`qin_fly_points` (state at t5, t3, t2 so far), `qin_fly_all_points`; on the prediction: `qin_fly`, `qin_tie`, `qin_no_fly`, `qin_fly_validation`.
No parameter is fitted, so the numbers are plain counts (16 races, 204 runners; 46 / 42 / 42 shortened 10%+ at t5 / t3 / t2):

| point | fly | tie | no_fly | fallers kept by excluding no_fly |
|---|---|---|---|---|
| t5 | 106 runners, 36% shortened 10%+ | 58, 7% | 40, 10% | 42/46 |
| t3 | 103, 33% | 68, 7% | 33, 9% | 39/42 |
| t2 | 108, 33% | 64, 5% | 32, 9% | 39/42 |

Use it as an **exclusion filter**: no_fly horses shortened 10%+ about 9-10% of the time (all runners 21%) and in the 10x-or-less group the
no_fly horses were 16% against 50% for fly horses. As a pick it is weak (fly horses: about 1 in 3), and `tie` horses behave like `no_fly` horses
(5-7%): not excluded, but not a reason to back a horse. Combine with the scores and flag list above. The six strict-rule misses were mostly
within 1 point of equal (two of the user's picks), which is why `tie` exists. `backtest.py` prints this table; `report.py` scores it live.

## Where it is written

Recorder (`recorder.py`, state in `make_windrops`, `make_windrops_dbl`; files in `publish_windrops`, `publish_windrops_dbl`), once per
point, the moment the board is in (before the race), to the private `odds-data` branch:

- `predictions/<date>_<venue>/race-NN-windrop-<t5|t3|t2>-<run>.json` (`prediction` = Quinella, `longshot` at t2)
- `predictions/<date>_<venue>/race-NN-windrop-dbl-<first|t5|t2>-<run>.json` (`prediction` = Double, `combined` = Double + Quinella, null at `first`)
- the race record `qin-history/.../race-NN-*.json` repeats them as `windrop`, `windrop_dbl`, `windrop_combined`, `windrop_longshot` with
  `*_outcome` after the close: per horse predicted vs actual close, `flagged_n`, `flagged_fell_any`, `flagged_fell_10pct`,
  `missed_fell_10pct`, `brier_10pct`, `in_50pct_band`.

Each prediction row: `win_odds`, `score`, `rank`, `flagged`, `shorten_prob_10pct`, `shorten_prob_any`, `predicted_drop_pct`,
`predicted_close_odds`, `predicted_close_low/high` (50% band); Double rows add `edge_pct`, `dbl_implied_win_odds`; combined rows add
`lead_pct`, `signals`, `signals_fired`, and `both_signals` lists horses in the top 3 on both. A labelled `error` replaces a prediction
whose inputs are missing; nothing is guessed. Every prediction carries its own `validation`, `flag_validation` and `note`.

A prediction failure never stops the recorder (each is wrapped; see `tests/test_windrop*.py`).

## Verified results (leave-one-race-out, 2026-11-14 Sha Tin + 2026-11-18 Happy Valley)

Quinella 16 races, Double / combined 12 races (races 2+). Target: shortened 10%+. Base rate of all runners: 21-26%.
Flag rule = predicted close <= now x 0.95.

| | point | flagged / race | flagged that fell at all | flagged that fell 10%+ | 10%+ fallers caught | Brier 10% (base) |
|---|---|---|---|---|---|---|
| Quinella | t5 / t3 / t2 | 2.5 / 2.2 / 2.3 | 62 / 72 / 76% | 55 / 56 / 59% | 48 / 48 / 52% | .131 / .120 / .112 (.175 / .163 / .163) |
| Double | first / t5 / t2 | 2.7 / 2.6 / 2.2 | 81 / 81 / 85% | 72 / 74 / 74% | 59 / 64 / 61% | .126 / .115 / .107 (.19 / .18 / .17) |
| Combined | t5 / t2 | 2.8 / 2.6 | 73 / 74% | 64 / 65% | 58 / 61% | .109 / .102 (.18 / .17) |

Chances are calibrated (predicted 60%+ -> about 7 in 10 shortened 10%+; under 15% -> about 1 in 25) and the 50% price band holds the close
price about half the time. Close-price error (mean abs ln) 0.22-0.25 against 0.30-0.34 for the average drift alone and 0.35-0.39 for "close = now".
Dropping the shortened-by-10% threshold or the 0.95 flag changes the numbers; do not quote them for other definitions.
`python3 research/windrop/backtest.py --data <odds-data checkout>` reproduces every table above.

## Findings that shaped the design (so nobody has to repeat them)

- The Double edge is the strongest single signal (rank correlation +0.71 to +0.74 in 12/12 races) and is best at `first`, when the frozen
  Double and race N's WIN price are time-aligned. Quinella lead alone is weaker (+0.43 to +0.52). Using the leg-1 WIN price *after* the
  close beats the price before it.
- Quinella *level* (how much keener the Quinella is than WIN right now) predicts; the path from `after_rollover` to t5/t3/t2 does not.
- Restricting leg 1 to 10x or less vs all leg-1 horses (capped prices excluded), different weightings: no real difference (8 variants tested).
- At `first` the Quinella lead hurts (it is not formed yet): the Double-only score is used there.
- Adding more time points or features beyond edge + lead (+ favourite-ness, momentum) did not help; do not add variants without more data.
- Weak spots: long shots (see the longshot flag); horses with no leg-1 partner at 10x or less have no edge; the average prediction under-states
  big drops (many horses fell 40-60% against 15-30% predicted).

## Limits (read before quoting any number)

Two race days, 12-16 races, about 200 runners; each cell of the tables has 10-60 horses, so +-10 points is noise. Chances and price
mapping are fitted on the same races they were checked on (leave-one-race-out removes the optimism only partly; the mapping parameters in
`PROB` are fitted on all races). The combined validation uses the shipped equal weights (an earlier version used fitted weights and looked
7 points better: validation numbers must match the shipped code). Not a betting recommendation: price movement is not a win probability
and no odds, take-out or payout were modelled.

## Keeping it honest as data comes in

1. Merge/deploy the recorder; after each race day run `python3 research/windrop/report.py --data <odds-data checkout>`: the live scorecard
   next to the validated numbers. One race day is about 9 races: do not react to a single day.
2. After about 5 race days (about 45 races) refit: `backtest.py --refit` prints the new `PROB` / `COEFS`. Fix the thresholds
   (10% target, 0.95 flag, 20x longshot, 10x leg-1 cap) **before** looking at the new results, and judge the refit on later days than it was fitted on.
3. Update the numbers in `VALIDATION`, `FLAG_VALIDATION`, `DBL_VALIDATION`, `LONGSHOT_VALIDATION`, `README.md` and the project memory
   (`o882876-boop/hkjc-odds` `memory/`) together, from `backtest.py` output of the shipped definitions.
4. Not done yet: Excel output (JSON first, by request), a value/payout analysis, per-venue or per-class fits.
