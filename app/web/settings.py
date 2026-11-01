from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import discord
from fastapi import APIRouter, Body, HTTPException, Request, Response

from app.services.config_io import ConfigError, export_bundle, import_bundle, reset_all
from app.services.discord_api import DiscordAPIError, verify_bot_token
from app.services.twitch_api import TwitchAuthError, TwitchClient, TwitchError
from app.utils import as_bool, as_int, as_str, is_masked, is_snowflake, snowflake_or_empty
from app.web.common import (
    REQUIRED_PERMISSIONS,
    bad_request,
    get_rt,
    invite_url,
    optional_guild,
    snowflake,
    text_channel,
)

log = logging.getLogger("frabot.web.settings")
router = APIRouter(prefix="/api/settings", tags=["settings"])


def _settings_payload(runtime) -> dict:
    return {
        "config": runtime.config.public(),
        "invite_url": invite_url(runtime.config.get()),
        "permissions": REQUIRED_PERMISSIONS.value,
        "commands": runtime.bot_manager.last_sync,
    }


@router.get("")
async def get_settings(request: Request) -> dict:
    return _settings_payload(get_rt(request))


@router.put("/ui")
async def update_ui(request: Request, payload: dict[str, Any] = Body(...)) -> dict:
    runtime = get_rt(request)
    cfg = runtime.config.get()
    cfg["ui"]["embed_color"] = as_str(payload.get("embed_color"), cfg["ui"]["embed_color"], 7)
    runtime.config.save(cfg)
    return _settings_payload(runtime)


@router.put("/modules")
async def update_modules(request: Request, payload: dict[str, Any] = Body(...)) -> dict:
    runtime = get_rt(request)
    cfg = runtime.config.get()
    modules = cfg["modules"]
    for key in ("tickets", "games", "twitch"):
        modules[key] = as_bool(payload.get(key), modules[key])
    if modules["twitch"] and not (cfg["twitch"]["client_id"] and cfg["twitch"]["client_secret"]):
        raise bad_request("Configura le credenziali Twitch prima di attivare il modulo.")
    runtime.config.save(cfg)
    # Enabling the games module is a natural moment to retry a failed sync,
    # especially on installations configured before the commands existed.
    commands = await runtime.bot_manager.sync_commands()
    return {**_settings_payload(runtime), "commands": commands}


@router.put("/tickets")
async def update_tickets(request: Request, payload: dict[str, Any] = Body(...)) -> dict:
    runtime = get_rt(request)
    cfg = runtime.config.get()
    guild = optional_guild(runtime)
    old_panel = cfg["tickets"]["panel_channel_id"]
    old_message = cfg["tickets"]["panel_message_id"]

    panel_id = snowflake_or_empty(payload.get("panel_channel_id", old_panel))
    log_id = snowflake_or_empty(payload.get("log_channel_id", cfg["tickets"]["log_channel_id"]))
    if guild:
        if panel_id:
            await text_channel(guild, panel_id, "Canale pannello ticket")
        if log_id:
            await text_channel(guild, log_id, "Canale log ticket")
    else:
        if panel_id:
            snowflake(panel_id, "Canale pannello ticket")
        if log_id:
            snowflake(log_id, "Canale log ticket")

    if panel_id != old_panel and old_message and guild:
        old_channel = guild.get_channel(int(old_panel)) if old_panel else None
        if isinstance(old_channel, discord.TextChannel):
            try:
                message = await old_channel.fetch_message(int(old_message))
                await message.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

    cfg["tickets"]["panel_channel_id"] = panel_id
    cfg["tickets"]["log_channel_id"] = log_id
    cfg["tickets"]["max_open_per_user"] = as_int(
        payload.get("max_open_per_user", cfg["tickets"]["max_open_per_user"]),
        cfg["tickets"]["max_open_per_user"], minimum=1, maximum=10,
    )
    cfg["tickets"]["auto_close_hours"] = as_int(
        payload.get("auto_close_hours", cfg["tickets"]["auto_close_hours"]),
        cfg["tickets"]["auto_close_hours"], minimum=0, maximum=720,
    )
    cfg["tickets"]["ask_reason"] = as_bool(
        payload.get("ask_reason"), cfg["tickets"]["ask_reason"]
    )
    if panel_id != old_panel:
        cfg["tickets"]["panel_message_id"] = ""
    runtime.config.save(cfg)
    return _settings_payload(runtime)


@router.put("/discord-token")
async def update_discord_token(request: Request, payload: dict[str, Any] = Body(...)) -> dict:
    runtime = get_rt(request)
    cfg = runtime.config.get()
    token = as_str(payload.get("bot_token"), "", 300)
    if not token or is_masked(token):
        raise bad_request("Inserisci un nuovo Bot Token.")
    application_id = snowflake_or_empty(
        payload.get("application_id") or cfg["discord"]["application_id"]
    )
    if not application_id:
        raise bad_request("Inserisci l'Application ID.")
    try:
        info = await verify_bot_token(token, application_id)
    except DiscordAPIError as exc:
        raise bad_request(str(exc)) from exc
    except Exception:
        log.exception("Verifica del nuovo token fallita")
        raise HTTPException(status_code=502, detail="Impossibile contattare Discord. Riprova.")

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
    wizard = runtime.config.get_wizard()
    wizard["discord_verified"] = True
    runtime.config.save_wizard(wizard)
    await runtime.bot_manager.restart()
    return {**_settings_payload(runtime), "bot": runtime.bot_manager.status()}


@router.put("/twitch")
async def update_twitch(request: Request, payload: dict[str, Any] = Body(...)) -> dict:
    runtime = get_rt(request)
    cfg = runtime.config.get()
    client_id = as_str(payload.get("client_id", cfg["twitch"]["client_id"]), "", 100).strip()
    secret = as_str(payload.get("client_secret"), "", 200)
    if not secret or is_masked(secret):
        secret = cfg["twitch"]["client_secret"]
    if not client_id or not secret:
        raise bad_request("Inserisci Client ID e Client Secret di Twitch.")
    candidate = {"twitch": {"client_id": client_id, "client_secret": secret}}
    client = TwitchClient(lambda: candidate)
    try:
        await client.test_credentials()
    except TwitchAuthError as exc:
        raise bad_request(str(exc)) from exc
    except TwitchError as exc:
        raise bad_request(str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail="Impossibile contattare Twitch."
        ) from exc
    cfg["twitch"]["client_id"] = client_id
    cfg["twitch"]["client_secret"] = secret
    cfg["twitch"]["update_on_end"] = as_bool(
        payload.get("update_on_end"), cfg["twitch"]["update_on_end"]
    )
    runtime.config.save(cfg)
    result = _settings_payload(runtime)
    result["twitch_verified"] = True
    return result


@router.get("/export")
async def export_config(request: Request) -> Response:
    runtime = get_rt(request)
    bundle = export_bundle(runtime)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    filename = f"frabot-config-{stamp}.json"
    return Response(
        content=json.dumps(bundle, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/import")
async def import_config(request: Request, payload: dict[str, Any] = Body(...)) -> dict:
    runtime = get_rt(request)
    try:
        counts = import_bundle(runtime, payload)
    except ConfigError as exc:
        raise bad_request(str(exc)) from exc
    return {"ok": True, **counts, "config": runtime.config.public()}


@router.post("/reset")
async def reset(request: Request, payload: dict[str, Any] = Body(...)) -> dict:
    runtime = get_rt(request)
    if str(payload.get("confirm", "")) != "RESET":
        raise bad_request('Per azzerare la configurazione scrivi "RESET".')
    reset_all(runtime)
    await runtime.bot_manager.restart()
    return {"ok": True, "status": runtime.status()}
