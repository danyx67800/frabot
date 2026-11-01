from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from app.utils import utcnow

if TYPE_CHECKING:
    from app.runtime import Runtime

log = logging.getLogger("frabot.bot")


class FraBot(commands.Bot):
    """Discord client.

    Intents are deliberately minimal: `guilds` (channels/roles cache) and
    `guild_messages` (only to timestamp ticket activity). Message Content is
    never requested; all user input arrives through interactions.
    """

    def __init__(self, runtime: "Runtime") -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_messages = True
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            help_command=None,
            # Never ping by default: user-provided ticket text must not be able
            # to turn a welcome message into an @everyone mention. Commands
            # that need a ping opt in explicitly.
            allowed_mentions=discord.AllowedMentions.none(),
            activity=discord.Game(name="FraBot · /tris"),
        )
        self.runtime = runtime
        self.ready_at = None
        self._synced_guilds: set[int] = set()

    async def setup_hook(self) -> None:
        await self.load_extension("app.bot.cogs.tickets")
        await self.load_extension("app.bot.cogs.games")
        self.tree.on_error = self.on_app_command_error
        log.info("Estensioni del bot caricate")

    async def on_ready(self) -> None:
        self.ready_at = self.ready_at or utcnow()
        self.runtime.bot_manager.mark_connected()
        self.runtime.bot_manager.last_error = None
        log.info(
            "Bot connesso",
            extra={
                "ctx_user": str(self.user),
                "ctx_guilds": len(self.guilds),
                "ctx_guild_id": self.runtime.config.get()["discord"]["guild_id"],
            },
        )
        await self.sync_commands()

    async def sync_commands(self) -> bool:
        guild_id = self.runtime.config.get()["discord"]["guild_id"]
        if not guild_id or not self.is_ready():
            return False
        guild = discord.Object(id=int(guild_id))
        try:
            synced = await self.tree.sync(guild=guild)
            self._synced_guilds.add(int(guild_id))
            log.info("Comandi sincronizzati", extra={"ctx_count": len(synced), "ctx_guild_id": guild_id})
            return True
        except discord.Forbidden:
            log.warning(
                "Impossibile sincronizzare i comandi: manca lo scope applications.commands",
                extra={"ctx_guild_id": guild_id},
            )
        except Exception as exc:
            log.error("Sincronizzazione comandi fallita: %s", exc)
        return False

    async def on_app_command_error(
        self, interaction: discord.Interaction, error: Exception
    ) -> None:
        original = getattr(error, "original", error)
        log.error(
            "Errore comando %s: %s",
            getattr(interaction.command, "qualified_name", "?"),
            original,
            exc_info=not isinstance(original, discord.HTTPException),
        )
        message = "Si è verificato un errore. Riprova tra poco."
        if isinstance(original, discord.Forbidden):
            message = "Non ho i permessi necessari in questo canale."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            pass

    async def on_guild_join(self, guild: discord.Guild) -> None:
        log.info(
            "Bot aggiunto a un server",
            extra={"ctx_guild_id": str(guild.id), "ctx_guild": guild.name},
        )
