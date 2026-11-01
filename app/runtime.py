from __future__ import annotations

import logging
from pathlib import Path

from app import __version__
from app.bot.manager import BotManager
from app.config import ConfigManager
from app.db import Database
from app.logging_setup import LogBuffer
from app.services.twitch_monitor import TwitchMonitor
from app.utils import utcnow

log = logging.getLogger("frabot.runtime")


class Runtime:
    def __init__(self, data_dir: Path, logs: LogBuffer) -> None:
        self.data_dir = data_dir
        self.transcripts_dir = data_dir / "transcripts"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.transcripts_dir.mkdir(parents=True, exist_ok=True)
        self.logs = logs
        self.db = Database(data_dir / "frabot.db")
        self.db.init()
        self.config = ConfigManager(self.db)
        self.started_at = utcnow()
        self.bot_manager = BotManager(self)
        self.twitch_monitor = TwitchMonitor(self)

    async def start(self) -> None:
        log.info("Avvio di FraBot", extra={"ctx_version": __version__})
        self.bot_manager.start()
        self.twitch_monitor.start()

    async def shutdown(self) -> None:
        log.info("Arresto di FraBot")
        await self.twitch_monitor.stop()
        await self.bot_manager.stop()

    def uptime_seconds(self) -> int:
        return int((utcnow() - self.started_at).total_seconds())

    def status(self) -> dict:
        cfg = self.config.get()
        bot = self.bot_manager.status()
        guild_id = cfg["discord"]["guild_id"]
        guild_name = cfg["discord"].get("guild_name") or bot.get("guild_name")
        return {
            "version": __version__,
            "started_at": self.started_at.isoformat(timespec="seconds"),
            "uptime_seconds": self.uptime_seconds(),
            "database": self.db.healthcheck(),
            "bot": bot,
            "twitch": self.twitch_monitor.status(),
            "modules": cfg["modules"],
            "guild": {"id": guild_id or None, "name": guild_name or None},
            "wizard": self.config.public_wizard(),
            "embed_color": cfg["ui"]["embed_color"],
        }
