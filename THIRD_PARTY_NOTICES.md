# Third-Party Notices

This document records third-party software notices and license references for
this repository.

This is a technical compliance aid, not legal advice.

## Included License Files

- Project license: `LICENSE` (Apache-2.0)
- Movesense SDK license copy: `licenses/Movesense_SDK_LICENSE.pdf`
- PyInstaller license text: `licenses/PyInstaller-COPYING.txt`
- GNU LGPL-3.0 text: `licenses/LGPL-3.0.txt`
- GNU GPL-3.0 text: `licenses/GPL-3.0.txt`
- GNU GPL-2.0 text: `licenses/GPL-2.0.txt`

## Firmware Components

### ESP logger firmware (`devices/esp_logger`)

- Built with ESP-IDF and ESP-IDF components.
- ESP-IDF is Apache-2.0 licensed.
- Required license/attribution texts are referenced by this file and
  `NOTICE.txt`.

### Movesense GATT firmware (`devices/movesense_gatt`)

- Built with Movesense SDK/device-lib.
- Movesense terms come from a separate SDK evaluation license included as
  `licenses/Movesense_SDK_LICENSE.pdf`.
- The license text defines use for evaluation/testing Purpose and states that
  commercialization is subject to a separate agreement.

## Desktop App Components (`apps/*`)

- Desktop apps depend on PySide6/Qt and PyInstaller.
- PySide6 / PySide6_Addons / PySide6_Essentials / shiboken6 package metadata
  indicates license expression:
  `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`.
- PyInstaller metadata indicates GPLv2-or-later with bundling exception.

## Where Notices Are Placed

- Root attribution summary: `NOTICE.txt`
- Third-party details: `THIRD_PARTY_NOTICES.md`
- License texts and vendor terms: `licenses/`
