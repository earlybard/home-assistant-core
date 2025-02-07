"""Test config flow for Twitch."""

from unittest.mock import patch

import pytest

from homeassistant.components.twitch.const import (
    CONF_CHANNELS,
    DOMAIN,
    OAUTH2_AUTHORIZE,
)
from homeassistant.config_entries import SOURCE_IMPORT, SOURCE_REAUTH, SOURCE_USER
from homeassistant.const import CONF_CLIENT_ID, CONF_CLIENT_SECRET, CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult, FlowResultType
from homeassistant.helpers import config_entry_oauth2_flow, issue_registry as ir

from . import setup_integration

from tests.common import MockConfigEntry
from tests.components.twitch import TwitchInvalidTokenMock, TwitchMock
from tests.components.twitch.conftest import CLIENT_ID, TITLE
from tests.typing import ClientSessionGenerator


async def _do_get_token(
    hass: HomeAssistant,
    result: FlowResult,
    hass_client_no_auth: ClientSessionGenerator,
    scopes: list[str],
) -> None:
    state = config_entry_oauth2_flow._encode_jwt(
        hass,
        {
            "flow_id": result["flow_id"],
            "redirect_uri": "https://example.com/auth/external/callback",
        },
    )

    assert result["url"] == (
        f"{OAUTH2_AUTHORIZE}?response_type=code&client_id={CLIENT_ID}"
        "&redirect_uri=https://example.com/auth/external/callback"
        f"&state={state}&scope={'+'.join(scopes)}"
    )

    client = await hass_client_no_auth()
    resp = await client.get(f"/auth/external/callback?code=abcd&state={state}")
    assert resp.status == 200
    assert resp.headers["content-type"] == "text/html; charset=utf-8"


async def test_full_flow(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    current_request_with_host: None,
    mock_setup_entry,
    twitch: TwitchMock,
    scopes: list[str],
) -> None:
    """Check full flow."""
    result = await hass.config_entries.flow.async_init(
        "twitch", context={"source": SOURCE_USER}
    )
    await _do_get_token(hass, result, hass_client_no_auth, scopes)

    result = await hass.config_entries.flow.async_configure(result["flow_id"])

    assert len(hass.config_entries.async_entries(DOMAIN)) == 1

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "channel123"
    assert "result" in result
    assert "token" in result["result"].data
    assert result["result"].data["token"]["access_token"] == "mock-access-token"
    assert result["result"].data["token"]["refresh_token"] == "mock-refresh-token"
    assert result["result"].unique_id == "123"
    assert result["options"] == {CONF_CHANNELS: ["internetofthings", "homeassistant"]}


async def test_already_configured(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    current_request_with_host: None,
    config_entry: MockConfigEntry,
    mock_setup_entry,
    twitch: TwitchMock,
    scopes: list[str],
) -> None:
    """Check flow aborts when account already configured."""
    await setup_integration(hass, config_entry)
    result = await hass.config_entries.flow.async_init(
        "twitch", context={"source": SOURCE_USER}
    )
    await _do_get_token(hass, result, hass_client_no_auth, scopes)

    with patch(
        "homeassistant.components.twitch.config_flow.Twitch", return_value=TwitchMock()
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"])

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "already_configured"


async def test_reauth(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    current_request_with_host: None,
    config_entry: MockConfigEntry,
    mock_setup_entry,
    twitch: TwitchMock,
    scopes: list[str],
) -> None:
    """Check reauth flow."""
    await setup_integration(hass, config_entry)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": SOURCE_REAUTH,
            "entry_id": config_entry.entry_id,
        },
        data=config_entry.data,
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    await _do_get_token(hass, result, hass_client_no_auth, scopes)

    result = await hass.config_entries.flow.async_configure(result["flow_id"])

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"


async def test_reauth_from_import(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    current_request_with_host: None,
    mock_setup_entry,
    twitch: TwitchMock,
    expires_at,
    scopes: list[str],
) -> None:
    """Check reauth flow."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title=TITLE,
        unique_id="123",
        data={
            "auth_implementation": DOMAIN,
            "token": {
                "access_token": "mock-access-token",
                "refresh_token": "mock-refresh-token",
                "expires_at": expires_at,
                "scope": " ".join(scopes),
            },
            "imported": True,
        },
        options={"channels": ["internetofthings"]},
    )
    await test_reauth(
        hass,
        hass_client_no_auth,
        current_request_with_host,
        config_entry,
        mock_setup_entry,
        twitch,
        scopes,
    )
    entries = hass.config_entries.async_entries(DOMAIN)
    entry = entries[0]
    assert "imported" not in entry.data
    assert entry.options == {CONF_CHANNELS: ["internetofthings", "homeassistant"]}


async def test_reauth_wrong_account(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    current_request_with_host: None,
    config_entry: MockConfigEntry,
    mock_setup_entry,
    twitch: TwitchMock,
    scopes: list[str],
) -> None:
    """Check reauth flow."""
    await setup_integration(hass, config_entry)
    twitch.different_user_id = True
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": SOURCE_REAUTH,
            "entry_id": config_entry.entry_id,
        },
        data=config_entry.data,
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    await _do_get_token(hass, result, hass_client_no_auth, scopes)

    result = await hass.config_entries.flow.async_configure(result["flow_id"])

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"


async def test_import(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    current_request_with_host: None,
    mock_setup_entry,
    twitch: TwitchMock,
) -> None:
    """Test import flow."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": SOURCE_IMPORT,
        },
        data={
            "platform": "twitch",
            CONF_CLIENT_ID: "1234",
            CONF_CLIENT_SECRET: "abcd",
            CONF_TOKEN: "efgh",
            "channels": ["channel123"],
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "channel123"
    assert "result" in result
    assert "token" in result["result"].data
    assert result["result"].data["token"]["access_token"] == "efgh"
    assert result["result"].data["token"]["refresh_token"] == ""
    assert result["result"].unique_id == "123"
    assert result["options"] == {CONF_CHANNELS: ["channel123"]}


@pytest.mark.parametrize("twitch_mock", [TwitchInvalidTokenMock()])
async def test_import_invalid_token(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    current_request_with_host: None,
    mock_setup_entry,
    twitch: TwitchMock,
) -> None:
    """Test import flow."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": SOURCE_IMPORT,
        },
        data={
            "platform": "twitch",
            CONF_CLIENT_ID: "1234",
            CONF_CLIENT_SECRET: "abcd",
            CONF_TOKEN: "efgh",
            "channels": ["channel123"],
        },
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "invalid_token"
    issue_registry = ir.async_get(hass)
    assert len(issue_registry.issues) == 1


async def test_import_already_imported(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    current_request_with_host: None,
    config_entry: MockConfigEntry,
    mock_setup_entry,
    twitch: TwitchMock,
) -> None:
    """Test import flow where the config is already imported."""
    await setup_integration(hass, config_entry)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": SOURCE_IMPORT,
        },
        data={
            "platform": "twitch",
            CONF_CLIENT_ID: "1234",
            CONF_CLIENT_SECRET: "abcd",
            CONF_TOKEN: "efgh",
            "channels": ["channel123"],
        },
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    issue_registry = ir.async_get(hass)
    assert len(issue_registry.issues) == 1
