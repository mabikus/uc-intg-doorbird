"""
Small asynchronous client for the DoorBird LAN-2-LAN HTTP API.

Only the endpoints needed by this integration are implemented:
info, open-door, light-on, image and the monitor event stream.

API documentation: https://www.doorbird.com/api

:license: MPL-2.0, see LICENSE for more details.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from enum import Enum

import aiohttp

_LOG = logging.getLogger(__name__)

MONITOR_RECONNECT_DELAY_MIN = 2
MONITOR_RECONNECT_DELAY_MAX = 60


class EventType(str, Enum):
    """Event types delivered by the DoorBird monitor stream."""

    DOORBELL = "doorbell"
    MOTION = "motionsensor"


class DoorBirdError(Exception):
    """Base error for DoorBird API calls."""


class AuthenticationError(DoorBirdError):
    """Wrong username or password, or missing API operator permission."""


class DoorBird:
    """Asynchronous DoorBird LAN API client for a single device."""

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        """Create a client instance for the given device address and credentials."""
        self._host = host
        self._auth = aiohttp.BasicAuth(username, password)
        self._session = session
        self._own_session = session is None
        self._monitor_task: asyncio.Task | None = None

    @property
    def host(self) -> str:
        """Device address as configured."""
        return self._host

    def _url(self, path: str) -> str:
        return f"http://{self._host}{path}"

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
            self._own_session = True
        return self._session

    async def close(self) -> None:
        """Stop the event monitor and release the HTTP session."""
        self.stop_monitor()
        if self._own_session and self._session and not self._session.closed:
            await self._session.close()

    async def _get(self, path: str, timeout: float = 10) -> aiohttp.ClientResponse:
        session = await self._get_session()
        try:
            response = await session.get(
                self._url(path),
                auth=self._auth,
                timeout=aiohttp.ClientTimeout(total=timeout),
            )
        except asyncio.TimeoutError:
            raise
        except aiohttp.ClientError as err:
            raise DoorBirdError(f"Request {path} failed: {err}") from err
        if response.status in (401, 403):
            response.release()
            raise AuthenticationError(f"Authentication failed for {self._host} ({response.status})")
        if response.status != 200:
            response.release()
            raise DoorBirdError(f"Request {path} failed with HTTP {response.status}")
        return response

    async def info(self) -> dict:
        """
        Return device information from info.cgi.

        Contains FIRMWARE, BUILD_NUMBER, PRIMARY_MAC_ADDR / WIFI_MAC_ADDR,
        RELAYS and DEVICE-TYPE.
        """
        response = await self._get("/bha-api/info.cgi")
        data = await response.json(content_type=None)
        return data["BHA"]["VERSION"][0]

    async def open_door(self, relay: str = "1") -> None:
        """Energize the given door opener relay."""
        response = await self._get(f"/bha-api/open-door.cgi?r={relay}")
        response.release()

    async def turn_on_light(self) -> None:
        """Switch on the IR light for the device-defined duration."""
        response = await self._get("/bha-api/light-on.cgi")
        response.release()

    async def restart(self) -> None:
        """Restart the device."""
        response = await self._get("/bha-api/restart.cgi")
        response.release()

    def start_monitor(
        self, callback: Callable[[EventType, bool], Awaitable[None]]
    ) -> None:
        """
        Start the background task listening for doorbell and motion events.

        The callback is invoked with the event type and the new state
        (``True`` = active / H, ``False`` = inactive / L).
        """
        self.stop_monitor()
        self._monitor_task = asyncio.create_task(self._monitor_loop(callback))

    def stop_monitor(self) -> None:
        """Stop the background event monitor task."""
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
        self._monitor_task = None

    async def _monitor_loop(
        self, callback: Callable[[EventType, bool], Awaitable[None]]
    ) -> None:
        delay = MONITOR_RECONNECT_DELAY_MIN
        while True:
            try:
                await self._monitor_once(callback)
                delay = MONITOR_RECONNECT_DELAY_MIN
            except asyncio.CancelledError:
                raise
            except AuthenticationError:
                _LOG.error(
                    "[%s] Monitor: authentication failed, check the API operator permission",
                    self._host,
                )
                delay = MONITOR_RECONNECT_DELAY_MAX
            except (aiohttp.ClientError, asyncio.TimeoutError, DoorBirdError) as err:
                _LOG.info("[%s] Monitor connection lost: %s", self._host, err)
            _LOG.debug("[%s] Reconnecting monitor in %ss", self._host, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, MONITOR_RECONNECT_DELAY_MAX)

    async def _monitor_once(
        self, callback: Callable[[EventType, bool], Awaitable[None]]
    ) -> None:
        """
        Connect to monitor.cgi and dispatch events until the stream ends.

        The endpoint returns a multipart/x-mixed-replace stream with
        text/plain parts containing lines like ``doorbell:H`` or ``motion:L``.
        """
        session = await self._get_session()
        _LOG.debug("[%s] Connecting to event monitor", self._host)
        async with session.get(
            self._url("/bha-api/monitor.cgi?ring=doorbell,motionsensor"),
            auth=self._auth,
            timeout=aiohttp.ClientTimeout(total=None, sock_connect=10, sock_read=300),
        ) as response:
            if response.status in (401, 403):
                raise AuthenticationError(f"Monitor authentication failed ({response.status})")
            if response.status != 200:
                raise DoorBirdError(f"Monitor request failed with HTTP {response.status}")
            _LOG.debug("[%s] Event monitor connected", self._host)
            async for raw_line in response.content:
                line = raw_line.decode(errors="ignore").strip()
                if ":" not in line or line.startswith("--"):
                    continue
                key, _, value = line.partition(":")
                key = key.strip().lower()
                value = value.strip().upper()
                if key in ("doorbell", "motionsensor") and value in ("H", "L"):
                    event = EventType.DOORBELL if key == "doorbell" else EventType.MOTION
                    await callback(event, value == "H")
        raise DoorBirdError("Monitor stream ended")
