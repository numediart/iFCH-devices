# Apps

Desktop applications for viewing, recording, and managing iFCH device data.

## Projects

- `ecg_viewer`: a simple ECG viewer to display signals recorded with this toolbox
- `esp_logger`: an app to control the ESP controller (start/stop recording, save data)
- `movesense_logger`: an app to run fully autonomous Movesense recordings (without phone nor ESP controller)
- `multi_movesense`: an app to record the live streaming data from multiple Movesense devices simultaneously

## Run an app

This repository is distributed as source code. If you want executable app
artifacts, generate them locally from source (for example with PyInstaller).

You can also run the apps directly with Python. We recommend using UV to easily
manage dependencies and environments.

On Linux and macOS, you can install UV from the terminal:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Or:

```bash
wget -qO- https://astral.sh/uv/install.sh | sh
```

Then, to run an app, use the following directly in the app directory:

```bash
uv run main.py
```

To build your own executable from an app directory:

```bash
uv run pyinstaller --windowed main.py
```

Use `--onefile` for a single binary. Startup time is usually longer.

For **macOS**: we provide helper scripts to easily run the apps without
requiring to manually open a terminal. These are located in each app directory,
and called `launch.command`. You can create a shortcut to these scripts for
convenience, but do not move the scripts themselves.
*These helper scripts still require UV to be installed.*

## Licensing Notes For Executable Distribution

These apps depend on PySide6/Qt and are packaged with PyInstaller.

- PySide6 packages are distributed under LGPL-3.0-only OR GPL-2.0-only OR
  GPL-3.0-only.
- PyInstaller includes GPL terms with a bundling exception; keep its license
  text with your distributed artifacts.

Notices and included license files are available in:

- `../NOTICE.txt`
- `../THIRD_PARTY_NOTICES.md`
- `../licenses/`
