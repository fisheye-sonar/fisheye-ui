# Installing FishEye on macOS

FishEye is currently an unsigned test app (it hasn't been notarized by
Apple yet). Because of that, macOS may show a warning saying the app is
"damaged" and should be moved to the Trash. This is just macOS being
cautious about unsigned software. The app isn't actually damaged, and the
steps below get you past it.

*(This build is for Apple Silicon Macs e.g., M1/M2/M3/M4. There's no Intel
build yet.)*

1. Go to the [FishEye releases page](https://github.com/fisheye-sonar/fisheye-ui/releases)
   on GitHub and find the most recent release (e.g. `v1.0.0-beta.2`). Scroll
   down to **Assets** and click the file ending in `.dmg`.

2. Double-click the downloaded `.dmg` file in your Downloads folder.

3. When the installer window opens, drag **FishEye** into your
   **Applications** folder.

4. Open Terminal by pressing **Command + Space**, type `Terminal`, and press
   **Return**.

5. Copy and paste the following command into Terminal, then press
   **Return**:

   ```
   xattr -cr "/Applications/FishEye.app"
   ```

6. Open **FishEye** again from your Applications folder.

You should only need to do the Terminal step **once** per install. These
instructions are temporary as they won't be needed anymore once the app is
signed and notarized.

Still having trouble? See [Troubleshooting](../04-troubleshooting/01-troubleshooting.md).
