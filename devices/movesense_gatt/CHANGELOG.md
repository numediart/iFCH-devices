# Changelog

_This describes the relevant changes between iFCH Movesense firmware versions._

---

## 1.8 (05/11/2026)

_No breaking changes, only a quality of life fix._

- Fixed a Movesense bug in which the device would crash if disconnected while
  fetching a log (DataLogger). On disconnect, the device will now continue
  reading until the end of the log (much faster because no data are sent, ~3x
  measured) and refuse other log requests (list/fetch/start) while not
  finished.
