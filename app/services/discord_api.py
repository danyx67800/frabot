from __future__ import annotations

import logging

import aiohttp

log = logging.getLogger("frabot.discordapi")

API = "https://discord.com/api/v10"
USER_AGENT = "DiscordBot (https://github.com/frabot/frabot, 1.0.2)"


class DiscordAPIError(Exception):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


async def _get(session: aiohttp.ClientSession, path: str, token: str) -> dict:
    async with session.get(
        API + path,
        headers={"Authorization": f"Bot {token}", "User-Agent": USER_AGENT},
    ) as resp:
        if resp.status == 401:
            raise DiscordAPIError("Il Bot Token non è valido o è stato revocato.", 401)
        if resp.status == 403:
            raise DiscordAPIError("Discord ha negato l'accesso con questo token.", 403)
        if resp.status == 429:
            raise DiscordAPIError("Discord sta limitando le richieste. Riprova tra poco.", 429)
        if resp.status >= 400:
            body = await resp.text()
            log.warning("Discord API %s ha risposto %s: %s", path, resp.status, body[:200])
            raise DiscordAPIError(
                f"Discord ha risposto con errore {resp.status}.", resp.status
            )
        return await resp.json()


async def verify_bot_token(token: str, application_id: str) -> dict:
    """Verify token and that it belongs to the pasted Application ID."""
    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        me = await _get(session, "/users/@me", token)
        if not me.get("bot"):
            raise DiscordAPIError("Questo token non appartiene a un bot.")
        app = await _get(session, "/applications/@me", token)
    real_id = str(app.get("id", ""))
    if not real_id:
        raise DiscordAPIError("Discord non ha restituito l'Application ID del bot.")
    if real_id != application_id:
        raise DiscordAPIError(
            f"L'Application ID non corrisponde al token: il token appartiene all'app {real_id}."
        )
    return {
        "application_id": real_id,
        "bot_user_id": str(me.get("id", "")),
        "bot_name": me.get("username") or app.get("name") or "Bot",
        "application_name": app.get("name") or me.get("username") or "",
    }
