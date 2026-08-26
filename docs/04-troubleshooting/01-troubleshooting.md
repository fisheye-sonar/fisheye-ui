# Troubleshooting

## FishEye won't open on macOS

This is almost always the Gatekeeper warning covered in
[Installing FishEye on macOS](../01-installation/02-macos-installation.md).
MacOS blocks the app because it isn't notarized yet, not because anything is
actually wrong with it. Follow the steps there (running
`xattr -cr "/Applications/FishEye.app"` in Terminal) to fix it.

If FishEye opens briefly and then shows an error saying it failed to start, the
app's background service didn't start correctly. Try restarting your computer
and opening FishEye again. If it keeps happening,
[report a bug](../05-support/01-reporting-a-bug.md) and include the exact error
message from the dialog.

## Windows says the installer isn't trusted

This is Windows SmartScreen, and it's expected for now since the installer isn't
signed yet — see
[Installing FishEye on Windows](../01-installation/03-windows-installation.md)
for the "Keep" / "Keep anyway" steps to get past it.

## GPU acceleration isn't available

FishEye automatically detects the best available option on your computer and
picks it for you. You don't need to configure anything. If GPU acceleration
shows as unavailable in the device dropdown, it usually means:

- **Your computer doesn't have a supported GPU.** FishEye will fall back to CPU
  processing automatically. This still works, just slower.
- **(Windows only) The additional files haven't been installed yet.** The
  first time you launch FishEye on Windows (and again after each update),
  you'll be asked to download extra files FishEye needs to run (see step 5
  of [Installing FishEye on Windows](../01-installation/03-windows-installation.md)).
  If that download is closed before finishing or fails, FishEye won't open.
  Reopen it to be prompted again and complete the download.

## FishEye is running slowly

A few things affect processing speed:

- **Running on CPU instead of GPU.** If GPU acceleration isn't available on your
  computer (see above), FishEye still works, but processing takes longer.
- **Frames per batch is set low on CPU.** When running on CPU, FishEye defaults
  to processing one frame at a time ("Frames per batch" under Advanced options →
  Platform configuration), which is safe but slow. Try raising the batch size
  to 4 or 8 as a starting point and see if processing speeds up. Higher values
  use more memory, so if FishEye slows down, freezes, or crashes instead of
  speeding up, lower it back down.
- **Large files or large batches.** Bigger sonar files and folders with many
  files simply take more time to process.
- **Other demanding apps running at the same time.** Try closing other heavy
  applications while FishEye is processing.
- **Multithreading settings.** Under Advanced options, check that "Use
  multithreading" is turned on and a reasonable number of workers is selected.
  This lets FishEye use more of your computer's processing power at once.

## My file isn't recognized

FishEye only processes ARIS (`.aris`) and DIDSON (`.ddf`) sonar files. Any other
file type can't be selected in the file picker. If you're selecting a folder,
make sure it actually contains `.aris` or `.ddf` files. Folders with none of
these will simply produce no results rather than an error.

## Processing failed

If a job fails, FishEye shows an error message on the progress screen explaining
what happened. Common causes include:

- **Low disk space** in your output folder's drive.
- **No files to process** — the input file or folder didn't contain any new
  `.aris`/`.ddf` files to run (for example, if everything in it already has
  results — see "FishEye found existing results" below).
- **Lost connection** — if FishEye loses its connection to its background
  service mid-job, you'll see a "Lost connection to server" message. Try
  restarting FishEye and running the job again.
- **The app or your computer was restarted** while a job was running.

Click **Show log** on the progress screen for more detail, and include it when
[reporting a bug](../05-support/01-reporting-a-bug.md) if the message doesn't
explain what went wrong.

Note this is different from individual files failing partway through a larger
batch — those are counted as "not successful" in the progress screen's file
counts, while the rest of the batch continues normally.

## FishEye found existing results

If you try to process a file or folder that already has results in the output
folder, FishEye won't overwrite them silently. Instead, it asks you to confirm:
choose **Rerun Anyway** to save new results into a separate, timestamped
subfolder alongside the existing ones, or **Cancel** to leave things as they
are.

## I don't know where my results were saved

Unless you entered a custom output folder under Advanced options, FishEye saves
results in the **same folder as your input file (or input folder)**. The
progress screen also shows the exact results folder path under **Show log**.

If you'd rather not hunt for the folder, you can also download a copy of any
result file directly from the app once processing finishes, using the
**Download** or **Download all** buttons on the results screen.
