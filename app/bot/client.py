from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
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
        await self.runtime.bot_manager.sync_commands()

    async def sync_commands(self, guild: discord.abc.Snowflake | None = None) -> dict:
        """Publish the application commands and return a result for the panel.

        Discord only shows slash commands after an explicit sync. When the
        configured guild is stale (bot re-invited, config imported, demo data)
        we fall back to every guild the bot is actually in, instead of syncing
        only to an ID that no longer exists. If the bot is not in any guild we
        register global commands, which are also available after a later join.
        """
        if not self.is_ready():
            return {"ok": False, "count": 0, "error": "Bot Discord non connesso."}

        configured_id = self.runtime.config.get()["discord"]["guild_id"]
        targets: list[discord.abc.Snowflake] = []
        if guild is not None:
            targets = [guild]
        elif configured_id:
            selected = self.get_guild(int(configured_id))
            if selected is not None:
                targets = [selected]
            elif self.guilds:
                targets = list(self.guilds)
                log.warning(
                    "La guilda configurata non è disponibile: sincronizzo i comandi nei server in cui sono presente",
                    extra={"ctx_guild_id": configured_id},
                )
        elif self.guilds:
            targets = list(self.guilds)

        available = len(self.tree.get_commands())
        if not available:
            return {
                "ok": False,
                "count": 0,
                "available": 0,
                "error": "Nessun comando caricato nel bot. Riavvia FraBot e riprova.",
            }

        try:
            if targets:
                total = 0
                synced_ids: list[str] = []
                for target in targets:
                    # `tree.sync(guild=...)` only sends commands registered for
                    # that specific guild. The commands in this bot are global,
                    # so copy them into the guild first: otherwise Discord
                    # receives an empty list and returns zero commands.
                    self.tree.clear_commands(guild=target)
                    self.tree.copy_global_to(guild=target)
                    synced = await self.tree.sync(guild=target)
                    total += len(synced)
                    target_id = int(target.id)
                    self._synced_guilds.add(target_id)
                    synced_ids.append(str(target_id))
                log.info(
                    "Comandi sincronizzati",
                    extra={"ctx_count": total, "ctx_guild_ids": ",".join(synced_ids)},
                )
                if not total:
                    return {
                        "ok": False,
                        "count": 0,
                        "available": available,
                        "scope": "guild",
                        "guild_ids": synced_ids,
                        "error": (
                            "Discord non ha registrato nessun comando. "
                            "Riprova tra poco o controlla i log del pannello."
                        ),
                    }
                return {
                    "ok": True,
                    "count": total,
                    "available": available,
                    "scope": "guild",
                    "guild_ids": synced_ids,
                }

            synced = await self.tree.sync()
            log.info("Comandi globali sincronizzati", extra={"ctx_count": len(synced)})
            return {
                "ok": True,
                "count": len(synced),
                "available": available,
                "scope": "global",
                "guild_ids": [],
            }
        except discord.Forbidden:
            log.warning(
                "Impossibile sincronizzare i comandi: manca lo scope applications.commands",
                extra={"ctx_guild_id": configured_id},
            )
            return {
                "ok": False,
                "count": 0,
                "error": (
                    "Il bot non ha lo scope applications.commands. "
                    "Reinvitalo con il link del pannello e riprova."
                ),
            }
        except app_commands.CommandSyncFailure as exc:
            log.error("Discord ha rifiutato i comandi: %s", exc)
            return {
                "ok": False,
                "count": 0,
                "error": "Discord ha rifiutato i comandi: controlla i log del pannello.",
            }
        except discord.HTTPException as exc:
            log.error("Sincronizzazione comandi fallita: %s", exc)
            return {
                "ok": False,
                "count": 0,
                "error": f"Discord ha risposto con errore {exc.status}.",
            }
        except Exception as exc:
            log.exception("Sincronizzazione comandi fallita")
            return {
                "ok": False,
                "count": 0,
                "error": f"Sincronizzazione non riuscita: {exc}",
            }

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
        # The wizard may still be open while the bot is invited. Publishing
        # the commands here makes them appear even if the admin never presses
        # the “check” button or the app restarts before syncing.
        await self.runtime.bot_manager.sync_commands(guild=guild)
