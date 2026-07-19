#!/usr/bin/env python3
"""
DoorBird integration driver for Unfolded Circle Remote Two/3.

Exposes door opener and IR light as button entities and doorbell /
motion events as sensor entities.

:license: MPL-2.0, see LICENSE for more details.
"""

import asyncio
import logging
import os
import re
import time
from typing import Any

import ucapi
from ucapi import button, sensor

import config
from doorbird import AuthenticationError, DoorBird, DoorBirdError, EventType

_LOG = logging.getLogger("driver")

EVENT_RESET_SECONDS = 30
"""Safety timeout to reset a doorbell/motion sensor if no low event arrives."""

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)

api = ucapi.IntegrationAPI(_LOOP)

_device: config.DeviceConfig | None = None
_client: DoorBird | None = None
_reset_tasks: dict[str, asyncio.Task] = {}


# ---------------------------------------------------------------------------
# Entity helpers
# ---------------------------------------------------------------------------


def _entity_id(suffix: str) -> str:
    assert _device is not None
    return f"doorbird_{_device.identifier}_{suffix}"


def _relay_suffix(relay: str) -> str:
    return "open_door_" + re.sub(r"[^a-z0-9]+", "_", relay.lower())


def _create_entities() -> None:
    """Create all entities for the configured device."""
    assert _device is not None
    api.available_entities.clear()

    for idx, relay in enumerate(_device.relays, start=1):
        if len(_device.relays) > 1:
            name = {"en": f"{_device.name} Open door {idx}", "de": f"{_device.name} Tür öffnen {idx}"}
        else:
            name = {"en": f"{_device.name} Open door", "de": f"{_device.name} Tür öffnen"}
        api.available_entities.add(
            button.Button(
                _entity_id(_relay_suffix(relay)),
                name,
                cmd_handler=_button_cmd_handler,
            )
        )

    api.available_entities.add(
        button.Button(
            _entity_id("light"),
            {"en": f"{_device.name} IR light", "de": f"{_device.name} IR-Licht"},
            cmd_handler=_button_cmd_handler,
        )
    )

    api.available_entities.add(
        sensor.Sensor(
            _entity_id("doorbell"),
            {"en": f"{_device.name} Doorbell", "de": f"{_device.name} Klingel"},
            [],
            {sensor.Attributes.STATE: sensor.States.ON, sensor.Attributes.VALUE: "OFF"},
            device_class=sensor.DeviceClasses.BINARY,
        )
    )
    api.available_entities.add(
        sensor.Sensor(
            _entity_id("motion"),
            {"en": f"{_device.name} Motion", "de": f"{_device.name} Bewegung"},
            [],
            {sensor.Attributes.STATE: sensor.States.ON, sensor.Attributes.VALUE: "OFF"},
            device_class=sensor.DeviceClasses.BINARY,
        )
    )
    api.available_entities.add(
        sensor.Sensor(
            _entity_id("last_event"),
            {"en": f"{_device.name} Last event", "de": f"{_device.name} Letztes Ereignis"},
            [],
            {sensor.Attributes.STATE: sensor.States.ON, sensor.Attributes.VALUE: "-"},
            device_class=sensor.DeviceClasses.CUSTOM,
        )
    )


async def _button_cmd_handler(
    entity: button.Button, cmd_id: str, _params: dict[str, Any] | None
) -> ucapi.StatusCodes:
    """Handle button push commands: open a door relay or switch on the light."""
    if _client is None or _device is None:
        return ucapi.StatusCodes.SERVICE_UNAVAILABLE
    if cmd_id != button.Commands.PUSH:
        return ucapi.StatusCodes.NOT_IMPLEMENTED

    try:
        if entity.id == _entity_id("light"):
            _LOG.info("Switching on IR light")
            await _client.turn_on_light()
        else:
            for relay in _device.relays:
                if entity.id == _entity_id(_relay_suffix(relay)):
                    _LOG.info("Opening door relay %s", relay)
                    await _client.open_door(relay)
                    break
            else:
                return ucapi.StatusCodes.NOT_FOUND
    except AuthenticationError:
        _LOG.error("Command failed: authentication error")
        return ucapi.StatusCodes.UNAUTHORIZED
    except (DoorBirdError, OSError, asyncio.TimeoutError) as err:
        _LOG.error("Command failed: %s", err)
        return ucapi.StatusCodes.SERVER_ERROR

    return ucapi.StatusCodes.OK


# ---------------------------------------------------------------------------
# DoorBird events
# ---------------------------------------------------------------------------


async def _on_doorbird_event(event: EventType, active: bool) -> None:
    """Update sensor entities on doorbell / motion events."""
    suffix = "doorbell" if event == EventType.DOORBELL else "motion"
    entity_id = _entity_id(suffix)
    _LOG.info("DoorBird event: %s -> %s", suffix, "H" if active else "L")

    api.configured_entities.update_attributes(
        entity_id, {sensor.Attributes.VALUE: "ON" if active else "OFF"}
    )

    if active:
        label = "Ring" if event == EventType.DOORBELL else "Motion"
        timestamp = time.strftime("%H:%M:%S")
        api.configured_entities.update_attributes(
            _entity_id("last_event"),
            {sensor.Attributes.VALUE: f"{label} {timestamp}"},
        )
        _schedule_reset(entity_id)
    elif entity_id in _reset_tasks:
        _reset_tasks.pop(entity_id).cancel()


def _schedule_reset(entity_id: str) -> None:
    """Reset a binary sensor to OFF if the device never sends the low event."""
    if entity_id in _reset_tasks:
        _reset_tasks.pop(entity_id).cancel()

    async def _reset() -> None:
        await asyncio.sleep(EVENT_RESET_SECONDS)
        api.configured_entities.update_attributes(
            entity_id, {sensor.Attributes.VALUE: "OFF"}
        )
        _reset_tasks.pop(entity_id, None)

    _reset_tasks[entity_id] = _LOOP.create_task(_reset())


# ---------------------------------------------------------------------------
# Setup flow
# ---------------------------------------------------------------------------


async def driver_setup_handler(msg: ucapi.SetupDriver) -> ucapi.SetupAction:
    """Handle the driver setup process."""
    if isinstance(msg, ucapi.DriverSetupRequest):
        return await _handle_driver_setup(msg)
    if isinstance(msg, ucapi.AbortDriverSetup):
        _LOG.info("Setup aborted: %s", msg.error)
        return ucapi.SetupError()
    return ucapi.SetupError()


async def _handle_driver_setup(msg: ucapi.DriverSetupRequest) -> ucapi.SetupAction:
    """Validate the entered DoorBird credentials and create the entities."""
    global _device, _client

    host = msg.setup_data.get("host", "").strip()
    username = msg.setup_data.get("username", "").strip()
    password = msg.setup_data.get("password", "")

    if not host or not username or not password:
        _LOG.warning("Setup: missing input values")
        return ucapi.SetupError(ucapi.IntegrationSetupError.OTHER)

    _LOG.info("Setup: connecting to DoorBird at %s", host)
    test_client = DoorBird(host, username, password)
    try:
        info = await test_client.info()
    except AuthenticationError:
        _LOG.error("Setup: authentication failed")
        await test_client.close()
        return ucapi.SetupError(ucapi.IntegrationSetupError.AUTHORIZATION_ERROR)
    except asyncio.TimeoutError:
        _LOG.error("Setup: connection timeout")
        await test_client.close()
        return ucapi.SetupError(ucapi.IntegrationSetupError.TIMEOUT)
    except Exception as err:  # pylint: disable=broad-except
        _LOG.error("Setup: connection failed: %s", err)
        await test_client.close()
        return ucapi.SetupError(ucapi.IntegrationSetupError.CONNECTION_REFUSED)

    mac = info.get("PRIMARY_MAC_ADDR") or info.get("WIFI_MAC_ADDR") or ""
    identifier = mac.lower() if mac else re.sub(r"[^a-z0-9]+", "_", host.lower())
    device_type = info.get("DEVICE-TYPE", "DoorBird")
    relays = [str(r) for r in info.get("RELAYS", ["1"])] or ["1"]

    if _client is not None:
        await _client.close()

    _device = config.DeviceConfig(
        identifier=identifier,
        name=device_type,
        host=host,
        username=username,
        password=password,
        relays=relays,
    )
    config.store(_config_dir(), _device)

    _client = test_client
    _create_entities()
    _client.start_monitor(_on_doorbird_event)

    _LOG.info(
        "Setup complete: %s (%s), firmware %s, relays %s",
        device_type,
        identifier,
        info.get("FIRMWARE"),
        relays,
    )
    return ucapi.SetupComplete()


# ---------------------------------------------------------------------------
# Remote events
# ---------------------------------------------------------------------------


@api.listens_to(ucapi.Events.CONNECT)
async def on_connect() -> None:
    """Set the device state when the remote connects."""
    if _client is None:
        await api.set_device_state(ucapi.DeviceStates.DISCONNECTED)
        return
    try:
        await _client.info()
        await api.set_device_state(ucapi.DeviceStates.CONNECTED)
    except (DoorBirdError, OSError, asyncio.TimeoutError) as err:
        _LOG.warning("DoorBird not reachable: %s", err)
        await api.set_device_state(ucapi.DeviceStates.ERROR)


@api.listens_to(ucapi.Events.DISCONNECT)
async def on_disconnect() -> None:
    """Set the device state when the remote disconnects."""
    await api.set_device_state(ucapi.DeviceStates.DISCONNECTED)


@api.listens_to(ucapi.Events.SUBSCRIBE_ENTITIES)
async def on_subscribe_entities(entity_ids: list[str]) -> None:
    """Push the current sensor states when entities are subscribed."""
    for entity_id in entity_ids:
        if entity_id.endswith(("_doorbell", "_motion")):
            api.configured_entities.update_attributes(
                entity_id,
                {sensor.Attributes.STATE: sensor.States.ON, sensor.Attributes.VALUE: "OFF"},
            )
        elif entity_id.endswith("_last_event"):
            api.configured_entities.update_attributes(
                entity_id,
                {sensor.Attributes.STATE: sensor.States.ON},
            )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _config_dir() -> str:
    return api.config_dir_path or os.getenv("UC_CONFIG_HOME", "./")


async def main() -> None:
    """Start the driver and restore a stored configuration."""
    global _device, _client

    logging.basicConfig(
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        level=os.getenv("UC_LOG_LEVEL", "INFO").upper(),
    )
    logging.getLogger("ucapi").setLevel(os.getenv("UC_LOG_LEVEL", "INFO").upper())

    # locate driver.json: next to this file (pyinstaller bundle), in the
    # project root (development) or in the working directory
    base_dir = os.path.dirname(os.path.realpath(__file__))
    for candidate in (
        os.path.join(base_dir, "driver.json"),
        os.path.join(base_dir, "..", "driver.json"),
        "driver.json",
    ):
        if os.path.isfile(candidate):
            driver_path = candidate
            break
    else:
        driver_path = "driver.json"

    await api.init(os.path.abspath(driver_path), driver_setup_handler)

    _device = config.load(_config_dir())
    if _device:
        _LOG.info("Restored configuration for %s (%s)", _device.name, _device.host)
        _client = DoorBird(_device.host, _device.username, _device.password)
        _create_entities()
        _client.start_monitor(_on_doorbird_event)
    else:
        _LOG.info("No device configured yet, waiting for setup")


if __name__ == "__main__":
    _LOOP.run_until_complete(main())
    _LOOP.run_forever()
