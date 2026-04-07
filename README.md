# iFCH Devices Workspace

Monorepo for iFCH device firmware, Python drivers, desktop applications, and tests.

## Repository Layout

- `apps/`: Desktop applications (`ecg_viewer`, `esp_logger`, `movesense_logger`, `multi_movesense`).
- `drivers/`: Python driver package (`ifch_drivers`), examples, scripts, and tests.
- `devices/`: Embedded firmware projects (`esp_logger`, `movesense_gatt`).

## Typical Workflows

### Run a desktop app

```bash
cd apps/<app_name>
uv run main.py
```

### Run driver tests

```bash
cd drivers
uv run -m pytest
```

### Work on firmware

- ESP logger firmware: see `devices/esp_logger/README.md`.
- Movesense GATT firmware: see `devices/movesense_gatt/README.md`.
