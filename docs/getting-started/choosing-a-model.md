# Choosing a Model

FishEye uses an object detection model to find fish in your sonar
videos. You can pick which one to use from the model dropdown on the run
screen.

## Which model should I use?

If you're not sure, use the default: **YOLOv5m v0 — Recommended**. It's
already selected when you open FishEye and works well for most files.

## Available models

| Model | What it is                                                 |
|---|------------------------------------------------------------|
| YOLOv5m v0 — Recommended | The current default model.                                 |
| YOLOv5s v1 | A smaller, faster model (the newer of the two "s" models). |
| YOLOv5s v0 | A smaller, faster model (the original small model).        |

As a general rule, the larger "m" model can take a bit longer to run
than the smaller "s" models, but is more thorough. If processing speed
matters more to you than squeezing out every last detection, for
example, if you're just doing a quick check of a file, a smaller model
may suit you better. If you're unsure, start with the recommended
default; you can always rerun a file with a different model afterward
and compare.

## Do I need to download anything first?

No. The first time you use a given model, FishEye downloads it
automatically in the background. You'll need an internet
connection for that one-time download. After that, the model is stored
on your computer and ready to use instantly, even offline.

## Using your own model file

Advanced users can use a custom model file instead of one of the
options above, using the **custom weights path** field under Advanced
options. This overrides the model dropdown. Most users won't need this.