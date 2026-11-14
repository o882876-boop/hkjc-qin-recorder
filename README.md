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
3. Confirm scheduled workflows are enabled. Scheduled wake-ups run every 10
   minutes, 11:02–23:52 Hong Kong time; a run starts recording from 50 minutes
   before the first race. To start by hand, use **Actions → Record HKJC
   Quinella → Run workflow** with all boxes unticked.

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

The Double query only runs from 6 minutes before a post time and is isolated from the Quinella loop: if HKJC
rejects or fails it, Quinella and WIN recording carry on unchanged. `source_test` now also lists the Double
pools (informational, it never fails the check).
