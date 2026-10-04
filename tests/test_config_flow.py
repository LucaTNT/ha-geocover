"""Tests for the Decathlon Geocover config flow."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pygeocover import (
    GeocoverConnectionError,
    GeocoverLoginError,
    LoginRequest,
    User,
)
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.geocover.const import (
    CONF_REDIRECT_URL,
    CONF_SCAN_INTERVAL,
    CONF_TOKENS,
    DOMAIN,
)

from .conftest import USER_ID, setup_integration


@pytest.fixture(autouse=True)
def mock_setup_entry():
    """Don't set up the integration after the flow creates the entry."""
    with patch("custom_components.geocover.async_setup_entry", return_value=True) as mock:
        yield mock


def redirect_url(request: LoginRequest, code: str = "EUkwvIDc") -> str:
    """The address of the "Whoops!" page for a login request."""
    return f"https://login.ids.conneq.tech/redirect?code={code}&state={request.state}"


async def _start(hass: HomeAssistant) -> dict:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "paste"
    return result


async def test_full_flow(
    hass: HomeAssistant, mock_client: MagicMock, login_request: LoginRequest
) -> None:
    """Login link, paste, entry created with tokens and the user id."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["description_placeholders"]["url"] == login_request.url

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "paste"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_REDIRECT_URL: f"  {redirect_url(login_request)}\n"}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Luca"
    assert result["result"].unique_id == str(USER_ID)
    tokens = result["data"][CONF_TOKENS]
    assert tokens["access_token"] == "new-access"
    assert tokens["refresh_token"] == "new-refresh"

    # The LoginRequest from step 1 is the one used to finish the login.
    request, pasted = mock_client.async_finish_login.call_args.args
    assert request == login_request
    assert pasted == redirect_url(login_request)
    mock_client.async_start_login.assert_awaited_once()


@pytest.mark.parametrize(
    "pasted",
    [
        "https://login.ids.conneq.tech/redirect",  # browser hid the query string
        "https://login.ids.conneq.tech/redirect?state=abc",
        "https://login.ids.conneq.tech/redirect?code=X&state=from-another-login",
        "not a url",
    ],
)
async def test_bad_pasted_url(
    hass: HomeAssistant, mock_client: MagicMock, login_request: LoginRequest, pasted: str
) -> None:
    """A pasted address without a usable code is rejected before calling the API."""
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_REDIRECT_URL: pasted}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_REDIRECT_URL: "invalid_url"}
    mock_client.async_finish_login.assert_not_awaited()

    # The user can still finish with the right address.
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_REDIRECT_URL: redirect_url(login_request)}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.parametrize(
    ("side_effect", "error"),
    [
        (GeocoverLoginError("expired"), "code_rejected"),
        (GeocoverConnectionError("down"), "cannot_connect"),
        (RuntimeError("boom"), "unknown"),
    ],
)
async def test_finish_login_errors(
    hass: HomeAssistant,
    mock_client: MagicMock,
    login_request: LoginRequest,
    side_effect: Exception,
    error: str,
) -> None:
    """An expired code (or other failure) shows an error and lets the user retry."""
    result = await _start(hass)
    mock_client.async_finish_login.side_effect = side_effect
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_REDIRECT_URL: redirect_url(login_request)}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}
    # The login link stays available to start over with the same request.
    assert result["description_placeholders"]["url"] == login_request.url

    mock_client.async_finish_login.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_REDIRECT_URL: redirect_url(login_request, "fresh")}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_start_login_cannot_connect(hass: HomeAssistant, mock_client: MagicMock) -> None:
    """The login service being down aborts the flow."""
    mock_client.async_start_login.side_effect = GeocoverConnectionError("down")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


async def test_already_configured(
    hass: HomeAssistant,
    mock_client: MagicMock,
    login_request: LoginRequest,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The same Decathlon account can't be added twice."""
    mock_config_entry.add_to_hass(hass)
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_REDIRECT_URL: redirect_url(login_request)}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert mock_config_entry.data[CONF_TOKENS]["refresh_token"] == "old-refresh"


async def test_reauth(
    hass: HomeAssistant,
    mock_client: MagicMock,
    login_request: LoginRequest,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Reauth uses the same two steps and replaces the tokens."""
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    assert result["description_placeholders"]["url"] == login_request.url

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "paste"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_REDIRECT_URL: redirect_url(login_request)}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data[CONF_TOKENS]["refresh_token"] == "new-refresh"


async def test_reauth_wrong_account(
    hass: HomeAssistant,
    mock_client: MagicMock,
    login_request: LoginRequest,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Reauth with another Decathlon account is refused and keeps the old tokens."""
    mock_config_entry.add_to_hass(hass)
    mock_client.async_get_user.return_value = User.from_dict({"id": 1, "username": "other"})
    result = await mock_config_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_REDIRECT_URL: redirect_url(login_request)}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"
    assert mock_config_entry.data[CONF_TOKENS]["refresh_token"] == "old-refresh"


async def test_options_flow(
    hass: HomeAssistant,
    mock_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    mock_setup_entry,
) -> None:
    """The polling interval can be changed, which reloads the entry."""
    await setup_integration(hass, mock_config_entry)
    assert mock_setup_entry.call_count == 1

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 2.0}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options == {CONF_SCAN_INTERVAL: 2}
    assert mock_setup_entry.call_count == 2


async def test_options_flow_minimum(
    hass: HomeAssistant, mock_client: MagicMock, mock_config_entry: MockConfigEntry
) -> None:
    """Less than one minute is refused."""
    await setup_integration(hass, mock_config_entry)
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    with pytest.raises(Exception):  # noqa: B017 - voluptuous error wrapped by the flow manager
        await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_SCAN_INTERVAL: 0.5}
        )
