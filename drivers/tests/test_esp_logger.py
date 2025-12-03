import warnings

import pytest
from ifch_drivers.esp_logger import ESPLogger


@pytest.fixture(scope="session")
async def device():
    devices = await ESPLogger.detect_devices()

    if len(devices) == 0:
        pytest.skip("No ESP Logger device found.")

    selected_device = devices[0]
    port = selected_device[0]
    device = ESPLogger(port)

    await device.start()

    status = await device.get_status()
    if status is None:
        pytest.fail("Failed to get ESP Logger status")
    elif status["logging"]:
        pytest.skip(
            "ESP Logger is currently logging. Please stop logging before running tests."
        )

    yield device

    ok = await device.disconnect()
    if not ok:
        pytest.fail("Failed to disconnect from ESP Logger")


async def test_version(device: ESPLogger):
    assert await device.get_version()


async def test_rid(device: ESPLogger):
    rid = await device.get_record_id()
    assert rid is not None


async def test_status(device: ESPLogger):
    status = await device.get_status()
    assert status is not None
    assert not status["logging"]
    assert not status["connected"]
    assert not status["streaming"]


async def test_reset(device: ESPLogger):
    assert await device.force_reset_state()


async def test_battery(device: ESPLogger):
    assert await device.get_battery()


async def test_epoch(device: ESPLogger):
    assert await device.get_epoch()


async def test_put_epoch(device: ESPLogger):
    assert await device.put_epoch()


async def test_free_space(device: ESPLogger):
    assert await device.get_free_space()


async def test_get_error_log(device: ESPLogger):
    assert await device.get_error_log() is not None


async def test_delete_error_log(device: ESPLogger):
    assert await device.delete_error_log()


async def test_get_logs(device: ESPLogger):
    logs = await device.list_logs(show_archived=False)
    assert logs is not None

    if logs is not None and len(logs) > 0:
        log_id = logs[0]

        assert await device.list_dir(log_id)

        assert await device.archive_log(log_id)

    else:
        warnings.warn("No logs found to test archiving.")
        logs = await device.list_logs(show_archived=True)
        if logs is None or len(logs) == 0:
            pytest.skip("No logs found to test directory listing.")

        log_id = logs[0]

        assert await device.list_dir(log_id)


async def test_config(device: ESPLogger):
    movesense_address = "00:00:00:00:00:00"
    movesense_id = "FakeID"
    assert await device.set_address(movesense_address, movesense_id)

    config = await device.get_config()
    assert config is not None
    assert config["address"] == movesense_address
    assert config["MovesenseID"] == movesense_id


async def test_movesense(device: ESPLogger):
    devices = await device.scan()
    assert devices is not None

    if len(devices) == 0:
        pytest.skip("No Movesense device found.")

    movesense_split = devices[0].split(";")
    assert await device.set_address(movesense_split[-1], movesense_split[0])

    assert await device.connect()

    status = await device.get_status()
    assert status is not None
    assert status["connected"]

    is_mov_logging = await device.get_mov_islogging()
    assert is_mov_logging is not None
    if is_mov_logging:
        pytest.skip(
            "Movesense is currently logging. Please stop logging before testing."
        )

    result = await device.hello_movesense()
    assert result is not None

    assert result[0] == 1
    parts = result[1:].split(b"\x00")[:-1]
    parts = [part.decode("utf-8") for part in parts]
    assert len(parts) == 5  # Movesense ID, HW version, BLE address, FW name, FW version

    assert len(parts[0]) == 12  # Movesense ID
    assert len(parts[2]) == 17 and parts[2].count(":") == 5  # BLE address

    assert await device.get_mov_battery()

    assert await device.sub_stream()

    status = await device.get_status()
    assert status is not None
    assert status["streaming"]

    assert await device.unsub_stream()

    status = await device.get_status()
    assert status is not None
    assert not status["streaming"]

    assert await device.start_movesense_logging()

    status = await device.get_status()
    assert status is not None
    assert status["logging"]

    assert await device.stop_movesense_logging()

    status = await device.get_status()
    assert status is not None
    assert not status["logging"]

    assert await device.disconnect()

    status = await device.get_status()
    assert status is not None
    assert not status["logging"]
    assert not status["connected"]
    assert not status["streaming"]
