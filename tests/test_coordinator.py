"""Tests for the Geocover data update coordinator."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from pygeocover import GeocoverApiError, GeocoverAuthError, GeocoverConnectionError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.geocover.const import CONF_SCAN_INTERVAL

from .conftest import BIKE_ID, make_bike, make_ride, make_state, setup_integration

POLL = timedelta(minutes=5)


async def _tick(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, delta: timedelta = POLL
) -> None:
    # +1 s: the coordinator schedules refreshes slightly after the interval
    freezer.tick(delta + timedelta(seconds=1))
    async_fire_time_changed(hass)
    # interval refreshes run as background tasks
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_polls_every_interval(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Bikes, state, health and battery are fetched every cycle."""
    await setup_integration(hass, mock_config_entry)
    for count in (2, 3):
        await _tick(hass, freezer)
        assert mock_client.async_get_bikes.await_count == count
        assert mock_client.async_get_state.await_count == count
        assert mock_client.async_get_health.await_count == count
        assert mock_client.async_get_battery.await_count == count
    mock_client.async_get_state.assert_awaited_with(BIKE_ID)


async def test_custom_interval(
    hass: HomeAssistant,
    mock_client: MagicMock,
    freezer: FrozenDateTimeFactory,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The polling interval comes from the options."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(mock_config_entry, options={CONF_SCAN_INTERVAL: 1})
    await setup_integration(hass, mock_config_entry)
    await _tick(hass, freezer, timedelta(minutes=1))
    assert mock_client.async_get_bikes.await_count == 2


async def test_rides_fetched_less_often(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The latest ride is fetched at setup, then every 30 minutes."""
    await setup_integration(hass, mock_config_entry)
    assert mock_client.async_get_latest_ride.await_count == 1

    for _ in range(5):  # 25 minutes
        await _tick(hass, freezer)
    assert mock_client.async_get_latest_ride.await_count == 1

    mock_client.async_get_latest_ride.return_value = make_ride(2, distance_traveled=5000)
    await _tick(hass, freezer)  # 30 minutes
    assert mock_client.async_get_latest_ride.await_count == 2
    assert hass.states.get("sensor.elops_920e_last_ride_distance").state == "5.0"


async def test_ride_fetched_when_ride_ends(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """When ride_in_progress goes off, the new ride is fetched straight away."""
    await setup_integration(hass, mock_config_entry)
    mock_client.async_get_bikes.return_value = [make_bike(ride_in_progress=True)]
    await _tick(hass, freezer)
    assert mock_client.async_get_latest_ride.await_count == 1

    mock_client.async_get_bikes.return_value = [make_bike(ride_in_progress=False)]
    mock_client.async_get_latest_ride.return_value = make_ride(2, distance_traveled=7000)
    await _tick(hass, freezer)
    assert mock_client.async_get_latest_ride.await_count == 2
    assert hass.states.get("sensor.elops_920e_last_ride_distance").state == "7.0"


async def test_connection_error_marks_unavailable(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """GeocoverConnectionError -> UpdateFailed -> unavailable, then recovers."""
    await setup_integration(hass, mock_config_entry)
    mock_client.async_get_bikes.side_effect = GeocoverConnectionError("timeout")
    await _tick(hass, freezer)
    assert hass.states.get("sensor.elops_920e_battery").state == STATE_UNAVAILABLE
    assert hass.states.get("device_tracker.elops_920e").state == STATE_UNAVAILABLE

    mock_client.async_get_bikes.side_effect = None
    await _tick(hass, freezer)
    assert hass.states.get("sensor.elops_920e_battery").state == "80"


async def test_connection_error_on_secondary_endpoint(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A timeout on state/health also fails the update."""
    await setup_integration(hass, mock_config_entry)
    mock_client.async_get_health.side_effect = GeocoverConnectionError("timeout")
    await _tick(hass, freezer)
    assert hass.states.get("sensor.elops_920e_battery").state == STATE_UNAVAILABLE


async def test_non_json_response_fails_update(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """pygeocover lets a JSON decode error through; it becomes UpdateFailed."""
    await setup_integration(hass, mock_config_entry)
    mock_client.async_get_bikes.side_effect = ValueError("Expecting value")
    await _tick(hass, freezer)
    assert hass.states.get("sensor.elops_920e_battery").state == STATE_UNAVAILABLE


async def test_api_error_on_secondary_endpoint_keeps_previous(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """An HTTP error on /state keeps the last state instead of failing everything."""
    await setup_integration(hass, mock_config_entry)
    mock_client.async_get_state.side_effect = GeocoverApiError(500, "oops")
    mock_client.async_get_bikes.return_value = [make_bike(battery_percentage=55)]
    await _tick(hass, freezer)
    assert hass.states.get("sensor.elops_920e_battery").state == "55"
    assert hass.states.get("sensor.elops_920e_range").state == "42.0"

    mock_client.async_get_state.side_effect = None
    mock_client.async_get_state.return_value = make_state(range=30)
    await _tick(hass, freezer)
    assert hass.states.get("sensor.elops_920e_range").state == "30.0"


async def test_auth_error_starts_reauth(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """GeocoverAuthError during polling -> ConfigEntryAuthFailed -> reauth flow."""
    await setup_integration(hass, mock_config_entry)
    mock_client.async_get_bikes.side_effect = GeocoverAuthError("refused")
    await _tick(hass, freezer)
    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]


async def test_new_bike_added(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A bike added to the account later gets its own entities."""
    await setup_integration(hass, mock_config_entry)
    mock_client.async_get_bikes.return_value = [make_bike(), make_bike(id=42, name="Second bike")]
    await _tick(hass, freezer)
    assert hass.states.get("device_tracker.second_bike") is not None
    assert hass.states.get("sensor.second_bike_battery").state == "80"


async def test_error_details_not_logged(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """pygeocover's error text can carry request headers; only the error type is logged."""
    await setup_integration(hass, mock_config_entry)
    caplog.set_level("DEBUG")
    try:
        raise OSError("Authorization: Bearer SECRET-TOKEN")
    except OSError as cause:
        error = GeocoverConnectionError(f"GET bike : {cause!r}")
        error.__cause__ = cause
    mock_client.async_get_bikes.side_effect = error
    await _tick(hass, freezer)
    mock_client.async_get_bikes.side_effect = None
    mock_client.async_get_state.side_effect = GeocoverApiError(502, "Bearer SECRET-TOKEN")
    await _tick(hass, freezer)
    assert "SECRET-TOKEN" not in caplog.text
    assert "connection error (OSError)" in caplog.text
    assert "HTTP 502" in caplog.text
