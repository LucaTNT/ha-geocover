"""Run the integration inside a real Home Assistant core against the live API.

Not part of the test suite. Everything lives in .live/ha (git-ignored):

  python scripts/live_ha.py flow     # config flow: prints the login link, then waits for
                                     # the pasted address in .live/paste.txt
  python scripts/live_ha.py run [N]  # boot HA (a restart, every time), print entity states,
                                     # force N token refreshes, stop HA (flushes storage)

Coordinates are rounded away in the output; tokens are only shown as short hashes.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path
import sys

import aiohttp
from homeassistant import bootstrap, config_entries, loader
from homeassistant.core import HomeAssistant
from homeassistant.helpers import aiohttp_client
from homeassistant.setup import async_setup_component

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / ".live" / "ha"
PASTE = ROOT / ".live" / "paste.txt"

if os.environ.get("HTTPS_PROXY"):
    # Sandboxed dev machine: let HA's aiohttp session use the egress proxy.
    _orig_init = aiohttp.ClientSession.__init__

    def _init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs.setdefault("trust_env", True)
        _orig_init(self, *args, **kwargs)

    aiohttp.ClientSession.__init__ = _init  # type: ignore[method-assign]


class _Resolver(aiohttp.ThreadedResolver):
    async def real_close(self) -> None:
        await self.close()


# HA's mDNS-aware resolver needs the zeroconf integration, which this minimal core
# doesn't load; plain system DNS is enough for the Geocover hosts.
aiohttp_client._async_make_resolver = lambda hass: _Resolver()  # type: ignore[assignment]


def _h(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:8]


def _token_summary(hass: HomeAssistant) -> str:
    entries = hass.config_entries.async_entries("geocover")
    if not entries:
        return "no entry"
    tokens = entries[0].data["tokens"]
    return f"refresh={_h(tokens['refresh_token'])} access={_h(tokens['access_token'])}"


async def _boot() -> HomeAssistant:
    """A minimal real HA core: registries, config entries and storage on disk.

    No HTTP server or default integrations (they need a bindable port and extra
    requirements), but config entries are loaded and set up exactly as in HA.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    link = CONFIG_DIR / "custom_components"
    if not link.exists():
        link.symlink_to(ROOT / "custom_components")
    hass = HomeAssistant(str(CONFIG_DIR))
    hass.config.skip_pip = True
    hass.config_entries = config_entries.ConfigEntries(hass, {})
    loader.async_setup(hass)
    await bootstrap.async_load_base_functionality(hass)
    await async_setup_component(hass, "homeassistant", {})
    await hass.async_start()
    for entry in hass.config_entries.async_entries():
        await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return hass


async def flow() -> None:
    hass = await _boot()
    try:
        result = await hass.config_entries.flow.async_init("geocover", context={"source": "user"})
        print("LOGIN URL:", result["description_placeholders"]["url"], flush=True)
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        PASTE.unlink(missing_ok=True)
        print(f"waiting for {PASTE} ...", flush=True)
        while not PASTE.exists():
            await asyncio.sleep(1)
        pasted = PASTE.read_text().strip()
        PASTE.unlink()
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"redirect_url": pasted}
        )
        print("FLOW RESULT:", result["type"], result.get("errors") or result.get("reason") or "")
        await hass.async_block_till_done()
        print("tokens:", _token_summary(hass))
    finally:
        await hass.async_stop()


def _print_states(hass: HomeAssistant) -> None:
    for state in sorted(hass.states.async_all(), key=lambda s: s.entity_id):
        if state.domain not in ("sensor", "binary_sensor", "device_tracker"):
            continue
        attrs = {
            k: v
            for k, v in state.attributes.items()
            if k not in ("latitude", "longitude", "friendly_name", "icon", "entity_picture")
        }
        if "latitude" in state.attributes:
            attrs["has_coordinates"] = state.attributes["latitude"] is not None
        print(f"  {state.entity_id} = {state.state}  {json.dumps(attrs, default=str)}")


async def run(refreshes: int) -> None:
    hass = await _boot()
    try:
        entry = hass.config_entries.async_entries("geocover")[0]
        print("entry state:", entry.state, "| tokens at boot:", _token_summary(hass))
        _print_states(hass)
        coordinator = entry.runtime_data
        for n in range(refreshes):
            await coordinator.client.async_refresh_tokens(force=True)
            await coordinator.async_refresh()
            print(
                f"refresh {n + 1}: update ok={coordinator.last_update_success} "
                f"| stored {_token_summary(hass)}"
            )
    finally:
        await hass.async_stop()
    print("stopped; storage flushed")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    # debug for the integration and library; pygeocover never logs tokens
    logging.getLogger("custom_components.geocover").setLevel(logging.DEBUG)
    logging.getLogger("pygeocover").setLevel(logging.DEBUG)
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "flow":
        asyncio.run(flow())
    elif cmd == "run":
        asyncio.run(run(int(sys.argv[2]) if len(sys.argv) > 2 else 0))
    else:
        sys.exit(__doc__)
