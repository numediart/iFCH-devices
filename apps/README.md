# Apps

Desktop applications for viewing, recording, and managing iFCH device data.

## Projects

- `ecg_viewer`: View previously saved ECG records.
- `esp_logger`: Control the iFCH ESP logger over USB and manage recording workflows.
- `movesense_logger`: Connect to one Movesense device, record data, and export records.
- `multi_movesense`: Monitor and coordinate multiple Movesense devices.

## Run an app

The easiest way to run the apps is to use the pre-compiled binaries available
for windows (you can compile binaries for Linux easily too using pyinstaller).

Alternatively, you can use your own Python to run the code. We recommend using
UV to easily manage all the dependencies.

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
