# Multi Movesense App

Desktop application for monitoring and coordinating multiple Movesense devices.

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
