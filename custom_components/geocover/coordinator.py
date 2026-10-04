"""Data update coordinator for Decathlon Geocover."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from pygeocover import (
    BatteryState,
    Bike,
    BikeState,
    GeocoverApiError,
    GeocoverAuthError,
    GeocoverClient,
    GeocoverConnectionError,
    Health,
    Ride,
)

from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN, RIDE_UPDATE_INTERVAL

if TYPE_CHECKING:
    from . import GeocoverConfigEntry

_LOGGER = logging.getLogger(__name__)


def describe_error(err: Exception) -> str:
    """Describe an API error without its message.

    pygeocover builds GeocoverConnectionError from repr() of the aiohttp error, which
    can include request headers (a proxy's credentials, potentially the Bearer
    token), so that text must never reach the log.
    """
    if isinstance(err, GeocoverApiError):
        return f"HTTP {err.status}"
    if isinstance(err, GeocoverConnectionError):
        cause = err.__cause__
        return f"connection error ({type(cause).__name__})" if cause else "connection error"
    return f"invalid response ({type(err).__name__})"


@dataclass
class GeocoverBikeData:
    """Everything known about one bike."""

    bike: Bike
    state: BikeState | None = None
    health: Health | None = None
    battery: BatteryState | None = None
    latest_ride: Ride | None = None
    rides_fetched_at: datetime | None = None

    @property
    def battery_percentage(self) -> int | None:
        """Bike battery level.

        `GET bike` reports 0 (not null) while the battery has never reported, when
        state and battery/current-state say null. A 0 is only trusted once the
        battery endpoint has a last update timestamp.
        """
        for source in (self.state, self.battery):
            if source is not None and source.battery_percentage is not None:
                return source.battery_percentage
        value = self.bike.battery_percentage
        if value:
            return value
        if value == 0 and self.battery is not None and self.battery.last_battery_update:
            return 0
        return None

    @property
    def range_km(self) -> float | None:
        """Remaining range."""
        for source in (self.state, self.battery):
            if source is not None and source.range_km is not None:
                return source.range_km
        return None

    @property
    def charging(self) -> bool | None:
        """Whether the bike battery is charging."""
        for source in (self.state, self.battery):
            if source is not None and source.charging is not None:
                return bool(source.charging)
        return None


class GeocoverCoordinator(DataUpdateCoordinator[dict[int, GeocoverBikeData]]):
    """Polls the Geocover API for all bikes of an account."""

    config_entry: GeocoverConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: GeocoverConfigEntry, client: GeocoverClient
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                minutes=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )
        self.client = client

    async def _async_update_data(self) -> dict[int, GeocoverBikeData]:
        """Fetch bikes, then state/health/battery (and rides when due) per bike."""
        previous = self.data or {}
        try:
            bikes = await self.client.async_get_bikes()
            results = await asyncio.gather(
                *(self._async_update_bike(bike, previous.get(bike.id)) for bike in bikes)
            )
        except GeocoverAuthError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="auth_failed"
            ) from err
        # ValueError: pygeocover doesn't wrap a non-JSON 200 body (e.g. a maintenance page)
        except (GeocoverConnectionError, GeocoverApiError, ValueError) as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": describe_error(err)},
            ) from None  # the chained error text may hold request headers
        return {data.bike.id: data for data in results}

    async def _async_update_bike(
        self, bike: Bike, previous: GeocoverBikeData | None
    ) -> GeocoverBikeData:
        data = GeocoverBikeData(bike=bike)
        if previous is not None:
            data.state = previous.state
            data.health = previous.health
            data.battery = previous.battery
            data.latest_ride = previous.latest_ride
            data.rides_fetched_at = previous.rides_fetched_at

        now = dt_util.utcnow()
        ride_ended = (
            previous is not None and previous.bike.ride_in_progress and not bike.ride_in_progress
        )
        fetch_rides = (
            data.rides_fetched_at is None
            or ride_ended
            or now - data.rides_fetched_at >= RIDE_UPDATE_INTERVAL
        )

        calls: list[Awaitable[object]] = [
            self.client.async_get_state(bike.id),
            self.client.async_get_health(bike.id),
            self.client.async_get_battery(bike.id),
        ]
        if fetch_rides:
            calls.append(self.client.async_get_latest_ride(bike.id))
        results = await asyncio.gather(*calls, return_exceptions=True)

        # Auth and connection problems fail the whole update; an API error on one
        # of these secondary endpoints only keeps its previous value.
        for result in results:
            if isinstance(result, BaseException) and not isinstance(result, GeocoverApiError):
                raise result
        state, health, battery, *ride = results
        if not isinstance(state, GeocoverApiError):
            data.state = state  # type: ignore[assignment]
        if not isinstance(health, GeocoverApiError):
            data.health = health  # type: ignore[assignment]
        if not isinstance(battery, GeocoverApiError):
            data.battery = battery  # type: ignore[assignment]
        if ride and not isinstance(ride[0], GeocoverApiError):
            data.latest_ride = ride[0]  # type: ignore[assignment]
            data.rides_fetched_at = now
        for result in results:
            if isinstance(result, GeocoverApiError):
                _LOGGER.debug("Ignoring API error for bike %s: %s", bike.id, describe_error(result))
        return data
