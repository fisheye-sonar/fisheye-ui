# FishEye UI

A web-based UI for running [FishEye](https://github.com/fisheye-sonar/fisheye/tree/main/fisheye) fish counting inference on ARIS sonar files. Submit a file and pipeline configuration, monitor progress, and download results from your browser.

## Installing the desktop app

Looking to just run FishEye, not develop it? See the download/install guide
for your platform:
- [Windows](docs/windows-installation.md)
- [macOS](docs/macos-installation.md)

## Requirements

- Python 3.10+
- [Poetry](https://python-poetry.org/)

## Setup

```bash
poetry install
pyenv rehash  # if using pyenv, required to register the fisheye-ui command
poetry run pre-commit install --hook-type pre-push  # run the test suite before every push
```

## To Run

```bash
fisheye-ui
```

## License

MIT