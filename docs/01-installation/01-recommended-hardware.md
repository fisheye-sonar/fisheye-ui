# Recommended Hardware

FishEye processes sonar footage using an object detection model. This runs much
faster on a computer with a dedicated graphics card (GPU) than on one without,
so it's worth knowing the difference before you buy or choose a machine to run
FishEye on.

## GPU vs. CPU: what's the difference?

Most everyday Windows laptops (the kind used for browsing, email, and office
work) only have **integrated graphics**: graphics processing built into the same
chip as the CPU, shared with everything else the computer is doing. FishEye
still works on these, it just runs on the CPU and takes longer.

A computer with a **dedicated GPU** has a separate chip built specifically for
graphics and AI-heavy work. These are most commonly found in laptops marketed
for gaming or as creator/content-creation machines, and they let FishEye process
files significantly faster.

**How to tell which one a laptop has:** look at the listed graphics. Integrated
graphics show up as something like "Intel Iris Xe Graphics" or "AMD Radeon
Graphics" with no separate model number. A dedicated GPU is listed by name and
model, e.g. "NVIDIA GeForce RTX 4070". If you see an NVIDIA GeForce RTX (or
similar) listed, that's a dedicated GPU.

> Apple Silicon Macs (M1 and newer) have GPU acceleration built in
> automatically. There's nothing extra to buy or configure. That said, a
> dedicated NVIDIA GPU is still generally faster for this kind of work than a
> Mac's built-in GPU, so this page mainly matters if you're choosing or
> purchasing a Windows machine.

## Recommended laptop

If you're purchasing a new Windows computer specifically to run FishEye, a
gaming or creator laptop with an NVIDIA GPU is the reliable way to get one at a
reasonable price. A good option:

**Acer Predator Triton Neo 16 Gaming Creator Laptop** (model `PTN16-51-932N`)

| Spec | Detail |
|---|---|
| Processor | Intel Core Ultra 9 185H |
| Graphics | NVIDIA GeForce RTX 4070 |
| Memory | 32GB LPDDR5X |
| Storage | 1TB SSD |

This isn't the only option that will work well. Any Windows laptop with a
dedicated NVIDIA GeForce RTX GPU is a good fit. If you're comparing other
machines, prioritize:

- **A dedicated NVIDIA GeForce RTX GPU** — the biggest factor in processing
  speed.
- **A newer GPU generation.** The number after "RTX" indicates how new/fast the
  GPU is — higher is better. Aim for RTX 40-series or newer (e.g. RTX 4060,
  4070, 4080) if you can. Avoid older cards like a GTX 1080, even though it's
  a dedicated GPU, it predates the RTX line and is far slower for this kind of
  work.
- **16GB of RAM or more** (32GB is comfortable).
- **SSD storage**, for faster file loading than a traditional hard drive.

## Do I need this to use FishEye?

No. FishEye works on a CPU-only computer too; it just takes longer to process
files (see
[FishEye is running slowly](../04-troubleshooting/01-troubleshooting.md#fisheye-is-running-slowly)).
This page is only for teams or individuals purchasing a new machine who want the
fastest experience.

Once you have a machine, see
[Installing FishEye on Windows](03-windows-installation.md) to get started.
