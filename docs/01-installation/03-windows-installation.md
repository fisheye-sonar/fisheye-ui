# Installing FishEye on Windows

1. Go to the
   [FishEye releases page](https://github.com/fisheye-sonar/fisheye-ui/releases)
   on GitHub and find the most recent release (e.g. `v1.0.0-beta.2`). Scroll
   down to **Assets** and click the file named `win-setup.exe`.

2. Wait for the download to finish. Depending on your browser, you may need to
   open the Downloads panel, click the **⋯** (three dots) next to the file, and
   choose **Keep**. You may then be asked to confirm you trust the file, choose
   **Keep Anyway**.

3. Open your Downloads folder and double-click `win-setup.exe`.

4. You'll see an "Installing, please wait…" screen while the installer sets
   things up.

5. A window will ask how you'd like to get the additional files FishEye needs
   to run (this step happens on every install and can't be skipped):
   - If you're connected to the internet, choose **Download automatically**.
   - If you've already downloaded these files separately, choose **I already
     have the files** instead.

Once you make a selection, installation finishes and FishEye opens
automatically.

## If you already have the files (no internet on this machine)

1. On a computer with internet access, go back to the same release's
   **Assets** list from step 1 and download every file named
   `FishEye-<version>-gpu-runtime-win.part1-of-N.zip`,
   `...part2-of-N.zip`, and so on — there may be several. Keep their
   original file names.

2. Copy all of those files to the Windows computer you're installing
   FishEye on (e.g. via USB drive).

3. When step 5 above asks how to get the files, choose **I already have the
   files…**. A window will open asking you to select files, select **all**
   of the part files together (not one at a time), then confirm.

Still having trouble? See
[Troubleshooting](../04-troubleshooting/01-troubleshooting.md).
