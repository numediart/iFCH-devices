# iFCH Devices

iFCH devices firmware, Python drivers and desktop applications.

The scope of these tools is to provide a complete hardware and software
environment for recording cardiac signals (ECG, SCG/GCG) using
[Movesense](https://www.movesense.com/) wearable devices.

The project also includes a custom ESP-based controller that allows continuously
recording with an autonomous Movesense FLASH device (i.e. not connected to a phone)
for as long as its battery lasts. This extends the maximum recording duration up
to 10 days typically.

## Repository Layout

- `apps/`: user-friendly desktop applications:
  - `ecg_viewer`: a simple ECG viewer to display signals recorded with this toolbox
  - `esp_logger`: an app to control the ESP controller (start/stop recording, save data)
  - `movesense_logger`: an app to run fully autonomous Movesense recordings (without phone nor ESP controller)
  - `multi_movesense`: an app to record the live streaming data from multiple Movesense devices simultaneously
- `devices/`: embedded firmware projects (`esp_logger`, `movesense_gatt`).
- `drivers/`: Python driver package to control the devices (`ifch_drivers`), examples, scripts, and tests.

## Typical Workflows

All the described workflows require the installation of
[UV](https://docs.astral.sh/uv/getting-started/installation/).
It will automatically create a virtual environment and install the dependencies.

### Run a desktop app

```bash
cd apps/<app_name>
uv run main.py
```

### Run driver tests

```bash
cd drivers
uv run pytest
```

### Work on firmware

- ESP logger firmware: see `devices/esp_logger/README.md`.
- Movesense GATT firmware: see `devices/movesense_gatt/README.md`.

## Third-Party Notices

Third-party attributions are included directly in this repository:

- `NOTICE.txt`: short attribution summary.
- `THIRD_PARTY_NOTICES.md`: detailed component-level notices.
- `licenses/`: included third-party license texts and vendor terms.

## Authors

This project is developed by the Computational Health group at [ISIA Lab](https://web.umons.ac.be/isia/),
[UMONS](https://web.umons.ac.be/).  It was initiated by [François Marelli](mailto:francois.marelli@umons.ac.be)
as part of the iFCH project, funded by the [Marie Skłodowska-Curie COFUND Action](https://cometowallonia.eu/)
under grant agreement 101034383.

The iFCH project was started as a collaboration between Dr Jean-Marie Grégoire,
Pr Stéphane Carlier, Pr Thierry Dutoit, Dr François Marelli, and Dr Cédric Gillon.

## License

This repository uses a dual-license model:

- `apps/` — **GPL-3.0-only** (see `apps/LICENSE`), required by PySide6/Qt.
- `devices/` and `drivers/` — **Apache-2.0** (see `devices/LICENSE`, `drivers/LICENSE`).

See `NOTICE.txt` and `THIRD_PARTY_NOTICES.md` for full third-party attribution.
