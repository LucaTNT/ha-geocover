"""Diagnostics for Decathlon Geocover."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import GeocoverConfigEntry
from .const import CONF_TOKENS

TO_REDACT = {
    CONF_TOKENS,
    "access_token",
    "refresh_token",
    "imei",
    "lat",
    "lon",
    "latitude",
    "longitude",
    # bike payload: BLE pairing secret, activation/invite codes, frame number
    "blepass",
    "blename",
    "activation_code",
    "invite_code",
    "invite_code_uri",
    "frame_number",
    # account details (also nested in bike.owning_user)
    "name",
    "username",
    "user_name",
    "display_name",
    "first_name",
    "last_name",
    "email",
    "conneqtech_id",
    "address",
    "city",
    "postal_code",
    "house_number",
    "phone_number",
    "phone_number_formatted",
    "avatar_url",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: GeocoverConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    bikes: dict[str, Any] = {}
    for bike_id, data in (coordinator.data or {}).items():
        bikes[str(bike_id)] = async_redact_data(
            {
                "bike": data.bike.raw,
                "state": asdict(data.state) if data.state else None,
                "health": data.health.raw if data.health else None,
                "battery": asdict(data.battery) if data.battery else None,
                "latest_ride": asdict(data.latest_ride) if data.latest_ride else None,
                "rides_fetched_at": data.rides_fetched_at,
            },
            TO_REDACT,
        )
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "last_update_success": coordinator.last_update_success,
        "bikes": bikes,
    }
