# HKJC Quinella recorder

A public GitHub Actions workflow records HKJC Quinella prices and publishes
race JSON files directly to a separate private repository. Run the workflow
on a standard Ubuntu runner in a public repository.

## Deploy

1. Create a new **public** GitHub repository named `hkjc-qin-recorder` and
   push this directory to its default branch, including `.github/workflows`.
2. In the public repo's **Settings → Secrets and variables → Actions**, set
   the variable `PRIVATE_DATA_REPO` to the private destination in
   `owner/repo` format.
3. Set the secret `PRIVATE_DATA_TOKEN` to a fine-grained GitHub token limited
   to that private destination, with **Contents: Read and write**. The
   destination must have an existing `odds-data` branch. The workflow uses
   the secret only to publish. It logs capture and publish status.
4. Confirm scheduled workflows are enabled. To start early by hand, use
   **Actions → Record HKJC Quinella → Run workflow** within 55 minutes of
   the first scheduled post. Automatic wake-ups run every 20 minutes during
   the Hong Kong race window. GitHub may delay a scheduled wake-up.

## Records

Files are written per race to
`odds-data:qin-history/YYYY-MM-DD_VENUE/race-NN-RUN-ATTEMPT.json`.
Each file contains the complete accepted boards, source and observation
times, and percentage odds drops across the four adjacent intervals.
A positive drop means the price shortened.

- `before_rollover` uses the previous race's first observed transition
  from selling to closed.
- `after_rollover` targets two minutes after observed WIN payout, with
  ten minutes after observed finish as a fallback. It is left blank if it
  overlaps T-5.
- `t5` and `t3` use HKJC's published scheduled post time.
- `after_start` uses the first complete closed board observed after a
  started/finished/result race status. If unavailable, a recent last
  open board is clearly labelled as the fallback.
- Missing snapshots are JSON null. First-race rollover points are null.
  An observation up to 35 seconds after a target can qualify.
  The source's update timestamp can differ from the collection time.

A run can archive a partial race record if it starts late or HKJC omits a
board. Retried runs use separate files. GitHub's standard hosted runner
caps individual jobs, and GitHub may disable scheduled workflows in an
inactive public repository. Verify the first live meeting in the Actions
log and inspect the five points for R2 before relying on the output.
