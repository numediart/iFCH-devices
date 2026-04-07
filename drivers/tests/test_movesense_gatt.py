"""Integration tests for MovesenseGatt high-level BLE workflows. Requires a
Movesense device with iFCH firmware to be powered and in range to run the full
test suite."""

import asyncio
import datetime

import pytest
from ifch_drivers.movesense_gatt import MovesenseGatt

data_notifications = []
PATH_ECG_125 = "/Meas/ECG/125"
TEST_TIME = 1704742200000000


def process_notification(_, data):
    """Collect incoming stream packets for subscription assertions."""
    data_notifications.append(data)


@pytest.fixture(scope="session")
async def client():
    devices = await MovesenseGatt.detect_devices()
    if not devices:
        pytest.skip("No Movesense device found.")

    device = MovesenseGatt(devices[0][0], stream_callback=process_notification)
    connected = await device.start()

    if not connected:
        pytest.fail("Failed to connect to Movesense device.")

    yield device

    await device.stop()


async def test_hello(client):
    """Verify hello response content and structure."""
    result = await client.hello()
    assert result

    assert result[0] == 1
    parts = result[1:].split(b"\x00")[:-1]
    parts = [part.decode("utf-8") for part in parts]
    assert len(parts) == 5  # Movesense ID, HW version, BLE address, FW name, FW version

    assert len(parts[0]) == 12  # Movesense ID
    assert len(parts[2]) == 17 and parts[2].count(":") == 5  # BLE address


async def test_subscribe(client):
    """Verify subscribe/unsubscribe behavior and data reception."""
    data_notifications.clear()

    assert await client.subscribe(PATH_ECG_125)

    assert not await client.subscribe(PATH_ECG_125), (
        "Should not be able to subscribe twice"
    )

    assert not await client.subscribe("/Invalid/Path"), (
        "Should not be able to subscribe to invalid path"
    )

    await asyncio.sleep(0.5)

    assert await client.unsubscribe(PATH_ECG_125)

    assert not await client.unsubscribe(PATH_ECG_125), (
        "Should not be able to unsubscribe twice"
    )

    assert len(data_notifications) > 0, "No data received during subscription"


async def test_unsubscribe_all(client: MovesenseGatt):
    """Verify unsubscribe-all clears active stream subscriptions."""
    if not client.is_ifch_firmware:
        pytest.skip("Device is not running iFCH firmware")

    data_notifications.clear()

    assert await client.subscribe(PATH_ECG_125)

    await asyncio.sleep(0.5)

    assert len(data_notifications) > 0, "No data received during subscription"

    assert await client.unsubscribe_all()

    data_notifications.clear()

    await asyncio.sleep(0.5)

    assert len(data_notifications) == 0, "Data received after unsubscribe all"


async def test_battery(client: MovesenseGatt):
    """Verify battery endpoint returns a valid percentage."""
    if not client.is_ifch_firmware:
        pytest.skip("Device is not running iFCH firmware")

    battery = await client.get_battery()
    assert battery is not None
    assert 0 <= battery <= 100


async def test_time(client: MovesenseGatt):
    """Verify time get/set operations for UTC synchronization."""
    if not client.is_ifch_firmware:
        pytest.skip("Device is not running iFCH firmware")

    dev_time = await client.get_time()
    assert dev_time is not None
    assert isinstance(dev_time, tuple) and len(dev_time) == 2
    assert dev_time[0] > 0 and dev_time[1] > 0

    success = await client.set_utc_time(TEST_TIME)
    assert success is not None, "Failed to set UTC time"

    dev_time = await client.get_time()
    assert dev_time is not None, "Failed to get time"

    assert 0 < dev_time[1] - TEST_TIME < 10_000_000, (
        f"Device time {dev_time[1]} is not close to set time {TEST_TIME}"
    )

    now = datetime.datetime.now(tz=datetime.timezone.utc)
    success = await client.set_utc_time()
    assert success is not None, "Failed to set UTC time to current time"

    dev_time = await client.get_time()
    assert dev_time is not None, "Failed to get time"

    now_timestamp_us = int(now.timestamp() * 1e6)
    assert 0 < dev_time[1] - now_timestamp_us < 10_000_000, (
        f"Device time {dev_time[1]} is not close to current time {now_timestamp_us}"
    )


async def test_log(client: MovesenseGatt):
    """Verify logging lifecycle and log retrieval commands."""
    if not client.is_ifch_firmware:
        with pytest.raises(RuntimeError):
            await client.reset()
        return

    assert await client.reset()

    is_logging = await client.get_logging_state()
    assert is_logging is False

    assert await client.sub_log(PATH_ECG_125)

    assert not await client.sub_log(PATH_ECG_125), (
        "Should not be able to subscribe twice"
    )

    assert not await client.sub_log("/Invalid/Path"), (
        "Should not be able to subscribe to invalid path"
    )

    assert await client.start_log()

    await asyncio.sleep(0.5)

    is_logging = await client.get_logging_state()
    assert is_logging is True

    assert await client.stop_log()

    assert await client.unsub_log(PATH_ECG_125)

    assert not await client.unsub_log(PATH_ECG_125), (
        "Should not be able to unsubscribe twice"
    )

    is_logging = await client.get_logging_state()
    assert is_logging is False

    log_list = await client.list_logs()
    assert log_list is not None
    assert len(log_list) == 1

    log_id = log_list[0]

    log_data = await client.fetch_log(log_id)
    assert log_data is not None
    assert len(log_data) > 0

    assert await client.clear_logs()

    log_list = await client.list_logs()
    assert log_list is not None
    assert len(log_list) == 0


async def test_reset(client: MovesenseGatt):
    """Verify reset clears subscriptions and logs when allowed."""
    assert await client.sub_log(PATH_ECG_125)

    assert await client.start_log()

    await asyncio.sleep(0.5)

    assert not await client.reset(), "Should not be able to reset while logging"

    assert await client.stop_log()

    assert await client.subscribe(PATH_ECG_125)

    assert await client.reset()

    assert not await client.unsubscribe(PATH_ECG_125), (
        "Should not be able to unsubscribe after reset"
    )

    assert not await client.unsub_log(PATH_ECG_125), (
        "Should not be able to unsubscribe log after reset"
    )

    log_list = await client.list_logs()
    assert log_list is not None
    assert len(log_list) == 0, "Logs should be cleared after reset"
