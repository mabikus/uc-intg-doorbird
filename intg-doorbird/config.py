"""
Configuration handling: persist the configured DoorBird device.

:license: MPL-2.0, see LICENSE for more details.
"""

import dataclasses
import json
import logging
import os

_LOG = logging.getLogger(__name__)

_CFG_FILENAME = "config.json"


@dataclasses.dataclass
class DeviceConfig:
    """Stored configuration of one DoorBird device."""

    identifier: str
    name: str
    host: str
    username: str
    password: str
    relays: list[str]


def _config_path(config_dir: str) -> str:
    return os.path.join(config_dir, _CFG_FILENAME)


def load(config_dir: str) -> DeviceConfig | None:
    """Load the device configuration, or return None if not configured yet."""
    path = _config_path(config_dir)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as file:
            data = json.load(file)
        return DeviceConfig(**data)
    except (json.JSONDecodeError, OSError, TypeError) as err:
        _LOG.error("Cannot load configuration from %s: %s", path, err)
        return None


def store(config_dir: str, device: DeviceConfig) -> bool:
    """Persist the device configuration."""
    path = _config_path(config_dir)
    try:
        os.makedirs(config_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8") as file:
            json.dump(dataclasses.asdict(device), file, indent=2)
        return True
    except OSError as err:
        _LOG.error("Cannot store configuration to %s: %s", path, err)
        return False


def remove(config_dir: str) -> None:
    """Delete the stored configuration."""
    path = _config_path(config_dir)
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError as err:
        _LOG.error("Cannot remove configuration %s: %s", path, err)
