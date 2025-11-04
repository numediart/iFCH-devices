import asyncio

import pytest
from ifch_drivers.movesense_gatt import MovesenseGatt

data_notifications = []
PATH_ECG_125 = "/Meas/ECG/125"


def process_notification(_, data):
    data_notifications.append(data)


@pytest.fixture(scope="session")
async def client():
    devices = await MovesenseGatt.detect_devices()
    if not devices:
        pytest.skip("No Movesense device found.")

    device = MovesenseGatt(
        devices[0][0], movesense_id=devices[0][1], stream_callback=process_notification
    )
    connected = await device.start()

    if not connected:
        pytest.fail("Failed to connect to Movesense device.")

    yield device

    await device.stop()


async def test_hello(client):
    result = await client.hello()
    assert result

    assert result[0] == 1
    parts = result[1:].split(b"\x00")[:-1]
    parts = [part.decode("utf-8") for part in parts]
    assert len(parts) == 5  # Movesense ID, HW version, BLE address, FW name, FW version

    assert len(parts[0]) == 12  # Movesense ID
    assert len(parts[2]) == 17 and parts[2].count(":") == 5  # BLE address


async def test_subscribe(client):
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


async def test_battery(client):
    if not client.is_ifch_firmware:
        pytest.skip("Device is not running iFCH firmware")

    battery = await client.get_battery()
    assert battery is not None
    assert 0 <= battery <= 100


async def test_time(client):
    if not client.is_ifch_firmware:
        pytest.skip("Device is not running iFCH firmware")

    dev_time = await client.get_time()
    assert dev_time is not None
    assert dev_time > 0


async def test_log(client: MovesenseGatt):
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
