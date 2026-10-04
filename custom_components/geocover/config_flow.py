"""Config flow for Decathlon Geocover.

The Geocover app only accepts a `tech.conneq.decathlon://` redirect, so the login
runs through Decathlon's identity provider and ends on an error page whose address
carries the authorization code. The user pastes that address in the second step.
"""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

from homeassistant.config_entries import (
    SOURCE_REAUTH,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
)
from pygeocover import (
    GeocoverApiError,
    GeocoverAuthError,
    GeocoverClient,
    GeocoverConnectionError,
    GeocoverError,
    GeocoverLoginError,
    LoginRequest,
)
import voluptuous as vol

from . import GeocoverConfigEntry
from .const import (
    CONF_REDIRECT_URL,
    CONF_SCAN_INTERVAL,
    CONF_TOKENS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .coordinator import describe_error

_LOGGER = logging.getLogger(__name__)

# Start of the "Whoops!" page address the user copies (shown in the instructions)
REDIRECT_PREFIX = "https://login.ids.conneq.tech/redirect?code="


class GeocoverConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Decathlon Geocover."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        # LoginRequest.to_dict(): kept between showing the link and the paste.
        self._login: dict[str, Any] | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: GeocoverConfigEntry) -> GeocoverOptionsFlow:
        """Get the options flow."""
        return GeocoverOptionsFlow()

    def _placeholders(self) -> dict[str, str]:
        assert self._login is not None
        return {"url": self._login["url"], "redirect_prefix": REDIRECT_PREFIX}

    def _client(self) -> GeocoverClient:
        return GeocoverClient(async_get_clientsession(self.hass))

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Step 1: show the login link."""
        return await self._async_step_login_link("user", user_input)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Start a reauth when the stored tokens are rejected."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1 of reauth: show the login link."""
        return await self._async_step_login_link("reauth_confirm", user_input)

    async def _async_step_login_link(
        self, step_id: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return await self.async_step_paste()
        if self._login is None:
            try:
                request = await self._client().async_start_login()
            except GeocoverError as err:
                _LOGGER.debug("Could not start login: %s", describe_error(err))
                return self.async_abort(reason="cannot_connect")
            self._login = request.to_dict()
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema({}),
            description_placeholders=self._placeholders(),
        )

    async def async_step_paste(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Step 2: exchange the pasted redirect address for tokens."""
        assert self._login is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            request = LoginRequest.from_dict(self._login)
            pasted = user_input[CONF_REDIRECT_URL].strip()
            try:
                request.extract_code(pasted)
            except GeocoverLoginError as err:
                _LOGGER.debug("Pasted address rejected: %s", err)
                errors[CONF_REDIRECT_URL] = "invalid_url"
            else:
                client = self._client()
                try:
                    tokens = await client.async_finish_login(request, pasted)
                    user = await client.async_get_user()
                except GeocoverLoginError as err:
                    _LOGGER.debug("Login code rejected: %s", err)
                    errors["base"] = "code_rejected"
                except GeocoverAuthError:
                    errors["base"] = "invalid_auth"
                except (GeocoverConnectionError, GeocoverApiError) as err:
                    _LOGGER.debug("Login failed: %s", describe_error(err))
                    errors["base"] = "cannot_connect"
                except Exception:
                    _LOGGER.exception("Unexpected error during login")
                    errors["base"] = "unknown"
                else:
                    await self.async_set_unique_id(str(user.id))
                    data = {CONF_TOKENS: tokens.to_dict()}
                    if self.source == SOURCE_REAUTH:
                        self._abort_if_unique_id_mismatch(reason="wrong_account")
                        return self.async_update_reload_and_abort(
                            self._get_reauth_entry(), data_updates=data
                        )
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=user.name or user.email or f"Geocover {user.id}",
                        data=data,
                    )

        return self.async_show_form(
            step_id="paste",
            data_schema=vol.Schema({vol.Required(CONF_REDIRECT_URL): TextSelector()}),
            errors=errors,
            description_placeholders=self._placeholders(),
        )


class GeocoverOptionsFlow(OptionsFlowWithReload):
    """Options: polling interval. Reloads only when the options change."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(
                data={CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL])}
            )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_SCAN_INTERVAL,
                            max=MAX_SCAN_INTERVAL,
                            step=1,
                            mode=NumberSelectorMode.BOX,
                            unit_of_measurement="min",
                        )
                    ),
                }
            ),
        )
