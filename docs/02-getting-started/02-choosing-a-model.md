# Choosing a Model

FishEye uses an object detection model to find fish in your sonar videos. You
can pick which one to use from the model dropdown on the run screen.

## Which model should I use?

If you're not sure, use the default: **YOLOv5m v0 — Recommended**. It's already
selected when you open FishEye and works well for most files.

## Available models

| Model | What it is                                                 |
|---|------------------------------------------------------------|
| YOLOv5m v0 — Recommended | The current default model.                                 |
| YOLOv5s v1 | A smaller, faster model (the newer of the two "s" models). |
| YOLOv5s v0 | A smaller, faster model (the original small model).        |

As a general rule, the larger "m" model can take a bit longer to run than the
smaller "s" models, but is more thorough. If processing speed matters more to
you than squeezing out every last detection, for example, if you're just doing a
quick check of a file, a smaller model may suit you better. If you're unsure,
start with the recommended default; you can always rerun a file with a different
model afterward and compare.

## Do I need to download anything first?

FishEye downloads the chosen automatically in the background. You'll need an
internet connection for that one-time download. After that, the model is stored
on your computer and ready to use instantly, even offline.

### No internet on this machine?

If the computer running FishEye won't have internet access, the automatic
download won't work. Instead:

1. On a computer with internet access, go to the
   [fisheye releases page](https://github.com/fisheye-sonar/fisheye/releases)
   (note: this is a different repository than the FishEye app itself) and
   download the `.pt` file matching the model you want (e.g.
   `cfc_detect_yolov5m_v0.pt` for YOLOv5m v0).

2. Copy that file to the computer running FishEye (e.g. via USB drive) and
   place it anywhere you like.

3. In FishEye, open Advanced options and enter the file's location in the
   **custom model weights path (optional)** field instead of using the model dropdown.

## Using your own model file

Advanced users can use a custom model file instead of one of the options above,
using the **custom weights path** field under Advanced options. This overrides
the model dropdown. Most users won't need this.
