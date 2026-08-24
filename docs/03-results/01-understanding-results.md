# Understanding Your Results

When a job finishes, FishEye shows a results summary right in the app, with one
row per sonar file you processed.

## Reading the results table

For each file, you'll see three counts:

- **Upstream** — the number of fish FishEye counted moving in the upstream
  direction
- **Downstream** — the number of fish FishEye counted moving in the downstream
  direction
- **Net** — Upstream minus Downstream, giving the overall movement for that file

## What counts as "upstream"?

Before running a job, you choose which side of the sonar image is upstream at
your site (left or right). FishEye uses that setting to label every fish it
tracks as moving upstream or downstream.

If your counts look reversed, double-check that the upstream direction you
selected matches your actual site setup, and rerun the file if needed.

## If a file couldn't be processed

While a job is running, FishEye keeps track of any files it couldn't process,
for example, a corrupted or unreadable file, and shows a count of them on the
progress screen so you know which numbers to double-check. See
[Troubleshooting](../04-troubleshooting/01-troubleshooting.md#processing-failed)
if this happens.

## Getting more detail

The in-app table shows totals only. For frame-by-frame detections, individual
fish tracks, or files formatted for other software, see
[Output Files](02-output-files.md).
