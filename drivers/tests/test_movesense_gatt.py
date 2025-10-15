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
    assert await client.hello()


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
        with pytest.raises(RuntimeError):
            await client.unsubscribe_all()
        return

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
        with pytest.raises(RuntimeError):
            await client.get_battery()
        return

    battery = await client.get_battery()
    assert battery is not None
    assert 0 <= battery <= 100


async def test_time(client):
    if not client.is_ifch_firmware:
        with pytest.raises(RuntimeError):
            await client.get_time()
        return

    dev_time = await client.get_time()
    assert dev_time is not None
    assert dev_time > 0


# TODO implement iFCH tests:
# check logging state on/off during logging
# check logs list empty after clear
# check logs list contains one log after logging
# check fetch logs sends correct number of packets
