import pytest
from ifch_drivers.movesense_gatt import MovesenseGatt, detect_device


@pytest.fixture
async def client():
    devices = await detect_device()
    if not devices:
        pytest.skip("No Movesense device found.")

    device = MovesenseGatt(devices[0][0], movesense_id=devices[0][1])
    connected = await device.start()

    if not connected:
        pytest.fail("Failed to connect to Movesense device.")

    yield device

    await device.stop()


async def test_hello(client):
    assert await client.hello()


async def test_subscribe(client):
    path = "/Meas/ECG/125"
    assert await client.subscribe(path)

    assert not await client.subscribe(path), "Should not be able to subscribe twice"


# TODO implement iFCH tests:
# check logs list empty after clear
# check logs list contains one log after logging
# check fetch logs sends correct number of packets
