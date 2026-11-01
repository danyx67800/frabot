from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import aiohttp

log = logging.getLogger("frabot.twitch")

TOKEN_URL = "https://id.twitch.tv/oauth2/token"
HELIX = "https://api.twitch.tv/helix"


class TwitchError(Exception):
    pass


class TwitchAuthError(TwitchError):
    pass


class TwitchRateLimited(TwitchError):
    def __init__(self, wait_seconds: float) -> None:
        super().__init__("Twitch ha limitato le richieste.")
        self.wait_seconds = wait_seconds


class TwitchClient:
    """Minimal Helix client using the client-credentials app token."""

    def __init__(self, config_getter) -> None:
        self._config_getter = config_getter
        self._token: str | None = None
        self._token_expires: float = 0
        self._token_client_id: str | None = None

    def credentials(self) -> tuple[str, str]:
        cfg = self._config_getter()["twitch"]
        client_id = (cfg.get("client_id") or "").strip()
        client_secret = (cfg.get("client_secret") or "").strip()
        if not client_id or not client_secret:
            raise TwitchAuthError("Client ID o Client Secret Twitch mancanti.")
        return client_id, client_secret

    async def _fetch_token(self) -> None:
        client_id, client_secret = self.credentials()
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                TOKEN_URL,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "grant_type": "client_credentials",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            ) as resp:
                body = await resp.json(content_type=None)
                if resp.status != 200:
                    message = body.get("message") if isinstance(body, dict) else None
                    raise TwitchAuthError(
                        f"Autenticazione Twitch fallita ({resp.status})"
                        + (f": {message}" if message else ".")
                    )
                token = body.get("access_token")
                if not token:
                    raise TwitchAuthError("Twitch non ha restituito un token.")
                self._token = token
                self._token_client_id = client_id
                # Refresh a minute early to avoid races.
                self._token_expires = time.time() + int(body.get("expires_in", 3600)) - 60

    async def token(self, force: bool = False) -> str:
        client_id, _ = self.credentials()
        if (
            force
            or not self._token
            or self._token_client_id != client_id
            or time.time() >= self._token_expires
        ):
            await self._fetch_token()
        assert self._token
        return self._token

    def _parse_ratelimit_wait(self, headers: aiohttp.typedefs.LooseHeaders) -> float:
        reset = headers.get("Ratelimit-Reset")
        if reset:
            try:
                return max(1.0, float(reset) - time.time())
            except ValueError:
                pass
        return 5.0

    async def _get(self, path: str, params: list[tuple[str, str]]) -> dict[str, Any]:
        client_id, _ = self.credentials()
        token = await self.token()
        timeout = aiohttp.ClientTimeout(total=25)
        headers = {"Client-Id": client_id, "Authorization": f"Bearer {token}"}
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(HELIX + path, params=params, headers=headers) as resp:
                if resp.status == 401:
                    token = await self.token(force=True)
                    headers["Authorization"] = f"Bearer {token}"
                    async with session.get(HELIX + path, params=params, headers=headers) as retry:
                        return await self._handle(retry)
                return await self._handle(resp)

    async def _handle(self, resp: aiohttp.ClientResponse) -> dict[str, Any]:
        if resp.status == 429:
            wait = self._parse_ratelimit_wait(resp.headers)
            raise TwitchRateLimited(wait)
        if resp.status >= 400:
            body = await resp.text()
            log.warning("Helix %s ha risposto %s: %s", resp.url.path, resp.status, body[:200])
            raise TwitchError(f"Twitch ha risposto con errore {resp.status}.")
        return await resp.json(content_type=None)

    async def fetch_users(self, logins: list[str]) -> list[dict]:
        results: list[dict] = []
        for chunk in _chunks(logins, 100):
            params = [("login", login) for login in chunk]
            data = await self._get("/users", params)
            results.extend(data.get("data", []))
        return results

    async def fetch_streams(self, logins: list[str]) -> list[dict]:
        results: list[dict] = []
        for chunk in _chunks(logins, 100):
            params = [("user_login", login) for login in chunk]
            params.append(("first", "100"))
            data = await self._get("/streams", params)
            results.extend(data.get("data", []))
        return results

    async def test_credentials(self) -> dict:
        """Fetch a token and make one real Helix call."""
        client_id, _ = self.credentials()
        token = await self.token(force=True)
        data = await self._get("/streams", [("first", "1")])
        return {
            "client_id": client_id,
            "token_type": "app",
            "streams_returned": len(data.get("data", [])),
        }


def _chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[i : i + size] for i in range(0, len(values), size)]


def thumbnail(url: str, width: int = 640, height: int = 360) -> str:
    """Twitch returns a URL with a {width}x{height} placeholder."""
    if not url:
        return ""
    return url.replace("{width}", str(width)).replace("{height}", str(height))
