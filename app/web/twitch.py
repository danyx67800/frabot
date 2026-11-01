from __future__ import annotations

import logging
import re
import sqlite3
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request

from app.config import DEFAULT_TWITCH_TEMPLATE
from app.services.twitch_api import TwitchAuthError, TwitchClient, TwitchError
from app.services.twitch_monitor import build_announcement
from app.utils import as_bool, as_str, is_masked, snowflake_or_empty, truncate, utcnow_iso
from app.web.common import (
    bad_request,
    get_rt,
    require_guild,
    role,
    text_channel,
)

log = logging.getLogger("frabot.web.twitch")
router = APIRouter(prefix="/api/twitch", tags=["twitch"])
LOGIN_RE = re.compile(r"^[a-zA-Z0-9_]{3,25}$")


def _public(runtime) -> dict:
    cfg = runtime.config.get()
    rows = runtime.db.query("SELECT * FROM twitch_streamers ORDER BY id")
    streamers = []
    for row in rows:
        streamers.append(
            {
                "id": row["id"],
                "login": row["login"],
                "display_name": row["display_name"] or row["login"],
                "channel_id": row["channel_id"],
                "mention_type": row["mention_type"],
                "mention_role_id": row["mention_role_id"] or "",
                "template": row["template"],
                "is_live": bool(row["is_live"]),
                "not_found": bool(row["not_found"]),
                "last_checked": row["last_checked"],
                "last_validated": row["last_validated"],
                "last_error": row["last_error"],
                "stream_id": row["stream_id"],
                "message_id": row["message_id"],
                "message_channel_id": row["message_channel_id"],
                "live_started_at": row["live_started_at"],
            }
        )
    return {
        "enabled": cfg["modules"]["twitch"],
        "config": {
            "client_id": cfg["twitch"]["client_id"],
            "has_client_secret": bool(cfg["twitch"]["client_secret"]),
            "client_secret_masked": "••••••••" if cfg["twitch"]["client_secret"] else "",
            "update_on_end": cfg["twitch"]["update_on_end"],
        },
        "monitor": runtime.twitch_monitor.status(),
        "streamers": streamers,
        "default_template": DEFAULT_TWITCH_TEMPLATE,
    }


async def _test(client_id: str, secret: str) -> dict:
    candidate = {"twitch": {"client_id": client_id, "client_secret": secret}}
    client = TwitchClient(lambda: candidate)
    try:
        return await client.test_credentials()
    except TwitchAuthError as exc:
        raise bad_request(str(exc)) from exc
    except TwitchError as exc:
        raise bad_request(str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Impossibile contattare Twitch.") from exc


@router.get("")
async def get_twitch(request: Request) -> dict:
    return _public(get_rt(request))


@router.put("/config")
async def update_config(request: Request, payload: dict[str, Any] = Body(...)) -> dict:
    runtime = get_rt(request)
    cfg = runtime.config.get()
    client_id = as_str(payload.get("client_id", cfg["twitch"]["client_id"]), "", 100).strip()
    secret = as_str(payload.get("client_secret"), "", 200)
    if not secret or is_masked(secret):
        secret = cfg["twitch"]["client_secret"]
    if not client_id or not secret:
        raise bad_request("Inserisci Client ID e Client Secret di Twitch.")
    changed = client_id != cfg["twitch"]["client_id"] or secret != cfg["twitch"]["client_secret"]
    if changed:
        await _test(client_id, secret)
    cfg["twitch"]["client_id"] = client_id
    cfg["twitch"]["client_secret"] = secret
    cfg["twitch"]["update_on_end"] = as_bool(
        payload.get("update_on_end"), cfg["twitch"]["update_on_end"]
    )
    if "enabled" in payload:
        cfg["modules"]["twitch"] = as_bool(payload["enabled"], cfg["modules"]["twitch"])
    runtime.config.save(cfg)
    return _public(runtime)


@router.post("/config/test")
async def test_config(request: Request, payload: dict[str, Any] = Body(...)) -> dict:
    runtime = get_rt(request)
    cfg = runtime.config.get()
    client_id = as_str(payload.get("client_id") or cfg["twitch"]["client_id"], "", 100).strip()
    secret = as_str(payload.get("client_secret"), "", 200)
    if not secret or is_masked(secret):
        secret = cfg["twitch"]["client_secret"]
    if not client_id or not secret:
        raise bad_request("Inserisci Client ID e Client Secret di Twitch.")
    result = await _test(client_id, secret)
    return {"ok": True, **result}


@router.get("/streamers")
async def list_streamers(request: Request) -> dict:
    return {"streamers": _public(get_rt(request))["streamers"]}


@router.post("/streamers")
async def add_streamer(request: Request, payload: dict[str, Any] = Body(...)) -> dict:
    runtime = get_rt(request)
    guild = require_guild(runtime)
    cfg = runtime.config.get()
    if not cfg["twitch"]["client_id"] or not cfg["twitch"]["client_secret"]:
        raise bad_request("Configura prima le credenziali Twitch.")
    login = as_str(payload.get("login"), "", 25).lower().lstrip("@")
    if not LOGIN_RE.match(login):
        raise bad_request("Login Twitch non valido (lettere, numeri e underscore, 3-25 caratteri).")
    channel = await text_channel(guild, payload.get("channel_id"), "Canale annunci")
    mention_type = as_str(payload.get("mention_type"), "none", 10).lower()
    if mention_type not in {"none", "everyone", "role"}:
        raise bad_request("Tipo di menzione non valido.")
    mention_role_id = snowflake_or_empty(payload.get("mention_role_id"))
    if mention_type == "role":
        if not mention_role_id:
            raise bad_request("Scegli il ruolo da menzionare.")
        role(guild, mention_role_id, "Ruolo da menzionare")
    template = as_str(payload.get("template"), "", 4096)
    existing = runtime.db.one("SELECT id FROM twitch_streamers WHERE login = ?", (login,))
    if existing:
        raise HTTPException(status_code=409, detail="Questo streamer è già nell'elenco.")

    client = TwitchClient(runtime.config.get)
    try:
        users = await client.fetch_users([login])
    except TwitchAuthError as exc:
        raise bad_request(str(exc)) from exc
    except TwitchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Impossibile contattare Twitch.") from exc
    if not users:
        raise bad_request("Utente Twitch non trovato. Controlla il login.")
    user = users[0]
    canonical = str(user.get("login") or login).lower()
    try:
        streamer_id = runtime.db.execute(
            """INSERT INTO twitch_streamers(login, display_name, channel_id, mention_type,
                   mention_role_id, template, last_validated, created_at)
               VALUES(?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                canonical, user.get("display_name") or canonical, str(channel.id),
                mention_type, mention_role_id, template, utcnow_iso(), utcnow_iso(),
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Questo streamer è già nell'elenco.") from exc
    row = next((s for s in _public(runtime)["streamers"] if s["id"] == streamer_id), None)
    log.info("Streamer Twitch aggiunto", extra={"ctx_streamer": canonical})
    return {"item": row}


@router.put("/streamers/{streamer_id}")
async def update_streamer(
    request: Request, streamer_id: int, payload: dict[str, Any] = Body(...)
) -> dict:
    runtime = get_rt(request)
    guild = require_guild(runtime)
    existing = runtime.db.one("SELECT * FROM twitch_streamers WHERE id = ?", (streamer_id,))
    if not existing:
        raise HTTPException(status_code=404, detail="Streamer non trovato.")
    channel = await text_channel(
        guild, payload.get("channel_id", existing["channel_id"]), "Canale annunci"
    )
    mention_type = as_str(payload.get("mention_type"), existing["mention_type"], 10).lower()
    if mention_type not in {"none", "everyone", "role"}:
        raise bad_request("Tipo di menzione non valido.")
    mention_role_id = snowflake_or_empty(
        payload.get("mention_role_id", existing["mention_role_id"])
    )
    if mention_type == "role":
        if not mention_role_id:
            raise bad_request("Scegli il ruolo da menzionare.")
        role(guild, mention_role_id, "Ruolo da menzionare")
    template = as_str(payload.get("template"), existing["template"], 4096)
    runtime.db.execute(
        """UPDATE twitch_streamers SET channel_id = ?, mention_type = ?, mention_role_id = ?,
               template = ? WHERE id = ?""",
        (str(channel.id), mention_type, mention_role_id, template, streamer_id),
    )
    row = next((s for s in _public(runtime)["streamers"] if s["id"] == streamer_id), None)
    return {"item": row}


@router.delete("/streamers/{streamer_id}")
async def delete_streamer(request: Request, streamer_id: int) -> dict:
    runtime = get_rt(request)
    existing = runtime.db.one("SELECT id FROM twitch_streamers WHERE id = ?", (streamer_id,))
    if not existing:
        raise HTTPException(status_code=404, detail="Streamer non trovato.")
    runtime.db.execute("DELETE FROM twitch_streamers WHERE id = ?", (streamer_id,))
    return {"ok": True}


@router.post("/streamers/{streamer_id}/test")
async def test_announcement(request: Request, streamer_id: int) -> dict:
    runtime = get_rt(request)
    try:
        result = await runtime.twitch_monitor.send_test(streamer_id)
    except TwitchError as exc:
        raise bad_request(str(exc)) from exc
    return {"ok": True, "message": result}


@router.post("/preview")
async def preview(request: Request, payload: dict[str, Any] = Body(...)) -> dict:
    runtime = get_rt(request)
    streamer_id = payload.get("streamer_id")
    row = (
        runtime.db.one("SELECT * FROM twitch_streamers WHERE id = ?", (int(streamer_id),))
        if streamer_id
        else None
    )
    login = as_str(payload.get("login") or (row["login"] if row else "streamer"), "streamer", 25).lower()
    streamer = {
        "login": login or "streamer",
        "display_name": as_str(
            payload.get("display_name") or (row["display_name"] if row else login),
            login or "Streamer",
            100,
        ),
        "mention_type": as_str(payload.get("mention_type"), row["mention_type"] if row else "none", 10),
        "mention_role_id": snowflake_or_empty(
            payload.get("mention_role_id") or (row["mention_role_id"] if row else "")
        ),
        "template": as_str(payload.get("template"), row["template"] if row else "", 4096),
    }
    sample = {
        "id": "preview",
        "user_name": streamer["display_name"],
        "title": "Titolo della diretta di prova",
        "game_name": "Gioco di prova",
        "viewer_count": 128,
        "thumbnail_url": "",
    }
    content, embed = build_announcement(streamer, sample, test=True)
    return {"content": content, "embed": embed.to_dict()}
