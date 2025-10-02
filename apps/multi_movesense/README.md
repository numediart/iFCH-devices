# Deployment

Use UV to run the script and create an environment.

To create an executable, use `uv run pyinstaller main.py` in this directory.
You can add the option `--onefile` to generate a single executable file, but the
startup time will be longer then.
If you do not have `pyinstaller`, get it by running `uv add pyinstaller` in this
directory.
