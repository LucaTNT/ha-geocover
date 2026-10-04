"""Fixtures for Decathlon Geocover tests. The pygeocover client is always mocked."""

from __future__ import annotations

from collections.abc import Generator
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from pygeocover import (
    BatteryState,
    Bike,
    BikeState,
    Health,
    LoginRequest,
    Ride,
    RidePage,
    TokenSet,
    User,
)
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.geocover.const import CONF_TOKENS, DOMAIN

BIKE_ID = 30058
USER_ID = 89295

LOGIN_SETTINGS = {
    "idp_client_id": "idp-client",
    "idp_issuer_id": "https://idp.example/connect",
    "idp_redirect_uri": "https://login.ids.conneq.tech/oauth/idpresponse",
    "idp_scopes": "email openid profile",
    "idp_uri": "https://idp.example/authorize",
}

TOKENS = {"access_token": "old-access", "refresh_token": "old-refresh", "expires_at": 0.0}


def bike_payload(**overrides: Any) -> dict[str, Any]:
    """Shape of a real `GET bike` item (values made up)."""
    payload = {
        "id": BIKE_ID,
        "name": "Elops 920E",
        "imei": "123456789012345",
        "battery_percentage": 80,
        "odometer": 1234567,
        "manufacturer": "decathlon",
        "frame_number": "FRAME123",
        "article_number": "3608409847683",
        "bike_image_url": "https://example.invalid/bike.jpg",
        "is_stolen": False,
        "ride_in_progress": False,
        "blepass": "secret-ble-pass",
        "activation_code": "ACTCODE",
        "last_location": {
            "id": "1b30058",
            "lat": "45.4642",
            "lon": "9.19",
            "date": "2026-10-04T10:14:04+0000",
            "speed": 12,
            "battery_percentage": 0,
            "bike_id": BIKE_ID,
            "is_moving": True,
        },
        "owning_user": {"id": USER_ID, "email": "luca@example.invalid", "name": "Luca"},
        "geofences": [],
    }
    payload.update(overrides)
    return payload


def make_bike(**overrides: Any) -> Bike:
    """A parsed bike."""
    return Bike.from_dict(bike_payload(**overrides))


def make_state(**overrides: Any) -> BikeState:
    """A parsed bike state."""
    data = {
        "powered_on": True,
        "ecu_locked": True,
        "erl_locked": None,
        "battery_percentage": None,
        "charging": False,
        "range": 42,
        "odometer": 1234,
    }
    data.update(overrides)
    return BikeState.from_dict(data)


def make_health() -> Health:
    """A parsed health response (real format)."""
    return Health.from_list(
        [
            {"key": "last_connection", "status": True, "value": "2026-10-04T10:16:42+0000"},
            {"key": "last_gps", "status": False, "value": "2026-10-04T10:14:04+0000"},
            {"key": "gps_battery", "status": True, "value": "43%"},
            {"key": "bike_system", "status": True, "value": "true"},
        ]
    )


def make_battery(**overrides: Any) -> BatteryState:
    """A parsed battery/current-state response."""
    data = {
        "battery_percentage": None,
        "charging": False,
        "range": None,
        "last_battery_update": None,
        "last_full_charge": None,
    }
    data.update(overrides)
    return BatteryState.from_dict(data)


def make_ride(ride_id: int = 1, **overrides: Any) -> Ride:
    """A parsed ride."""
    data = {
        "id": ride_id,
        "start_date": "2026-10-03T16:00:00+0000",
        "end_date": "2026-10-03T16:45:00+0000",
        "distance_traveled": 15230,
        "active_time": 2400,
        "avg_speed": 22.8,
        "co2": 2100,
        "elevation_up": 120,
        "elevation_down": 118,
        "name": "Home to Work",
    }
    data.update(overrides)
    return Ride.from_dict(data)


def make_login_request() -> LoginRequest:
    """A real LoginRequest, so extract_code() behaves like the library."""
    return LoginRequest.create(LOGIN_SETTINGS)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integrations in all tests."""


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """A configured entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Luca",
        unique_id=str(USER_ID),
        data={CONF_TOKENS: dict(TOKENS)},
    )


@pytest.fixture
def login_request() -> LoginRequest:
    """The login request returned by async_start_login."""
    return make_login_request()


@pytest.fixture
def mock_client(login_request: LoginRequest) -> Generator[MagicMock]:
    """Mock GeocoverClient everywhere it is constructed.

    `mock_client.init_kwargs` holds the constructor kwargs of the last instance,
    e.g. the on_tokens_updated callback.
    """
    client = MagicMock()
    client.init_kwargs = {}
    client.async_start_login = AsyncMock(return_value=login_request)
    client.async_finish_login = AsyncMock(
        return_value=TokenSet("new-access", "new-refresh", time.time() + 14400)
    )
    client.async_get_user = AsyncMock(
        return_value=User.from_dict({"id": USER_ID, "username": "uuid", "display_name": "Luca"})
    )
    client.async_get_bikes = AsyncMock(return_value=[make_bike()])
    client.async_get_state = AsyncMock(return_value=make_state())
    client.async_get_health = AsyncMock(return_value=make_health())
    client.async_get_battery = AsyncMock(return_value=make_battery())
    client.async_get_latest_ride = AsyncMock(return_value=make_ride())
    client.async_get_rides = AsyncMock(
        return_value=RidePage(rides=[make_ride()], total=1, offset=0, limit=1)
    )

    def _factory(session: Any, tokens: TokenSet | None = None, **kwargs: Any) -> MagicMock:
        client.init_tokens = tokens
        client.init_kwargs = kwargs
        return client

    with (
        patch("custom_components.geocover.GeocoverClient", side_effect=_factory),
        patch("custom_components.geocover.config_flow.GeocoverClient", side_effect=_factory),
    ):
        yield client


async def setup_integration(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Set up the integration."""
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
