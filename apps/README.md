# Apps

Desktop applications for viewing, recording, and managing iFCH device data.

## Projects

- `ecg_viewer`: a simple ECG viewer to display signals recorded with this toolbox
- `esp_logger`: an app to control the ESP controller (start/stop recording, save data)
- `movesense_logger`: an app to run fully autonomous Movesense recordings (without phone nor ESP controller)
- `multi_movesense`: an app to record the live streaming data from multiple Movesense devices simultaneously

## Run an app

The easiest way to run the apps is to use the pre-compiled binaries available
for Windows (you can compile binaries for Linux easily too using pyinstaller).

Alternatively, you can use your own Python to run the code. We recommend using
UV to easily manage all the dependencies and environments.

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

For **macOS**: we provide helper scripts to easily run the apps without
requiring to manually open a terminal. These are located in each app directory,
and called `launch.command`. You can create a shortcut to these scripts for
convenience, but do not move the scripts themselves.
*These helper scripts still require UV to be installed.*
