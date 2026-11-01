from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import discord

from app.config import DEFAULT_TWITCH_TEMPLATE
from app.services.twitch_api import (
    TwitchAuthError,
    TwitchClient,
    TwitchError,
    TwitchRateLimited,
    thumbnail,
)
from app.utils import render_template, truncate, utcnow, utcnow_iso

if TYPE_CHECKING:
    from app.runtime import Runtime

log = logging.getLogger("frabot.twitch")

POLL_SECONDS = 60
VALIDATE_SECONDS = 6 * 60 * 60
TWITCH_COLOR = 0x9146FF


def _viewers(value) -> str:
    try:
        return f"{int(value):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "0"


def build_announcement(
    streamer: dict, stream: dict, test: bool = False
) -> tuple[str, discord.Embed]:
    login = str(streamer["login"])
    display = streamer.get("display_name") or stream.get("user_name") or login
    variables = {
        "streamer": display,
        "titolo": stream.get("title") or "Senza titolo",
        "gioco": stream.get("game_name") or "—",
        "url": f"https://twitch.tv/{login}",
        "viewers": _viewers(stream.get("viewer_count", 0)),
    }
    template = streamer.get("template") or DEFAULT_TWITCH_TEMPLATE
    description = truncate(render_template(template, variables), 4096)
    embed = discord.Embed(
        title=truncate(f"🔴 {display} è live", 256),
        url=f"https://twitch.tv/{login}",
        description=description,
        color=discord.Color(TWITCH_COLOR),
        timestamp=utcnow(),
    )
    thumb = thumbnail(stream.get("thumbnail_url") or "")
    if thumb:
        embed.set_thumbnail(url=thumb)
    embed.set_footer(text="Annuncio di prova · FraBot" if test else "Twitch · FraBot")

    mention_type = streamer.get("mention_type") or "none"
    role_id = streamer.get("mention_role_id")
    if mention_type == "everyone":
        content = "@everyone"
    elif mention_type == "role" and role_id:
        content = f"<@&{role_id}>"
    else:
        content = ""
    return content, embed


class TwitchMonitor:
    def __init__(self, runtime: "Runtime") -> None:
        self.runtime = runtime
        self.client = TwitchClient(runtime.config.get)
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self.last_run: str | None = None
        self.last_error: str | None = None

    @property
    def running(self) -> bool:
        return bool(self._task and not self._task.done())

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="frabot-twitch")

    async def stop(self) -> None:
        self._stop.set()
        task = self._task
        self._task = None
        if task and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    async def _loop(self) -> None:
        # Give the Discord gateway a moment to become ready.
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=10)
            return
        except asyncio.TimeoutError:
            pass
        while not self._stop.is_set():
            try:
                await self.run_once()
            except TwitchRateLimited as exc:
                wait = min(max(exc.wait_seconds, 1), 60)
                self.last_error = f"Rate limit Twitch, nuovo tentativo tra {int(wait)}s."
                log.warning(self.last_error)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=wait)
                    return
                except asyncio.TimeoutError:
                    continue
            except TwitchAuthError as exc:
                self.last_error = str(exc)
                log.error("Twitch: %s", exc)
            except TwitchError as exc:
                self.last_error = str(exc)
                log.warning("Twitch: %s", exc)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = f"Errore imprevisto: {exc.__class__.__name__}"
                log.exception("Errore nel polling Twitch")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=POLL_SECONDS)
            except asyncio.TimeoutError:
                pass

    async def run_once(self) -> None:
        cfg = self.runtime.config.get()
        if not cfg["modules"]["twitch"]:
            return
        if not cfg["twitch"]["client_id"] or not cfg["twitch"]["client_secret"]:
            return
        streamers = self.runtime.db.query("SELECT * FROM twitch_streamers ORDER BY id")
        if not streamers:
            return
        await self._validate_users(streamers)
        streamers = self.runtime.db.query("SELECT * FROM twitch_streamers ORDER BY id")
        logins = [str(row["login"]).lower() for row in streamers]
        try:
            streams = await self.client.fetch_streams(logins)
        except TwitchRateLimited:
            raise
        except (TwitchAuthError, TwitchError) as exc:
            self.last_error = str(exc)
            self.last_run = utcnow_iso()
            error = truncate(str(exc), 250)
            self.runtime.db.execute(
                "UPDATE twitch_streamers SET last_checked = ?, last_error = ?",
                (self.last_run, error),
            )
            raise
        live_by_login = {str(s.get("user_login", "")).lower(): s for s in streams}
        now = utcnow_iso()
        for streamer in streamers:
            login = str(streamer["login"]).lower()
            stream = live_by_login.get(login)
            if stream:
                await self._handle_live(streamer, stream, now)
            else:
                await self._handle_offline(streamer, now)
        self.last_run = now
        self.last_error = None

    async def _validate_users(self, streamers: list[dict]) -> None:
        """Twitch omits offline channels from /streams, so detect renamed or
        deleted accounts with an occasional /users call (not every minute)."""
        from datetime import datetime, timedelta, timezone

        cutoff = (utcnow() - timedelta(seconds=VALIDATE_SECONDS)).isoformat(timespec="seconds")
        due = [s for s in streamers if not s.get("last_validated") or s["last_validated"] < cutoff]
        if not due:
            return
        logins = [str(row["login"]) for row in due]
        try:
            users = await self.client.fetch_users(logins)
        except (TwitchAuthError, TwitchError) as exc:
            log.warning("Validazione utenti Twitch non riuscita: %s", exc)
            return
        by_login = {str(u.get("login", "")).lower(): u for u in users}
        now = utcnow_iso()
        for row in due:
            user = by_login.get(str(row["login"]).lower())
            if user:
                self.runtime.db.execute(
                    """UPDATE twitch_streamers SET display_name = ?, not_found = 0,
                           last_validated = ?, last_error = NULL WHERE id = ?""",
                    (user.get("display_name") or row["login"], now, row["id"]),
                )
            else:
                self.runtime.db.execute(
                    """UPDATE twitch_streamers SET not_found = 1, last_validated = ?,
                           last_error = 'Utente Twitch non trovato' WHERE id = ?""",
                    (now, row["id"]),
                )

    async def _handle_live(self, streamer: dict, stream: dict, now: str) -> None:
        stream_id = str(stream.get("id") or "")
        is_new_stream = str(streamer.get("stream_id") or "") != stream_id
        was_live = bool(streamer.get("is_live"))
        if is_new_stream:
            self.runtime.db.execute(
                """UPDATE twitch_streamers SET is_live = 1, stream_id = ?, live_started_at = ?,
                       announced = 0, last_checked = ?, last_error = NULL, not_found = 0
                   WHERE id = ?""",
                (stream_id, stream.get("started_at"), now, streamer["id"]),
            )
        elif not was_live:
            self.runtime.db.execute(
                """UPDATE twitch_streamers SET is_live = 1, last_checked = ?,
                       last_error = NULL, not_found = 0 WHERE id = ?""",
                (now, streamer["id"]),
            )
        else:
            self.runtime.db.execute(
                "UPDATE twitch_streamers SET last_checked = ?, last_error = NULL WHERE id = ?",
                (now, streamer["id"]),
            )

        fresh = self.runtime.db.one(
            "SELECT * FROM twitch_streamers WHERE id = ?", (streamer["id"],)
        )
        if not fresh or fresh["announced"]:
            return
        try:
            message = await self._send_announcement(fresh, stream, test=False)
        except TwitchError as exc:
            self.runtime.db.execute(
                "UPDATE twitch_streamers SET last_error = ? WHERE id = ?",
                (truncate(str(exc), 250), streamer["id"]),
            )
            log.warning("Annuncio Twitch non inviato per %s: %s", streamer["login"], exc)
            return
        self.runtime.db.execute(
            """UPDATE twitch_streamers SET announced = 1, message_id = ?,
                   message_channel_id = ?, last_error = NULL WHERE id = ?""",
            (str(message.id), str(message.channel.id), streamer["id"]),
        )
        log.info(
            "Annuncio live inviato",
            extra={"ctx_streamer": streamer["login"], "ctx_stream_id": stream_id},
        )

    async def _handle_offline(self, streamer: dict, now: str) -> None:
        was_live = bool(streamer.get("is_live"))
        self.runtime.db.execute(
            """UPDATE twitch_streamers SET is_live = 0, live_started_at = NULL,
                   last_checked = ?,
                   last_error = CASE WHEN not_found = 1 THEN last_error ELSE NULL END
               WHERE id = ?""",
            (now, streamer["id"]),
        )
        if not was_live:
            return
        cfg = self.runtime.config.get()
        if not cfg["twitch"]["update_on_end"]:
            return
        if not streamer.get("message_id") or not streamer.get("message_channel_id"):
            return
        await self._edit_offline_message(streamer)
        log.info("Annuncio Twitch aggiornato a fine stream", extra={"ctx_streamer": streamer["login"]})

    async def _edit_offline_message(self, streamer: dict) -> None:
        bot = self.runtime.bot_manager.bot
        if not bot or not bot.is_ready():
            return
        channel = bot.get_channel(int(streamer["message_channel_id"]))
        if channel is None:
            try:
                channel = await bot.fetch_channel(int(streamer["message_channel_id"]))
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return
        if not isinstance(channel, discord.TextChannel):
            return
        try:
            message = await channel.fetch_message(int(streamer["message_id"]))
            embed = message.embeds[0] if message.embeds else discord.Embed()
            embed.color = discord.Color.dark_gray()
            embed.set_footer(text="Stream terminato · Twitch · FraBot")
            await message.edit(embed=embed)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            log.info("Messaggio live non più modificabile", extra={"ctx_streamer": streamer["login"]})

    async def _send_announcement(
        self, streamer: dict, stream: dict, test: bool
    ) -> discord.Message:
        bot = self.runtime.bot_manager.bot
        if not bot or not bot.is_ready():
            raise TwitchError("Bot Discord non connesso.")
        channel = bot.get_channel(int(streamer["channel_id"]))
        if channel is None:
            try:
                channel = await bot.fetch_channel(int(streamer["channel_id"]))
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                raise TwitchError("Canale di annuncio non trovato.")
        if not isinstance(channel, discord.TextChannel):
            raise TwitchError("Il canale di annuncio non è un canale testuale.")
        content, embed = build_announcement(streamer, stream, test=test)
        try:
            return await channel.send(
                content=content or None,
                embed=embed,
                allowed_mentions=discord.AllowedMentions(
                    everyone=(streamer.get("mention_type") == "everyone"),
                    roles=(streamer.get("mention_type") == "role"),
                    users=False,
                ),
            )
        except discord.Forbidden:
            raise TwitchError("Non ho i permessi per scrivere nel canale di annuncio.")
        except discord.HTTPException as exc:
            raise TwitchError(f"Invio dell'annuncio fallito ({exc.status}).")

    async def send_test(self, streamer_id: int) -> dict:
        streamer = self.runtime.db.one(
            "SELECT * FROM twitch_streamers WHERE id = ?", (streamer_id,)
        )
        if not streamer:
            raise TwitchError("Streamer non trovato.")
        sample = {
            "id": "test",
            "user_name": streamer["display_name"] or streamer["login"],
            "title": "Titolo di prova: benvenuti in stream!",
            "game_name": "Gioco di prova",
            "viewer_count": 42,
            "thumbnail_url": "",
        }
        message = await self._send_announcement(streamer, sample, test=True)
        return {"message_id": str(message.id), "url": message.jump_url}

    def status(self) -> dict:
        cfg = self.runtime.config.get()
        rows = self.runtime.db.query(
            "SELECT is_live, last_error, not_found FROM twitch_streamers"
        )
        configured = bool(cfg["twitch"]["client_id"] and cfg["twitch"]["client_secret"])
        return {
            "enabled": cfg["modules"]["twitch"],
            "configured": configured,
            # The task idles while the module is disabled; report what the
            # panel can actually expect (active polling) instead of the task.
            "running": bool(self.running and cfg["modules"]["twitch"] and configured),
            "poll_seconds": POLL_SECONDS,
            "last_run": self.last_run,
            "last_error": self.last_error,
            "live": sum(1 for r in rows if r["is_live"]),
            "total": len(rows),
            "errors": sum(1 for r in rows if r["last_error"]),
        }
