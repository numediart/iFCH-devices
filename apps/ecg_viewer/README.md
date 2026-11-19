# ECG Viewer

Desktop viewer for iFCH ECG recordings stored in Movesense record format (`h5`).

## Source layout

- `main.py`: application window and entry point
- `src/views.py`: settings and ECG monitoring views
- `src/r_peaks.py`: ECG peak detection and RR filtering

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
