# ECG Viewer

Desktop viewer for iFCH ECG recordings stored in Movesense record format (`h5`).

## Run

From this directory:

```bash
uv run main.py
```

## Build Executable

```bash
uv run pyinstaller main.py
```

Use `--onefile` for a single binary. Startup time is usually longer.
