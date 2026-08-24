# FishEye Output Files

After processing is complete, FishEye creates files containing your results,
saved to your output folder. You can choose which file types to generate under
**Export options** on the run screen: Summary CSV, Detailed CSV, and ARISFish
Count File are selected by default; MOT is optional.

For an explanation of the upstream/downstream counts themselves, see
[Understanding Your Results](01-understanding-results.md).

## Summary CSV

One CSV file with one row per ARIS or DIDSON file, showing its upstream,
downstream, and net fish counts. This is the same information shown in the
in-app results table, saved as a spreadsheet you can open in Excel or Google
Sheets.

## Detailed CSV (per file)

One CSV file per ARIS or DIDSON file, with one row per fish FishEye detected
including its distance, direction, and other measurements. Use this if you need
to look at individual detections rather than just totals.

## ARISFish Count File

A text file compatible with Sound Metrics' ARISFish software, containing each
detected fish's distance, direction, and other measurements. This is the
**only** export format that can be opened in ARISFish to review and edit fish
markers.

## Multi-Object Tracking (MOT) File

Contains FishEye's fish tracks in the standard MOT format used by computer
vision research and evaluation tools. Most users won't need this. It's intended
for technical/research use.
