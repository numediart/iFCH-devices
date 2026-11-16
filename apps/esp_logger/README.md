# ESP Logger App

Desktop controller for iFCH ESP logger hardware and Movesense recording workflows.

## Run

First install UV (see parent README).

From this directory:

```bash
uv run main.py
```

## Browse existing device logs

For advanced recovery, open **Settings** and select **Browse device logs** while
the iFCH device is connected, not recording, and no download is in progress.
The browser includes archived logs (whose names start with `_`). Choose one
log, enter the required record information, and save it to the configured output
directory. Streaming is paused while browsing and restored if you cancel.

The usual export creates a raw ZIP and converted output. As with a normal
recording export, it archives an unarchived device log and copies and deletes
the device error log. A log that is already archived is not archived again.
After a successful download the application shows its final success screen.

## Build Your Own Executable

```bash
uv run pyinstaller --windowed main.py
```

Use `--onefile` for a single binary. Startup time is usually longer.
