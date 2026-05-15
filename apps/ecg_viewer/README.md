# ECG Viewer

Desktop viewer for iFCH ECG recordings stored in Movesense record format (`h5`).

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
