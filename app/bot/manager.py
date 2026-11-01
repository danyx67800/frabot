from __future__ import annotations

import asyncio
import logging
import contextlib
from typing import TYPE_CHECKING

import discord

from app.bot.client import FraBot
from app.utils import utcnow

if TYPE_CHECKING:
    from app.runtime import Runtime

log = logging.getLogger("frabot.bot")


class BotManager:
    """Owns the Discord client lifecycle and restarts it on token changes.

    discord.py already reconnects the gateway; this supervisor additionally
    retries a failed startup (network down, DNS, etc.) with backoff.
    """

    def __init__(self, runtime: "Runtime") -> None:
        self.runtime = runtime
        self._task: asyncio.Task | None = None
        self._bot: FraBot | None = None
        self._stop = asyncio.Event()
        self._lock = asyncio.Lock()
        self.last_error: str | None = None
        self.started_at = None
        self.connected_at = None

    @property
    def bot(self) -> FraBot | None:
        return self._bot

    @property
    def is_connected(self) -> bool:
        return bool(self._bot and self._bot.is_ready())

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        if not self.runtime.config.get()["discord"]["bot_token"]:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="frabot-discord")

    async def _run(self) -> None:
        delays = [15, 30, 60, 120, 300]
        attempt = 0
        while not self._stop.is_set():
            token = self.runtime.config.get()["discord"]["bot_token"]
            if not token:
                log.info("Nessun token configurato: bot in attesa")
                return
            bot = FraBot(self.runtime)
            self._bot = bot
            self.started_at = self.started_at or utcnow()
            failure = None
            try:
                log.info("Connessione a Discord in corso")
                await bot.start(token)
            except asyncio.CancelledError:
                raise
            except discord.LoginFailure:
                failure = "Token Discord non valido. Aggiornalo dalle impostazioni."
                log.error("Token Discord rifiutato da Discord")
            except discord.PrivilegedIntentsRequired:
                failure = "Discord richiede un intent privilegiato non abilitato."
                log.error(failure)
            except Exception as exc:  # network errors, DNS, Cloudflare...
                failure = f"Connessione a Discord non riuscita: {exc.__class__.__name__}"
                log.warning("Connessione a Discord non riuscita: %s", exc)
            finally:
                self._bot = None
                self.connected_at = None
                with contextlib.suppress(Exception):
                    if not bot.is_closed():
                        await bot.close()
            if self._stop.is_set():
                break
            self.last_error = failure
            wait = delays[min(attempt, len(delays) - 1)]
            if failure and "Token" in failure:
                wait = 300  # useless to hammer Discord with a rejected token
            attempt += 1
            log.info("Nuovo tentativo di connessione tra %s secondi", wait)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=wait)
            except asyncio.TimeoutError:
                pass

    async def stop(self) -> None:
        self._stop.set()
        bot = self._bot
        if bot and not bot.is_closed():
            with contextlib.suppress(Exception):
                await bot.close()
        task = self._task
        self._task = None
        if task and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._bot = None

    async def restart(self) -> None:
        async with self._lock:
            await self.stop()
            self.last_error = None
            self.started_at = utcnow()
            self.start()

    async def sync_commands(self) -> bool:
        if self._bot and self._bot.is_ready():
            return await self._bot.sync_commands()
        return False

    async def wait_ready(self, timeout: float = 10.0) -> bool:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if self.is_connected:
                return True
            await asyncio.sleep(0.25)
        return self.is_connected

    def status(self) -> dict:
        bot = self._bot
        connected = self.is_connected
        guilds = []
        if bot and connected:
            guilds = [
                {
                    "id": str(guild.id),
                    "name": guild.name,
                    "member_count": guild.member_count,
                    "icon_url": str(guild.icon.url) if guild.icon else None,
                }
                for guild in bot.guilds
            ]
        latency = None
        if bot and connected:
            latency = round(bot.latency * 1000) if bot.latency == bot.latency else None
        uptime = None
        if connected and self.connected_at:
            uptime = int((utcnow() - self.connected_at).total_seconds())
        cfg = self.runtime.config.get()["discord"]
        selected = cfg["guild_id"]
        selected_name = next((g["name"] for g in guilds if g["id"] == selected), None)
        return {
            "configured": bool(cfg["bot_token"]),
            "connected": connected,
            "starting": bool(self._task and not self._task.done() and not connected),
            "user": str(bot.user) if bot and bot.user else cfg["bot_name"] or None,
            "user_id": str(bot.user.id) if bot and bot.user else cfg["bot_user_id"] or None,
            "application_id": cfg["application_id"],
            "latency_ms": latency,
            "uptime_seconds": uptime,
            "guild_count": len(guilds),
            "guilds": guilds,
            "guild_id": selected or None,
            "guild_name": selected_name,
            "last_error": self.last_error,
        }

    def mark_connected(self) -> None:
        if not self.connected_at:
            self.connected_at = utcnow()
