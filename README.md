# FishEye UI

A web-based UI for running [FishEye](https://github.com/fisheye-sonar/fisheye/tree/main/fisheye) for fish counting inference on ARIS sonar files. Submit a file and pipeline configuration, monitor progress, and download results from your browser.

- **[Website](https://fisheye-sonar.github.io/)** — learn more about FishEye
- **[Try the cloud demo](https://docs.google.com/forms/d/e/1FAIpQLSdcFlfHc9t18jregFgqe-DpXS0pwbkTSrn4Yxy9yNiA5-PNRA/viewform)** — request access, no install required
- **[Documentation](docs/)** — installation guides, quick start, troubleshooting

## Installing the desktop app

Looking to just run FishEye, not develop it? See the download/install guide
for your platform:
- [Windows](docs/01-installation/03-windows-installation.md)
- [macOS](docs/01-installation/02-macos-installation.md)
- [Recommended hardware](docs/01-installation/01-recommended-hardware.md) — buying a new machine? Read this first.

## Developing FishEye UI

The rest of this README is for contributors building the app from source.

### Requirements

- Python 3.10+
- [Poetry](https://python-poetry.org/)
- [npm](https://docs.npmjs.com/downloading-and-installing-node-js-and-npm) (for the frontend, in `frontend/`)
- [git](https://git-scm.com/downloads) (`poetry install` pulls the `fisheye` dependency directly from GitHub)

### Setup

```bash
poetry install
pyenv rehash  # if using pyenv, required to register the fisheye-ui command
poetry run pre-commit install --hook-type pre-push  # run the test suite before every push
```

### To Run

```bash
fisheye-ui
```

## License

MIT