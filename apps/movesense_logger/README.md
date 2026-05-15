# Movesense Logger App

Desktop application for controlling one Movesense device, recording data, and exporting records.

## Run

First install UV (see parent README).

From this directory:

```bash
uv run main.py
```

## Build Your Own Executable

```bash
uv run pyinstaller --windowed main.py
```

Use `--onefile` for a single binary. Startup time is usually longer.
