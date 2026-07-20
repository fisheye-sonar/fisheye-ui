# GPU worker setup

Runs FishEye UI directly via Poetry on a GPU EC2 instance, as a
systemd service that restarts on crash/reboot. This instance is the one the
gateway box (separate, not documented here yet) wakes on demand and reverse
proxies to (**no public IP**, reachable only from the
gateway's security group.)

## Before running setup.sh

- **Instance type:** g4dn.xlarge (T4) or similar.
- **Driver installation:** `setup.sh` assumes the driver is already present;
  it does not install one.
- **Security group:** no inbound rule from `0.0.0.0/0`. Only allow inbound
  on port 8000 (or whatever `PORT` is set to) from the gateway box's
  security group/private IP.

## Running it

SSH into the instance, clone the repo (or just copy this `deploy/gpu-worker/`
directory over if you'd rather not check out the whole repo before Poetry
is installed), and run:

```bash
bash setup.sh
```

This installs Python/Poetry, clones the repo to `/opt/fisheye-ui`, runs
`poetry install`, checks whether the installed `torch` picked up
the GPU, and installs + starts the systemd service.

## Verifying

```bash
sudo systemctl status fisheye-ui   # should be active (running)
curl localhost:8000/health         # {"status": "ok"}
curl localhost:8000/platform       # native_file_picker should be false here
```

`native_file_picker` should read `false` on this box (no display, likely no
`zenity` either) — that's the signal the frontend uses to show the upload
input instead of the native OS pickers. If it reads `true`, something about
the headless assumption doesn't hold on this AMI and is worth a second look
before moving on to the gateway.

`/tmp/fisheye-ui-uploads/` is self-cleaning: each upload's raw file is
deleted as soon as its job finishes with it, and a background sweep clears
out anything left over (abandoned uploads, output dirs still waiting on a
download) after 24 hours.