# Copyright (c) 2026-2026, ISIA Lab (UMONS)
# SPDX-License-Identifier: Apache-2.0

"""Command/status-code validation tests for iFCH Movesense firmware. Requires a
Movesense device with iFCH firmware to be powered and in range to run the full
test suite."""

import pytest

from ifch_drivers.movesense_gatt import (
    Commands,
    MovesenseGatt,
    StatusCodes,
)

ECG_125 = bytearray("/Meas/ECG/125", "utf-8")
ECG_200 = bytearray("/Meas/ECG/200", "utf-8")
ACC_13 = bytearray("/Meas/Acc/13", "utf-8")
INVALID_PATH = bytearray("/Invalid/Path", "utf-8")


@pytest.fixture(scope="session")
async def client():
    devices = await MovesenseGatt.detect_devices()
    if not devices:
        pytest.skip("No Movesense device found.")

    device = MovesenseGatt(devices[0][0])
    connected = await device.start()

    if not connected:
        pytest.fail("Failed to connect to Movesense device.")

    yield device

    await device.stop()


async def run_test_command(
    client: MovesenseGatt,
    command: Commands,
    expected: StatusCodes,
    client_ref=None,
    data=None,
):
    """Send one command and assert returned status code."""
    if client_ref is None:
        client_ref = min(command.value + 10, 255)
    _, code, data_rx = await client.send_and_wait(command, client_ref, data)

    assert code == expected

    return data_rx


async def test_hello(client):
    """Verify HELLO command returns HTTP-like 200 code."""
    await run_test_command(client, Commands.HELLO, StatusCodes.OK_200)


async def test_invalid(client):
    """Verify invalid command is rejected."""
    await run_test_command(client, Commands.INVALID, StatusCodes.ERROR_400)


async def test_time(client):
    """Verify GET_TIME returns success."""
    await run_test_command(client, Commands.GET_TIME, StatusCodes.OK_200)


async def test_set_utc_time(client):
    """Verify valid/invalid SET_UTCTIME payload lengths."""
    await run_test_command(
        client,
        Commands.SET_UTCTIME,
        StatusCodes.OK_200,
        data=(1704742200000000).to_bytes(8, byteorder="little"),
    )

    await run_test_command(
        client,
        Commands.SET_UTCTIME,
        StatusCodes.ERROR_400,
        data=(1704742200000000).to_bytes(10, byteorder="little"),
    )


async def test_battery(client):
    """Verify GET_BATTERY returns success."""
    await run_test_command(client, Commands.GET_BATTERY, StatusCodes.OK_200)


async def test_reset(client):
    """Verify RESET returns success in idle state."""
    await run_test_command(client, Commands.RESET, StatusCodes.OK_200)


async def test_subscribe(client):
    """Verify subscription command status-code matrix."""
    await run_test_command(
        client,
        Commands.SUBSCRIBE,
        StatusCodes.ERROR_403,
        client_ref=0,
        data=ECG_125,
    )

    await run_test_command(
        client,
        Commands.SUBSCRIBE,
        StatusCodes.ERROR_404,
        client_ref=1,
        data=INVALID_PATH,
    )

    await run_test_command(
        client,
        Commands.UNSUBSCRIBE,
        StatusCodes.ERROR_403,
        client_ref=0,
    )

    await run_test_command(
        client,
        Commands.UNSUBSCRIBE,
        StatusCodes.ERROR_404,
        client_ref=1,
    )

    await run_test_command(
        client,
        Commands.SUBSCRIBE,
        StatusCodes.OK_201,
        client_ref=1,
        data=ECG_125,
    )

    await run_test_command(
        client,
        Commands.SUBSCRIBE,
        StatusCodes.OK_201,
        client_ref=2,
        data=ACC_13,
    )

    await run_test_command(
        client,
        Commands.SUBSCRIBE,
        StatusCodes.ERROR_500,
        client_ref=3,
        data=ECG_200,
    )

    await run_test_command(
        client,
        Commands.UNSUBSCRIBE,
        StatusCodes.OK_200,
        client_ref=1,
    )

    await run_test_command(
        client,
        Commands.UNSUBSCRIBE_ALL,
        StatusCodes.OK_200,
    )

    await run_test_command(
        client,
        Commands.UNSUBSCRIBE,
        StatusCodes.ERROR_404,
        client_ref=2,
    )


async def test_datalogger(client):
    """Verify datalogger command state transitions and constraints."""
    data_rx = await run_test_command(
        client,
        Commands.GET_LOGGING_STATE,
        StatusCodes.OK_200,
    )

    assert data_rx[0] == 2

    await run_test_command(
        client,
        Commands.SUB_LOG,
        StatusCodes.ERROR_403,
        client_ref=0,
        data=ECG_125,
    )

    await run_test_command(
        client,
        Commands.SUB_LOG,
        StatusCodes.ERROR_404,
        client_ref=1,
        data=INVALID_PATH,
    )

    await run_test_command(
        client,
        Commands.UNSUB_LOG,
        StatusCodes.ERROR_403,
        client_ref=0,
    )

    await run_test_command(
        client,
        Commands.UNSUB_LOG,
        StatusCodes.ERROR_404,
        client_ref=1,
    )

    await run_test_command(
        client,
        Commands.START_LOG,
        StatusCodes.ERROR_403,
    )

    await run_test_command(
        client,
        Commands.STOP_LOG,
        StatusCodes.OK_202,
    )

    await run_test_command(
        client,
        Commands.CLEAR_LOGS,
        StatusCodes.OK_200,
    )

    await run_test_command(
        client,
        Commands.LIST_LOGS,
        StatusCodes.OK_200,
    )

    await run_test_command(
        client,
        Commands.SUB_LOG,
        StatusCodes.OK_200,
        client_ref=1,
        data=ECG_125,
    )

    await run_test_command(
        client,
        Commands.START_LOG,
        StatusCodes.OK_200,
    )

    data_rx = await run_test_command(
        client,
        Commands.GET_LOGGING_STATE,
        StatusCodes.OK_200,
    )
    assert data_rx[0] == 3

    await run_test_command(
        client,
        Commands.START_LOG,
        StatusCodes.ERROR_409,
    )

    await run_test_command(
        client,
        Commands.CLEAR_LOGS,
        StatusCodes.ERROR_409,
    )

    await run_test_command(
        client,
        Commands.RESET,
        StatusCodes.ERROR_409,
    )

    await run_test_command(
        client,
        Commands.STOP_LOG,
        StatusCodes.OK_200,
    )

    await run_test_command(
        client,
        Commands.UNSUB_LOG,
        StatusCodes.OK_200,
        client_ref=1,
    )

    await run_test_command(
        client,
        Commands.LIST_LOGS,
        StatusCodes.OK_200,
    )

    await run_test_command(
        client,
        Commands.FETCH_LOG,
        StatusCodes.OK_200,
        data=(1).to_bytes(4, byteorder="little"),
    )
