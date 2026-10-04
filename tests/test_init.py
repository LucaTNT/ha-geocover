"""Tests for setup, token persistence and entities."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pygeocover import (
    GeocoverAuthError,
    GeocoverConnectionError,
    TokenSet,
)
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.geocover.const import CONF_TOKENS, DOMAIN

from .conftest import BIKE_ID, make_battery, make_bike, setup_integration


async def test_setup_and_unload(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """The entry sets up with the stored tokens and unloads cleanly."""
    await setup_integration(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert mock_client.init_tokens.refresh_token == "old-refresh"

    await hass.config_entries.async_unload(mock_config_entry.entry_id)
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED


async def test_token_rotation_is_persisted(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """Every rotated token set is written to the entry at once, without a reload."""
    await setup_integration(hass, mock_config_entry)
    store_tokens = mock_client.init_kwargs["on_tokens_updated"]

    with patch.object(hass.config_entries, "async_reload") as mock_reload:
        for n in range(1, 4):
            store_tokens(TokenSet(f"access-{n}", f"refresh-{n}", 1000.0 * n))
            assert mock_config_entry.data[CONF_TOKENS] == {
                "access_token": f"access-{n}",
                "refresh_token": f"refresh-{n}",
                "expires_at": 1000.0 * n,
            }
        await hass.async_block_till_done()
    mock_reload.assert_not_called()
    assert mock_config_entry.state is ConfigEntryState.LOADED

    # After a restart the client starts from the last stored refresh token.
    await hass.config_entries.async_reload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_client.init_tokens.refresh_token == "refresh-3"


async def test_tokens_from_superseded_session_are_ignored(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """A client still running after a reauth can't overwrite the new tokens."""
    await setup_integration(hass, mock_config_entry)
    store_tokens = mock_client.init_kwargs["on_tokens_updated"]
    hass.config_entries.async_update_entry(
        mock_config_entry,
        data={CONF_TOKENS: {"access_token": "a", "refresh_token": "from-reauth", "expires_at": 1}},
    )
    store_tokens(TokenSet("stale", "stale", 2.0))
    assert mock_config_entry.data[CONF_TOKENS]["refresh_token"] == "from-reauth"


async def test_tokens_never_logged(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Token values don't end up in the log."""
    caplog.set_level("DEBUG")
    await setup_integration(hass, mock_config_entry)
    mock_client.init_kwargs["on_tokens_updated"](TokenSet("acc-SECRET", "ref-SECRET", 1.0))
    assert "SECRET" not in caplog.text
    assert "old-refresh" not in caplog.text


async def test_setup_auth_error_starts_reauth(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """Rejected tokens put the entry in error and start a reauth flow."""
    mock_client.async_get_bikes.side_effect = GeocoverAuthError("refresh token refused")
    await setup_integration(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert len(flows) == 1
    assert flows[0]["context"]["source"] == SOURCE_REAUTH
    assert flows[0]["context"]["entry_id"] == mock_config_entry.entry_id


async def test_setup_connection_error_retries(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """A transient error retries setup later."""
    mock_client.async_get_bikes.side_effect = GeocoverConnectionError("timeout")
    await setup_integration(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_entities(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    device_registry: dr.DeviceRegistry,
) -> None:
    """One device per bike, with the expected entity states."""
    await setup_integration(hass, mock_config_entry)

    device = device_registry.async_get_device_by_identifier(
        (DOMAIN, str(BIKE_ID)), mock_config_entry.entry_id
    )
    assert device is not None
    assert device.name == "Elops 920E"
    assert device.manufacturer == "Decathlon"

    tracker = hass.states.get("device_tracker.elops_920e")
    assert tracker.state == "not_home"
    assert tracker.attributes["latitude"] == 45.4642
    assert tracker.attributes["longitude"] == 9.19
    assert tracker.attributes["speed"] == 12
    assert tracker.attributes["fix_time"] == "2026-10-04T10:14:04+00:00"
    assert tracker.attributes["source_type"] == "gps"

    def state(entity_id: str) -> str:
        return hass.states.get(entity_id).state

    assert state("sensor.elops_920e_battery") == "80"
    assert state("sensor.elops_920e_range") == "42.0"
    assert state("sensor.elops_920e_odometer") == "1234.6"
    assert state("sensor.elops_920e_speed") == "12.0"
    assert state("sensor.elops_920e_last_ride_distance") == "15.23"
    assert state("sensor.elops_920e_last_ride_duration") == "40.0"
    assert state("sensor.elops_920e_last_ride_average_speed") == "22.8"
    assert state("sensor.elops_920e_last_ride_elevation_gain") == "120"
    ride = hass.states.get("sensor.elops_920e_last_ride_distance")
    assert ride.attributes["start_time"].isoformat() == "2026-10-03T16:00:00+00:00"
    assert ride.attributes["end_time"].isoformat() == "2026-10-03T16:45:00+00:00"

    assert state("binary_sensor.elops_920e_moving") == STATE_ON
    assert state("binary_sensor.elops_920e_ride_in_progress") == STATE_OFF
    assert state("binary_sensor.elops_920e_stolen") == STATE_OFF
    assert state("binary_sensor.elops_920e_charging") == STATE_OFF
    assert state("binary_sensor.elops_920e_power") == STATE_ON
    # LOCK device class: off = locked
    assert state("binary_sensor.elops_920e_ecu_lock") == STATE_OFF

    # Diagnostic entities
    for entity_id, expected in (
        ("sensor.elops_920e_tracker_battery", "43"),
        ("sensor.elops_920e_last_gps_fix", "2026-10-04T10:14:04+00:00"),
        ("sensor.elops_920e_last_connection", "2026-10-04T10:16:42+00:00"),
    ):
        assert state(entity_id) == expected
        assert entity_registry.async_get(entity_id).entity_category == "diagnostic"

    # CO₂ unit is undocumented: disabled by default
    co2 = entity_registry.async_get("sensor.elops_920e_last_ride_co2")
    assert co2.disabled_by is er.RegistryEntryDisabler.INTEGRATION


async def test_battery_zero_from_bike_list_is_unknown(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """`GET bike` reports 0% before the battery ever reported; show unknown, not 0."""
    mock_client.async_get_bikes.return_value = [make_bike(battery_percentage=0)]
    await setup_integration(hass, mock_config_entry)
    assert hass.states.get("sensor.elops_920e_battery").state == STATE_UNKNOWN


async def test_battery_zero_trusted_with_battery_timestamp(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """A 0% is real once the battery endpoint has a last update time."""
    mock_client.async_get_bikes.return_value = [make_bike(battery_percentage=0)]
    mock_client.async_get_battery.return_value = make_battery(
        last_battery_update="2026-10-04T10:00:00+0000"
    )
    await setup_integration(hass, mock_config_entry)
    assert hass.states.get("sensor.elops_920e_battery").state == "0"


async def test_no_rides_and_no_location(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """A brand-new bike without rides or a fix still sets up."""
    mock_client.async_get_bikes.return_value = [make_bike(last_location=None)]
    mock_client.async_get_latest_ride.return_value = None
    mock_client.async_get_state.return_value = None
    await setup_integration(hass, mock_config_entry)
    assert hass.states.get("sensor.elops_920e_last_ride_distance").state == STATE_UNKNOWN
    assert hass.states.get("binary_sensor.elops_920e_moving").state == STATE_UNKNOWN
    assert hass.states.get("binary_sensor.elops_920e_power").state == STATE_UNKNOWN
    assert hass.states.get("device_tracker.elops_920e").state == STATE_UNKNOWN
