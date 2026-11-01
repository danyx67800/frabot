from __future__ import annotations

import logging
from typing import Any

import discord
from fastapi import APIRouter, Body, HTTPException, Request

from app.services.discord_api import DiscordAPIError, verify_bot_token
from app.services.twitch_api import TwitchAuthError, TwitchClient, TwitchError
from app.utils import as_bool, as_str, is_masked, is_snowflake, snowflake_or_empty
from app.web.common import (
    REQUIRED_PERMISSIONS,
    bad_request,
    get_rt,
    invite_url,
    require_bot,
    require_guild,
    text_channel,
)

log = logging.getLogger("frabot.web.wizard")
router = APIRouter(prefix="/api/wizard", tags=["wizard"])


def _public_config(runtime) -> dict:
    cfg = runtime.config.get()
    return {
        "discord": {
            "application_id": cfg["discord"]["application_id"],
            "bot_name": cfg["discord"]["bot_name"],
            "has_bot_token": bool(cfg["discord"]["bot_token"]),
            "guild_id": cfg["discord"]["guild_id"] or "",
            "guild_name": cfg["discord"]["guild_name"] or "",
        },
        "modules": cfg["modules"],
        "tickets": {
            "panel_channel_id": cfg["tickets"]["panel_channel_id"],
            "log_channel_id": cfg["tickets"]["log_channel_id"],
            "ask_reason": cfg["tickets"]["ask_reason"],
            "max_open_per_user": cfg["tickets"]["max_open_per_user"],
            "auto_close_hours": cfg["tickets"]["auto_close_hours"],
        },
        "games_channels": sorted(
            {channel for item in cfg["games"]["items"].values() for channel in item["channels"]}
        ),
        "twitch": {
            "client_id": cfg["twitch"]["client_id"],
            "has_client_secret": bool(cfg["twitch"]["client_secret"]),
            "client_secret_masked": "••••••••" if cfg["twitch"]["client_secret"] else "",
            "update_on_end": cfg["twitch"]["update_on_end"],
        },
        "setup": {"test_channel_id": cfg["setup"]["test_channel_id"]},
    }


def _payload(runtime) -> dict:
    bot_status = runtime.bot_manager.status()
    cfg = runtime.config.get()
    return {
        "state": runtime.config.public_wizard(),
        "config": _public_config(runtime),
        "bot": bot_status,
        "guilds": bot_status.get("guilds", []),
        "invite_url": invite_url(cfg),
        "permissions": REQUIRED_PERMISSIONS.value,
        "scopes": ["bot", "applications.commands"],
        "counts": {
            "ticket_categories": runtime.db.one("SELECT COUNT(*) AS n FROM ticket_categories")["n"],
            "quiz_questions": runtime.db.one("SELECT COUNT(*) AS n FROM quiz_questions")["n"],
            "twitch_streamers": runtime.db.one("SELECT COUNT(*) AS n FROM twitch_streamers")["n"],
        },
    }


def _save_wizard(runtime, **updates) -> dict:
    wizard = runtime.config.get_wizard()
    wizard.update(updates)
    runtime.config.save_wizard(wizard)
    return runtime.config.public_wizard()


async def _sync_commands(runtime) -> dict:
    """Sync the slash commands and turn a Discord failure into a clear error.

    The wizard used to ignore the result: a bot invited without the
    `applications.commands` scope looked configured but had no commands.
    """
    result = await runtime.bot_manager.sync_commands()
    if not result.get("ok"):
        detail = result.get("error") or "Riprova tra qualche secondo."
        raise bad_request(f"Impossibile pubblicare i comandi: {detail}")
    return result


async def _test_twitch(client_id: str, client_secret: str) -> dict:
    candidate = {"twitch": {"client_id": client_id, "client_secret": client_secret}}
    client = TwitchClient(lambda: candidate)
    try:
        return await client.test_credentials()
    except TwitchAuthError as exc:
        raise bad_request(str(exc)) from exc
    except TwitchError as exc:
        raise bad_request(str(exc)) from exc
    except Exception as exc:
        log.warning("Test Twitch fallito: %s", exc.__class__.__name__)
        raise HTTPException(
            status_code=502, detail="Impossibile contattare Twitch. Controlla la connessione."
        ) from exc


@router.get("")
async def wizard_state(request: Request) -> dict:
    return _payload(get_rt(request))


@router.put("/step/{step}")
async def save_step(
    request: Request, step: int, payload: dict[str, Any] | None = Body(default=None)
) -> dict:
    runtime = get_rt(request)
    body = payload or {}
    if not 1 <= step <= 7:
        raise bad_request("Passaggio del wizard non valido.")
    cfg = runtime.config.get()
    wizard = runtime.config.get_wizard()

    if step == 1:
        _save_wizard(runtime, step=2)
        return _payload(runtime)

    if step == 2:
        application_id = snowflake_or_empty(
            body.get("application_id") or cfg["discord"]["application_id"]
        )
        token = as_str(body.get("bot_token"), "", 300)
        if token and is_masked(token):
            token = ""
        if not application_id or not is_snowflake(application_id):
            raise bad_request("Inserisci un Application ID Discord valido.")
        if token:
            try:
                info = await verify_bot_token(token, application_id)
            except DiscordAPIError as exc:
                raise bad_request(str(exc)) from exc
            except Exception:
                log.exception("Verifica Discord fallita")
                raise HTTPException(
                    status_code=502, detail="Impossibile contattare Discord. Riprova."
                )
            old_app = cfg["discord"]["application_id"]
            cfg["discord"].update(
                {
                    "application_id": info["application_id"],
                    "bot_token": token,
                    "bot_user_id": info["bot_user_id"],
                    "bot_name": info["bot_name"],
                }
            )
            if old_app and old_app != info["application_id"]:
                cfg["discord"]["guild_id"] = ""
                cfg["discord"]["guild_name"] = ""
                cfg["tickets"]["panel_message_id"] = ""
            runtime.config.save(cfg)
            await runtime.bot_manager.restart()
            _save_wizard(
                runtime, discord_verified=True, step=3, test_sent=False, twitch_verified=False
            )
            return _payload(runtime)
        if not cfg["discord"]["bot_token"] or not wizard["discord_verified"]:
            raise bad_request("Inserisci il Bot Token per verificare l'app.")
        if application_id != cfg["discord"]["application_id"]:
            raise bad_request("L'Application ID non corrisponde al token salvato.")
        if not runtime.bot_manager.is_connected:
            runtime.bot_manager.start()
        _save_wizard(runtime, step=3)
        return _payload(runtime)

    if not wizard["discord_verified"] or not cfg["discord"]["bot_token"]:
        raise bad_request("Completa prima la verifica del bot.")

    if step == 3:
        ready = await runtime.bot_manager.wait_ready(timeout=12)
        if not ready:
            status = runtime.bot_manager.status()
            if status.get("last_error"):
                raise bad_request(str(status["last_error"]))
            raise HTTPException(
                status_code=409,
                detail="Il bot si sta connettendo a Discord. Attendi qualche secondo e riprova.",
            )
        bot = require_bot(runtime)
        if not bot.guilds:
            raise bad_request(
                "Il bot non è ancora in nessun server. Usa il link di invito e riprova."
            )
        if len(bot.guilds) == 1:
            guild = bot.guilds[0]
            cfg["discord"]["guild_id"] = str(guild.id)
            cfg["discord"]["guild_name"] = guild.name
            runtime.config.save(cfg)
            await _sync_commands(runtime)
            _save_wizard(runtime, step=5)
            return {**_payload(runtime), "auto_selected": True}
        _save_wizard(runtime, step=4)
        return {**_payload(runtime), "auto_selected": False}

    if step == 4:
        guild_id = snowflake_or_empty(body.get("guild_id"))
        if not guild_id:
            raise bad_request("Scegli un server.")
        bot = require_bot(runtime)
        guild = bot.get_guild(int(guild_id))
        if not guild:
            raise bad_request("Il bot non è in quel server.")
        cfg["discord"]["guild_id"] = str(guild.id)
        cfg["discord"]["guild_name"] = guild.name
        runtime.config.save(cfg)
        await _sync_commands(runtime)
        _save_wizard(runtime, step=5)
        return _payload(runtime)

    if step == 5:
        guild = require_guild(runtime, cfg["discord"]["guild_id"] or None)
        modules = body.get("modules") if isinstance(body.get("modules"), dict) else {}
        new_modules = {
            "tickets": as_bool(modules.get("tickets"), cfg["modules"]["tickets"]),
            "games": as_bool(modules.get("games"), cfg["modules"]["games"]),
            "twitch": as_bool(modules.get("twitch"), cfg["modules"]["twitch"]),
        }
        ticket_values = body.get("tickets") if isinstance(body.get("tickets"), dict) else {}
        panel_id = snowflake_or_empty(
            ticket_values.get("panel_channel_id") or cfg["tickets"]["panel_channel_id"]
        )
        log_id = snowflake_or_empty(
            ticket_values.get("log_channel_id") or cfg["tickets"]["log_channel_id"]
        )
        if new_modules["tickets"] and not panel_id:
            raise bad_request("Scegli il canale in cui pubblicare il pannello ticket.")
        if panel_id:
            await text_channel(guild, panel_id, "Canale pannello ticket")
        if log_id:
            await text_channel(guild, log_id, "Canale log ticket")
        old_panel_id = cfg["tickets"]["panel_channel_id"]
        cfg["modules"] = new_modules
        cfg["tickets"]["panel_channel_id"] = panel_id
        cfg["tickets"]["log_channel_id"] = log_id
        if panel_id != old_panel_id:
            cfg["tickets"]["panel_message_id"] = ""
        game_channels = body.get("games_channels")
        if game_channels is None and isinstance(body.get("games"), dict):
            game_channels = body["games"].get("channels")
        clean_channels: list[str] = []
        if isinstance(game_channels, list):
            for cid in game_channels:
                channel = await text_channel(guild, cid, "Canale mini giochi")
                if str(channel.id) not in clean_channels:
                    clean_channels.append(str(channel.id))
            for item in cfg["games"]["items"].values():
                item["channels"] = clean_channels
        runtime.config.save(cfg)
        next_step = 6 if new_modules["twitch"] else 7
        _save_wizard(runtime, step=next_step)
        return _payload(runtime)

    if step == 6:
        if not cfg["modules"]["twitch"]:
            _save_wizard(runtime, step=7)
            return _payload(runtime)
        client_id = as_str(body.get("client_id") or cfg["twitch"]["client_id"], "", 100).strip()
        secret_input = as_str(body.get("client_secret"), "", 200)
        if not secret_input or is_masked(secret_input):
            secret_input = cfg["twitch"]["client_secret"]
        if not client_id or not secret_input:
            raise bad_request("Inserisci Client ID e Client Secret di Twitch.")
        result = await _test_twitch(client_id, secret_input)
        cfg["twitch"]["client_id"] = client_id
        cfg["twitch"]["client_secret"] = secret_input
        cfg["twitch"]["update_on_end"] = as_bool(
            body.get("update_on_end"), cfg["twitch"]["update_on_end"]
        )
        runtime.config.save(cfg)
        _save_wizard(runtime, twitch_verified=True, step=7)
        return {**_payload(runtime), "twitch_test": result}

    # step 7
    wizard = runtime.config.get_wizard()
    _save_wizard(runtime, step=7)
    return _payload(runtime)


@router.post("/twitch/test")
async def test_twitch(request: Request, payload: dict[str, Any] = Body(...)) -> dict:
    runtime = get_rt(request)
    cfg = runtime.config.get()
    client_id = as_str(payload.get("client_id") or cfg["twitch"]["client_id"], "", 100).strip()
    secret = as_str(payload.get("client_secret"), "", 200)
    if not secret or is_masked(secret):
        secret = cfg["twitch"]["client_secret"]
    if not client_id or not secret:
        raise bad_request("Inserisci Client ID e Client Secret di Twitch.")
    return await _test_twitch(client_id, secret)


@router.post("/test-message")
async def send_test_message(request: Request, payload: dict[str, Any] = Body(...)) -> dict:
    runtime = get_rt(request)
    guild = require_guild(runtime)
    channel = await text_channel(guild, payload.get("channel_id"), "Canale messaggio di prova")
    bot = require_bot(runtime)
    cog = bot.get_cog("Tickets")
    if not cog:
        raise HTTPException(status_code=409, detail="Il bot è ancora in avvio. Riprova.")
    try:
        result = await cog.send_test_message(str(channel.id))
    except Exception as exc:
        from app.bot.cogs.tickets import TicketError

        if isinstance(exc, TicketError):
            raise bad_request(str(exc)) from exc
        raise HTTPException(status_code=502, detail=f"Invio non riuscito: {exc}") from exc
    cfg = runtime.config.get()
    cfg["setup"]["test_channel_id"] = str(channel.id)
    runtime.config.save(cfg)
    _save_wizard(runtime, test_sent=True, step=7)
    return {"message": result, "wizard": runtime.config.public_wizard()}


@router.post("/complete")
async def complete(request: Request) -> dict:
    runtime = get_rt(request)
    cfg = runtime.config.get()
    wizard = runtime.config.get_wizard()
    if not wizard["discord_verified"] or not cfg["discord"]["bot_token"]:
        raise bad_request("Verifica prima il Bot Token.")
    if not cfg["discord"]["guild_id"]:
        raise bad_request("Scegli il server Discord.")
    if cfg["modules"]["tickets"] and not cfg["tickets"]["panel_channel_id"]:
        raise bad_request("Scegli il canale del pannello ticket.")
    if cfg["modules"]["twitch"]:
        if not cfg["twitch"]["client_id"] or not cfg["twitch"]["client_secret"]:
            raise bad_request("Configura Twitch prima di completare.")
        if not wizard["twitch_verified"]:
            raise bad_request("Esegui il test di autenticazione Twitch.")
    if not wizard["test_sent"]:
        raise bad_request("Invia il messaggio di prova nel canale scelto.")
    await _sync_commands(runtime)
    _save_wizard(runtime, completed=True, step=7)
    log.info("Configurazione guidata completata")
    return _payload(runtime)


@router.post("/restart")
async def restart(request: Request) -> dict:
    runtime = get_rt(request)
    _save_wizard(runtime, completed=False, step=1, test_sent=False)
    log.info("Wizard rilanciato dal pannello")
    return _payload(runtime)


@router.post("/sync-commands")
async def sync_commands(request: Request) -> dict:
    runtime = get_rt(request)
    result = await _sync_commands(runtime)
    return result
