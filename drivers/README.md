# Drivers

Python drivers, examples, scripts, and tests for communicating with iFCH devices.
These drivers are designed to be used by the iFCH apps, or to be installed as
a dependency for other Python projects that need to communicate with iFCH devices.

Supported devices include:

- iFCH ESP Logger
- Movesense MD/FLASH (standard and iFCH firmware)

## Contents

- `ifch_drivers/`: Main Python package.
- `examples/`: Small usage examples.
- `scripts/`: Helper scripts for driver-related maintenance tasks.
- `tests/`: Integration and protocol-level tests.

## Common Commands

In order to run the commands below, you need to have installed
[UV](https://docs.astral.sh/uv/getting-started/installation/).
It will automatically create a virtual environment and install the dependencies.

If you are planning to contribute code to this repository, it is recommended to
install the provided pre-commit hooks that will automatically run some complance
checks before each commit. To do so, run the following command from this directory:

```bash
uv run pre-commit install
```

Run tests from this directory (the tests require a connected device):

```bash
uv run pytest
```

Run an example:

```bash
uv run examples/example_movesense_gatt.py
```
