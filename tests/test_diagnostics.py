"""Tests for Geocover diagnostics."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from homeassistant.core import HomeAssistant
from homeassistant.helpers.json import ExtendedJSONEncoder
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.geocover.diagnostics import async_get_config_entry_diagnostics

from .conftest import setup_integration

REDACTED = "**REDACTED**"


async def test_diagnostics_redacted(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """Tokens, IMEI, coordinates and other secrets are redacted."""
    await setup_integration(hass, mock_config_entry)
    diag = await async_get_config_entry_diagnostics(hass, mock_config_entry)
    text = json.dumps(diag, cls=ExtendedJSONEncoder)

    for secret in (
        "old-access",
        "old-refresh",
        "123456789012345",  # IMEI
        "45.4642",
        "9.19",
        "secret-ble-pass",
        "ACTCODE",
        "FRAME123",
        "luca@example.invalid",
        "Home to Work",  # ride names can contain places
    ):
        assert secret not in text, secret

    assert diag["entry"]["data"]["tokens"] == REDACTED
    bike = diag["bikes"]["30058"]["bike"]
    assert bike["imei"] == REDACTED
    assert bike["last_location"]["lat"] == REDACTED
    assert bike["last_location"]["lon"] == REDACTED
    assert bike["last_location"]["speed"] == 12
    assert bike["battery_percentage"] == 80
    assert diag["bikes"]["30058"]["state"]["range_km"] == 42
