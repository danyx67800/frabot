from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import discord
from fastapi import APIRouter, Body, HTTPException, Request

from app.bot.cogs.tickets import TicketError
from app.utils import as_str, snowflake_or_empty
from app.web.common import (
    bad_request,
    category_channel,
    get_rt,
    optional_guild,
    parse_staff_ids,
    role,
    snowflake,
    text_channel,
    ticket_category_public,
    ticket_public,
)

log = logging.getLogger("frabot.web.tickets")
router = APIRouter(prefix="/api/tickets", tags=["tickets"])


def _panel_url(runtime) -> str | None:
    cfg = runtime.config.get()
    guild = cfg["discord"]["guild_id"]
    channel = cfg["tickets"]["panel_channel_id"]
    message = cfg["tickets"]["panel_message_id"]
    if guild and channel and message:
        return f"https://discord.com/channels/{guild}/{channel}/{message}"
    return None


async def _clean_category(runtime, payload: dict, existing: dict | None = None) -> dict:
    guild = optional_guild(runtime)
    name = as_str(payload.get("name", existing["name"] if existing else ""), "", 80)
    if not name:
        raise bad_request("Il nome della categoria è obbligatorio (max 80 caratteri).")
    emoji = as_str(payload.get("emoji", existing["emoji"] if existing else "🎫"), "🎫", 32)
    description = as_str(
        payload.get("description", existing["description"] if existing else ""), "", 500
    )
    welcome = as_str(
        payload.get("welcome_message", existing["welcome_message"] if existing else ""), "", 2000
    )
    discord_category_id = snowflake_or_empty(
        payload.get("discord_category_id", existing["discord_category_id"] if existing else "")
    )
    if discord_category_id and guild:
        await category_channel(guild, discord_category_id, "Categoria Discord")
    if not discord_category_id:
        raw = payload.get("discord_category_id")
        if raw not in (None, ""):
            snowflake(raw, "Categoria Discord")
    staff_raw = payload.get("staff_role_ids", existing["staff_role_ids"] if existing else [])
    if isinstance(staff_raw, str):
        try:
            staff_raw = json.loads(staff_raw)
        except json.JSONDecodeError:
            staff_raw = []
    staff = parse_staff_ids(staff_raw)
    if guild:
        for role_id in staff:
            role(guild, role_id, "Ruolo staff")
    else:
        for role_id in staff:
            snowflake(role_id, "Ruolo staff")
    position = int(existing["position"]) if existing else int(
        runtime.db.one("SELECT COALESCE(MAX(position), -1) + 1 AS n FROM ticket_categories")["n"]
    )
    return {
        "name": name,
        "emoji": emoji or "🎫",
        "description": description,
        "discord_category_id": discord_category_id,
        "staff_role_ids": staff,
        "welcome_message": welcome,
        "position": position,
    }


def _refresh_views(runtime) -> None:
    bot = runtime.bot_manager.bot
    if bot and bot.is_ready():
        cog = bot.get_cog("Tickets")
        if cog:
            cog.refresh_persistent_views()


@router.get("/categories")
async def list_categories(request: Request) -> dict:
    runtime = get_rt(request)
    rows = runtime.db.query("SELECT * FROM ticket_categories ORDER BY position, id")
    return {"items": [ticket_category_public(row) for row in rows]}


@router.post("/categories")
async def create_category(request: Request, payload: dict[str, Any] = Body(...)) -> dict:
    runtime = get_rt(request)
    count = runtime.db.one("SELECT COUNT(*) AS n FROM ticket_categories")["n"]
    if count >= 20:
        raise bad_request("Puoi creare al massimo 20 categorie (limite componenti Discord).")
    category = await _clean_category(runtime, payload)
    category_id = runtime.db.execute(
        """INSERT INTO ticket_categories(name, emoji, description, discord_category_id,
               staff_role_ids, welcome_message, position) VALUES(?, ?, ?, ?, ?, ?, ?)""",
        (
            category["name"], category["emoji"], category["description"],
            category["discord_category_id"],
            json.dumps(category["staff_role_ids"]),
            category["welcome_message"], category["position"],
        ),
    )
    _refresh_views(runtime)
    row = runtime.db.one("SELECT * FROM ticket_categories WHERE id = ?", (category_id,))
    return {"item": ticket_category_public(row)}


@router.put("/categories/{category_id}")
async def update_category(
    request: Request, category_id: int, payload: dict[str, Any] = Body(...)
) -> dict:
    runtime = get_rt(request)
    existing = runtime.db.one("SELECT * FROM ticket_categories WHERE id = ?", (category_id,))
    if not existing:
        raise HTTPException(status_code=404, detail="Categoria non trovata.")
    category = await _clean_category(runtime, payload, existing)
    runtime.db.execute(
        """UPDATE ticket_categories SET name = ?, emoji = ?, description = ?,
               discord_category_id = ?, staff_role_ids = ?, welcome_message = ?, position = ?
           WHERE id = ?""",
        (
            category["name"], category["emoji"], category["description"],
            category["discord_category_id"],
            json.dumps(category["staff_role_ids"]),
            category["welcome_message"], category["position"], category_id,
        ),
    )
    _refresh_views(runtime)
    row = runtime.db.one("SELECT * FROM ticket_categories WHERE id = ?", (category_id,))
    return {"item": ticket_category_public(row)}


@router.delete("/categories/{category_id}")
async def delete_category(request: Request, category_id: int) -> dict:
    runtime = get_rt(request)
    existing = runtime.db.one("SELECT id FROM ticket_categories WHERE id = ?", (category_id,))
    if not existing:
        raise HTTPException(status_code=404, detail="Categoria non trovata.")
    runtime.db.execute("DELETE FROM ticket_categories WHERE id = ?", (category_id,))
    _refresh_views(runtime)
    return {"ok": True, "republish_required": True}


@router.get("/stats")
async def ticket_stats(request: Request) -> dict:
    runtime = get_rt(request)
    counts = runtime.db.one(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END) AS open,
                  SUM(CASE WHEN status = 'closed' THEN 1 ELSE 0 END) AS closed,
                  SUM(CASE WHEN transcript IS NOT NULL THEN 1 ELSE 0 END) AS with_transcript
           FROM tickets"""
    ) or {}
    today = runtime.db.one(
        "SELECT COUNT(*) AS n FROM tickets WHERE status = 'closed' AND closed_at LIKE ?",
        (datetime.now(timezone.utc).strftime("%Y-%m-%d") + "%",),
    )
    avg = runtime.db.one(
        """SELECT AVG((julianday(closed_at) - julianday(created_at)) * 86400) AS seconds
           FROM tickets WHERE status = 'closed' AND closed_at IS NOT NULL"""
    )
    by_category = runtime.db.query(
        """SELECT category_name,
                  SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END) AS open,
                  SUM(CASE WHEN status = 'closed' THEN 1 ELSE 0 END) AS closed,
                  COUNT(*) AS total
           FROM tickets GROUP BY category_name ORDER BY total DESC"""
    )
    return {
        "total": int(counts.get("total") or 0),
        "open": int(counts.get("open") or 0),
        "closed": int(counts.get("closed") or 0),
        "with_transcript": int(counts.get("with_transcript") or 0),
        "closed_today": int(today["n"]) if today else 0,
        "avg_close_seconds": round(float(avg["seconds"]), 1) if avg and avg["seconds"] is not None else None,
        "by_category": by_category,
    }


@router.get("/panel")
async def panel_status(request: Request) -> dict:
    runtime = get_rt(request)
    cfg = runtime.config.get()
    return {
        "channel_id": cfg["tickets"]["panel_channel_id"],
        "message_id": cfg["tickets"]["panel_message_id"],
        "published": bool(cfg["tickets"]["panel_channel_id"] and cfg["tickets"]["panel_message_id"]),
        "url": _panel_url(runtime),
        "categories": runtime.db.one("SELECT COUNT(*) AS n FROM ticket_categories")["n"],
    }


@router.post("/publish")
async def publish(request: Request) -> dict:
    runtime = get_rt(request)
    bot = runtime.bot_manager.bot
    if not bot or not bot.is_ready():
        raise HTTPException(status_code=409, detail="Bot Discord non connesso.")
    cog = bot.get_cog("Tickets")
    if not cog:
        raise HTTPException(status_code=409, detail="Modulo Ticket non ancora caricato.")
    try:
        result = await cog.publish_panel()
    except TicketError as exc:
        raise bad_request(str(exc)) from exc
    except discord.Forbidden:
        raise HTTPException(
            status_code=403,
            detail="Il bot non ha i permessi per pubblicare in quel canale.",
        )
    except discord.HTTPException as exc:
        raise HTTPException(status_code=502, detail=f"Discord ha rifiutato la richiesta ({exc.status}).")
    return {"ok": True, "message": result, "url": result.get("url")}


@router.get("")
async def list_tickets(
    request: Request,
    status: str = "all",
    category_id: int | None = None,
    q: str = "",
    limit: int = 50,
    offset: int = 0,
) -> dict:
    runtime = get_rt(request)
    if status not in {"all", "open", "closed"}:
        raise bad_request("Filtro stato non valido.")
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    where = ["1 = 1"]
    params: list[Any] = []
    if status != "all":
        where.append("t.status = ?")
        params.append(status)
    if category_id is not None:
        where.append("t.category_id = ?")
        params.append(category_id)
    if q.strip():
        where.append("(t.user_name LIKE ? OR CAST(t.id AS TEXT) LIKE ?)")
        term = f"%{q.strip()}%"
        params.extend([term, term])
    clause = " AND ".join(where)
    total = runtime.db.one(f"SELECT COUNT(*) AS n FROM tickets t WHERE {clause}", tuple(params))
    rows = runtime.db.query(
        f"""SELECT t.* FROM tickets t WHERE {clause}
            ORDER BY t.id DESC LIMIT ? OFFSET ?""",
        tuple(params + [limit, offset]),
    )
    return {
        "items": [ticket_public(row) for row in rows],
        "total": int(total["n"]) if total else 0,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{ticket_id}")
async def ticket_detail(request: Request, ticket_id: int) -> dict:
    runtime = get_rt(request)
    row = runtime.db.one("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Ticket non trovato.")
    item = ticket_public(row)
    if row["channel_id"] and row["guild_id"]:
        item["channel_url"] = (
            f"https://discord.com/channels/{row['guild_id']}/{row['channel_id']}"
        )
    return {"item": item}


@router.get("/{ticket_id}/transcript")
async def transcript(request: Request, ticket_id: int) -> dict:
    runtime = get_rt(request)
    row = runtime.db.one("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Ticket non trovato.")
    if not row["transcript"]:
        raise HTTPException(status_code=404, detail="Transcript non disponibile.")
    filename = Path(row["transcript"]).name
    path = runtime.transcripts_dir / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File del transcript non trovato.")
    if path.stat().st_size > 8_000_000:
        raise HTTPException(status_code=413, detail="Transcript troppo grande per la visualizzazione.")
    content = await asyncio.to_thread(path.read_text, "utf-8")
    return {"filename": filename, "html": content}


@router.post("/{ticket_id}/close")
async def force_close(
    request: Request, ticket_id: int, payload: dict[str, Any] | None = Body(default=None)
) -> dict:
    runtime = get_rt(request)
    bot = runtime.bot_manager.bot
    if not bot or not bot.is_ready():
        raise HTTPException(status_code=409, detail="Bot Discord non connesso.")
    cog = bot.get_cog("Tickets")
    if not cog:
        raise HTTPException(status_code=409, detail="Modulo Ticket non ancora caricato.")
    row = runtime.db.one("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Ticket non trovato.")
    if row["status"] != "open":
        raise HTTPException(status_code=409, detail="Il ticket è già chiuso.")
    reason = as_str((payload or {}).get("reason"), "Chiusura forzata dal pannello", 400)
    closed = await cog.close_ticket(ticket_id, None, "Pannello web", reason)
    if not closed:
        raise HTTPException(status_code=409, detail="Il ticket è già chiuso.")
    return {"ok": True, "item": ticket_public(closed)}
