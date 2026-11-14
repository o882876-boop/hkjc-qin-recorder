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
