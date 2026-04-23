# ESP Logger App

Desktop controller for iFCH ESP logger hardware and Movesense recording workflows.

## Run

First install UV (see parent README).

From this directory:

```bash
uv run main.py
```

## Build Executable

```bash
uv run pyinstaller --windowed main.py
```

Use `--onefile` for a single binary. Startup time is usually longer.
