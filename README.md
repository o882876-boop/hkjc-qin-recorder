# HKJC Quinella recorder

A public GitHub Actions workflow records HKJC Quinella and Win prices and publishes
race JSON files directly to a separate private repository. It runs on a
standard Ubuntu runner in a public repository.

## Deploy

1. Keep this repository public, with the workflow on `main`.
2. In **Settings → Secrets and variables → Actions → Secrets**, set
   `PRIVATE_DATA_REPO` (private destination, `owner/repo`) and
   `PRIVATE_DATA_TOKEN` (fine-grained token limited to that repository,
   **Contents: Read and write**). The destination needs an `odds-data` branch.
   A `PRIVATE_DATA_REPO` *variable* still works, but variables are printed in
   public logs; use the secret and delete the variable.
3. Confirm scheduled workflows are enabled. Scheduled wake-ups are requested every 10
   minutes, 08:02–23:52 Hong Kong time; a run starts recording from 50 minutes
   before the first race. To start by hand, use **Actions → Record HKJC
   Quinella → Run workflow** with all boxes unticked.

GitHub does not keep that schedule: on this repository it has fired about twice a day, hours late (on
2026-11-14 not once before the last race, so races 1–3 were only seen after they were over). The recorder
therefore needs **one** trigger at any time on the race day before the first race, from the schedule, by hand
or from an outside scheduler. A run that starts early waits for the meeting instead of exiting, and a run that
has to stop (near the 6-hour job limit, or after a long wait) queues its own successor with the workflow's
`actions: write` token. A race that is already off when the first run starts cannot be recovered: HKJC serves
no history.

Manual checks: `source_test` checks the live HKJC source. HKJC serves only
the current or next meeting, never history. `write_test` writes and lists a
file in `qin-diagnostics/`. `rehearsal` runs the real capture loop for 4 minutes on the
next live race with the clock shifted to just before its T-5, saves the record
to `qin-diagnostics/rehearsal-RUN.json`, reads it back, and logs how many
seconds after each target the T-5, T-3 and T-2 boards were taken.

## Snapshots (race N)

| point | when |
|---|---|
| `before_rollover` | first poll after race N-1 stops selling (the off) |
| `after_rollover` | 2 min after race N-1 WIN payout (`anchor` says if a fallback was used: result + 10 min, or off + 14 min) |
| `t5`, `t3`, `t2` | 5 / 3 / 2 min before race N's post time; re-taken if HKJC moves the post time |
| `after_start` | first closed board at race N's off. If HKJC withdraws the board, `basis` starts with `FALLBACK_` and the last open board (at most 60 s old) is used |

The per-combination `drop_pct` includes T-3 to T-2 and T-2 to the final board,
plus the existing T-3 to final comparison. Older archives have no `t2`.

The rollover points are timed from the last race that was really run (`rollover_from_race`). An abandoned
race is skipped: it has no off and its refund is not a payout. If a race is only declared abandoned after the
race before it went off, the next race's `before_rollover` target has already passed and its reason is
`race_in_between_abandoned_after_this_target_had_passed`.

Race 1 has no rollover points. The recorder wakes at each target time and
normally takes the snapshot about 1 s after it; if a poll fails it keeps
trying every 2 s until 35 s after the target. Every missing snapshot has a reason in `missing`, such as
`collides_with_t5`, `recorder_not_running_at_target` or `first_race`.
`events` holds the observed stop-sell, off, result and payout times, and each
snapshot keeps HKJC's `source_odds_at`. A selling pause more than 2 minutes
before the post time is logged in `suspensions` and does not count as the off.

Files: `odds-data:qin-history/YYYY-MM-DD_VENUE/race-NN-RUN-ATTEMPT.json`.
A queued run skips races that are already archived. Near GitHub's 6-hour job
limit, the recorder saves its state to `qin-handoff/` at a quiet moment
between races, and the next queued run resumes from that state. Races that
were already off when a run first saw them are archived with empty snapshots
and a reason. Their boards are never relabelled.

## Testing

`python3 -m unittest discover -s tests -v` runs offline race-day simulations.

## Win snapshots

Each new race JSON includes `win_points` and `win_missing` at the same six targets as Quinella. Each WIN board is keyed by horse number and keeps its own HKJC price update time. Both pools are read in the same poll, with separate validation and cutoff fallback labels. Compare source update times when inferring which pool moved first. Older race records may have no WIN snapshots.

`win_runners` gives each horse's own `drop_pct` across the same `CHANGE_INTERVALS` as the Quinella `combinations` rows (T-3 to T-2, T-2 to the final board, T-3 to final, etc.), so a WIN price drop is as easy to read as a Quinella one. Older race records have no `win_runners`.

## Double (孖寶)

The recorder also captures the Double pool, which pairs race N (leg 1) with race N+1 (leg 2) and closes at
race N's off. For every race N that has a following race it stores four boards, all anchored to race N:
`t5`, `t3`, `t2` (5/3/2 minutes before its post time) and `after_start` (first closed board at its off, with the
same labelled `FALLBACK_` rule as Quinella). There are no rollover points. The last race has no Double.

Combinations are **ordered** (`"3-7"` = horse 3 in race N, horse 7 in race N+1; `"7-3"` is a different bet) and a
board is only kept when the full leg-1 x leg-2 grid is present. Files:
`odds-data:dbl-history/YYYY-MM-DD_VENUE/race-NN-RUN.json` (`NN` = leg-1 race, schema 1). `drop_pct` has
`t5_to_t3`, `t3_to_t2`, `t2_to_after_start` and `t3_to_after_start`.

`leg2_void` says when the leg-2 race was abandoned, and `source_failures` counts failed Double polls; a Double
whose pool could never be read has the reason `double_source_failed_or_rejected`. Records still open when the
run ends are written with up to four attempts.

The Double query only runs from 6 minutes before a post time and is isolated from the Quinella loop: if HKJC
rejects or fails it, Quinella and WIN recording carry on unchanged. `source_test` now also lists the Double
pools (informational, it never fails the check).

## `final_open`: the last board before the close

T-5/T-3/T-2 follow the *published* post time, but HKJC often runs a race late (e.g. posted 14:25, off 14:29:57), so
those points can sit several minutes before the real off. Every Quinella, WIN and Double record therefore also has
`final_open` (`win_final_open` for WIN): the last board seen while the pool was still selling, with
`seconds_before_close` (how long before the observed stop-sell it was taken, normally under 10 s). Each combination
row has `final_open_odds` and `final_drop_pct_from_t3`. Use this as the end point when you want the price closest to the
real off. Existing fields are unchanged. The Double poll now follows the observed off (up to 45 min past the post
time) instead of stopping 70 s after the published post time.

## `c5` / `c3` / `c2`: points measured back from the real close

`t5/t3/t2` are scheduled from the published post time, so a race that runs late (the off keeps slipping, or the post time is
never updated) gets them 15/13/12 minutes before the real close instead of 5/3/2. The recorder therefore also keeps a
rolling window of open boards (one every 20 s, last 8 minutes) for Quinella, WIN and Double. When the pool closes it picks
the boards nearest to **observed close - 5 / - 3 / - 2 min** and stores them as `close_points` (`c5`, `c3`, `c2`,
`win_close_points` for WIN), each with `offset_seconds` (how far the sample is from the exact target, within 30 s) and a
reason in `close_missing` when one cannot be found. Each combination row gets `close_odds` and `close_drop_pct`
(`c5_to_c3`, `c3_to_c2`). Nothing needs to be predicted, so a 10 or 30 minute delay, or repeated delays, make no difference.
The close is the observed stop-sell (accurate to about 8 s). The rolling window is not carried over a hand-over, so a race
whose run was taken over mid-race has `close_missing` instead of guessed values. Existing fields are unchanged.

## t3 and t2 predictions (`predictions/`)

Two predictions are made for every race, each the moment its boards are in (Quinella and WIN, within a few seconds):

| point | looks at | predicts |
|---|---|---|
| `t3` | how much each horse's price shortened from `t5` to `t3` | which horses keep shortening from `t3` to the close |
| `t2` | `t5` (or `t3`) to `t2` | which horses keep shortening from `t2` to the close |

`momentum_v1`: for each horse the mean Quinella-combination drop and the WIN drop over the "before" window, each z-scored and
added (Quinella alone if the WIN board is more than 60 s late). Each prediction is written straight away in its own small file,
so it can be read before the race:
`odds-data:predictions/YYYY-MM-DD_VENUE/race-NN-t3-RUN.json` and `race-NN-t2-RUN.json`, with `prediction.top` (3 horses expected
to keep shortening) and `prediction.horses` (every horse: score, drops, WIN price at that point).

Both are repeated in the race's `qin-history` record as `t3_prediction` / `t2_prediction`, each with `*_outcome` (what every horse
really did from that point to `after_start`, the three that actually shortened most, and `qin_top_hits` against
`qin_chance_hits`, the hits expected by chance). Add these up over many race days before trusting either.

It predicts *which prices keep shortening*, not which horse wins. Back-test on the two meetings recorded so far (the model was chosen
after looking at them, so the figures are optimistic): `t3` 15 races, 20 of 45 top-3 picks against about 10.7 by chance, rank
correlation +0.30 with 14 of 15 races positive; `t2` 7 races, 11 of 21 against about 4.6. `t3`/`t2` follow the published post time, so
for a race that runs late the prediction covers a longer period. A prediction bug can only blank the prediction
(`prediction.error`), never the record.

## 66888 water indices during the meeting (`record-indices.yml`)

`indices_recorder.py` reads the public 66888 W/P water-index page of every race at 10, 5 and 2 minutes
before the published post time and 1 minute after the off, and stores one JSON per race under
`indices-live/<date>_<venue>/` in the private archive. 66888 clears the values of finished races, so these
cannot be recovered afterwards. A point that could not be read keeps its status (`missed`, `no_values`,
`no_data`, `error`, `verification_wall`); nothing is filled in. Values are the page as displayed at capture
time, not 66888's own history. It reuses the meeting calendar and private archive writer of `recorder.py`,
checks robots.txt first (fail closed) and stops at a verification wall.

Trigger it once on race day before the first race (it waits for the meeting, up to 5.5 hours), preferably
from the same external scheduler that triggers `record.yml`: `POST /repos/<owner>/hkjc-qin-recorder/actions/workflows/record-indices.yml/dispatches`
with `{"ref":"main"}`. A backup schedule exists but GitHub fires it unreliably. Checks: `probe` reads race 1
once and reports the status; `write_test` verifies the private archive write.

> The whole windrop family (Quinella, Double, combined, longshot, flag list) is described in [docs/WINDROP.md](docs/WINDROP.md); reproduce with `research/windrop/backtest.py`, score live with `research/windrop/report.py`.

## windrop_v1: predicted WIN shortening and close price (t5, t3, t2)

At t5, t3 and t2 of every race the recorder also writes `predictions/<date>_<venue>/race-NN-windrop-<point>-<run>.json`
(written the moment the board is in, before the race) and repeats it in the race record (`windrop`, `windrop_outcome`
after the off). Per horse: WIN odds now, WIN-implied %, Quinella support %, `lead_pct` (Quinella support / WIN-implied - 1),
`score`, `rank`, `predicted_drop_pct` (+ = WIN expected to shorten until the close) and `predicted_close_odds`.
`top` is the three highest scores. See `windrop.py` for the exact formula and coefficients.

Fitted on 16 races (Sha Tin 2026-11-14, Happy Valley 2026-11-18, 204 runners); two meetings, so treat it as exploratory.
Leave-one-race-out: about 54% of the top three shortened by 10% or more (about 21% of all runners do); the typical error
of the predicted close price is about 20-25% (mean |ln error| 0.225 at t2 against 0.264 for favourite-ness alone and 0.346
for "close = now"). A ranking signal, not a betting recommendation. Refit the coefficients as more race days are stored;
`windrop_outcome` in each race record is the out-of-sample check.

## windrop_dbl_v1: Double (孖寶) prediction, and the chance of shortening (races 2+)

Three separate predictions, each with the chance that the WIN price ends **10% or more shorter** (`shorten_prob_10pct`) or
shorter at all (`shorten_prob_any`), and a predicted close price with a 50% band (`predicted_close_odds`,
`predicted_close_low` .. `predicted_close_high`):

- **Quinella** - `windrop_v1`, at t5, t3, t2 (above).
- **Double** - `windrop_dbl_v1`, at `first`, t5, t2: score = edge only.
- **Combined** - `windrop_dbl_v1_combined`, at t5, t2: edge plus the Quinella lead (the best calibrated of the three).

The Double of legs (N-1, N) is frozen when race N-1 stops selling. Its price for (a, b) should be about W1(a) x W2(b), where
W1 is race N-1's WIN price after the close. Dividing by W1 gives the race-N price the Double bettors had in mind
(`dbl_implied_win_odds`, weighted over leg-1 horses at 10x or less). `edge_pct` is how much longer the WIN price is than that;
long = expected to shorten. `first` is race N's first WIN board after race N-1 stopped selling (about 30 minutes before race N).

Written per race 2+ as `predictions/<date>_<venue>/race-NN-windrop-dbl-<first|t5|t2>-<run>.json` (`prediction` = Double,
`combined` = Double + Quinella, null at `first`) and repeated in the race record (`windrop_dbl`, `windrop_combined` and their
`*_outcome`, which score each chance with a Brier value and count the horses inside the 50% band).

Fitted on 12 races (Sha Tin 2026-11-14, Happy Valley 2026-11-18), 16 for the Quinella model; checked leave-one-race-out. The
chances are calibrated: horses given 60%+ shortened 10%+ about 7 times in 10, horses given under 15% about 1 time in 25, and the
50% band holds the close price about half the time. Brier score of the 10% chance (lower is better, base rate alone in brackets):
Double 0.107-0.126 (0.17-0.19), combined 0.102-0.109 (0.17-0.18), Quinella 0.112-0.131 (0.16-0.18). Exploratory, two
meetings: a ranking and a chance, not a betting recommendation; refit as more race days are stored.


### Flag list and longshot flag

Every prediction also carries `flagged`: the horses whose predicted close price is at least 5% below the price now (no top-N, a race
can have 0 or 5), with `flag_validation`. At t2 the Quinella file also carries `longshot` (`windrop_longshot_v1`): horses at 20x or
more that are in the race top 3 by Quinella-combination drop t5 -> t2 (13 flagged -> 4 shortened 10%+, 61 not flagged -> 0; low
confidence, 4 fallers). Race records add `windrop_longshot` and the `*_outcome` scoring. See docs/WINDROP.md.

### Quinella 飛 states

Every Quinella, Double and combined prediction row says whether the horse's Quinella-pool share is above its WIN-implied share (`qin_fly_state`:
`fly`, `tie` within 1 percentage point below, `no_fly` below that; `qin_fly_points` for t5/t3/t2). `qin_no_fly` is the exclusion list (tie is never
excluded). 16 races: no_fly horses shortened 10%+ only about 9-10% of the time (all runners 21%) and 39 of 42 fallers were kept. An exclusion
filter, not a pick. See docs/WINDROP.md.

### Quinella share path from the previous payout

Rows also carry the Quinella-pool share path after_rollover -> t5 -> t3 -> t2 (`qin_pct_path`, `qin_rise_from_rollover_pct`, `qin_rise_from_t5_pct`,
`qin_rise_steps`, `qin_rise_all_steps`) and, at t2, `qin_fall5_from_t5`: horses whose share fell 5%+ from t5 (0 of 17 shortened 10%+). Rising at every step is only
a weak helper on top of qin fly (fly + every step up 35% of 31; no fly + every step up 5%). See docs/WINDROP.md.
