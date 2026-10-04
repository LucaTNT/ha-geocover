"""Manual live check against the real Geocover API (not part of the test suite).

  python scripts/live_probe.py login-url          # prints the login URL
  python scripts/live_probe.py login-finish URL   # exchanges the pasted redirect URL
  python scripts/live_probe.py dump               # dumps raw JSON of every read endpoint

Tokens are kept in .live/tokens.json (git-ignored). Never commit or share that file.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import sys

import aiohttp
from pygeocover import GeocoverClient, LoginRequest, TokenSet

STATE = Path(__file__).resolve().parent.parent / ".live"
TOKENS = STATE / "tokens.json"
PENDING = STATE / "pending_login.json"


def _write(path: Path, data: dict) -> None:
    STATE.mkdir(exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def _save_tokens(tokens: TokenSet) -> None:
    _write(TOKENS, tokens.to_dict())
    print("[tokens rotated and saved]", file=sys.stderr)


async def main(cmd: str, arg: str | None) -> None:
    async with aiohttp.ClientSession(trust_env=True) as session:
        tokens = TokenSet.from_dict(json.loads(TOKENS.read_text())) if TOKENS.exists() else None
        client = GeocoverClient(session, tokens, on_tokens_updated=_save_tokens)
        if cmd == "login-url":
            req = await client.async_start_login()
            _write(PENDING, req.to_dict())
            print(req.url)
        elif cmd == "login-finish":
            req = LoginRequest.from_dict(json.loads(PENDING.read_text()))
            await client.async_finish_login(req, arg or "")
            PENDING.unlink()
            print("logged in")
        elif cmd == "refresh":
            await client.async_refresh_tokens(force=True)
            print("refreshed, expires_at", client.tokens.expires_at)
        elif cmd == "dump":
            out: dict = {"user/me": await client._api("user/me")}
            bikes = await client._api("bike")
            out["bike"] = bikes
            now = datetime.now(UTC)
            for bike in bikes or []:
                bid = bike["id"]
                for path in ("state", "health", "battery/current-state", "geofence"):
                    try:
                        out[f"bike/{bid}/{path}"] = await client._api(f"bike/{bid}/{path}")
                    except Exception as err:
                        out[f"bike/{bid}/{path}"] = repr(err)
                out[f"bike/{bid}/location"] = await client._api(
                    f"bike/{bid}/location",
                    {
                        "from": (now - timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%S%z"),
                        "till": now.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    },
                )
                out[f"v2/bike/{bid}/ride"] = await client._api(
                    f"v2/bike/{bid}/ride", {"limit": 2, "offset": 0, "order": "start_date;desc"}
                )
            print(json.dumps(out, indent=2, ensure_ascii=False))
        else:
            sys.exit(__doc__)


if __name__ == "__main__":
    asyncio.run(
        main(sys.argv[1] if len(sys.argv) > 1 else "", sys.argv[2] if len(sys.argv) > 2 else None)
    )
