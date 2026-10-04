"""The Decathlon Geocover integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pygeocover import GeocoverClient, TokenSet

from .const import CONF_TOKENS
from .coordinator import GeocoverCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.DEVICE_TRACKER,
    Platform.SENSOR,
]

type GeocoverConfigEntry = ConfigEntry[GeocoverCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: GeocoverConfigEntry) -> bool:
    """Set up Decathlon Geocover from a config entry."""
    # The refresh token rotates and is single use: every refresh must be written to
    # the config entry immediately, or the next restart needs a new login.
    current_refresh_token = entry.data[CONF_TOKENS]["refresh_token"]

    @callback
    def _async_store_tokens(tokens: TokenSet) -> None:
        nonlocal current_refresh_token
        if entry.data[CONF_TOKENS]["refresh_token"] != current_refresh_token:
            # A reauth replaced the tokens while this client was still running;
            # don't overwrite the newer chain with the old one.
            _LOGGER.debug("Discarding tokens from a superseded session")
            return
        current_refresh_token = tokens.refresh_token
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_TOKENS: tokens.to_dict()}
        )
        _LOGGER.debug("Stored rotated Geocover tokens")

    client = GeocoverClient(
        async_get_clientsession(hass),
        TokenSet.from_dict(entry.data[CONF_TOKENS]),
        on_tokens_updated=_async_store_tokens,
    )
    coordinator = GeocoverCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GeocoverConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
