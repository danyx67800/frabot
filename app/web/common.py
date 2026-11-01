from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote, urlencode

import discord
from fastapi import HTTPException, Request

from app.runtime import Runtime
from app.utils import is_snowflake, snowflake_or_empty

# Exactly the permissions FraBot needs: private ticket channels, messages,
# embeds, attachments, history for transcripts and @everyone for Twitch pings.
REQUIRED_PERMISSIONS = discord.Permissions(
    view_channel=True,
    send_messages=True,
    embed_links=True,
    attach_files=True,
    read_message_history=True,
    manage_channels=True,
    manage_roles=True,
    mention_everyone=True,
)


def get_rt(request: Request) -> Runtime:
    return request.app.state.runtime


def bad_request(message: str) -> HTTPException:
    return HTTPException(status_code=400, detail=message)


def require_bot(rt: Runtime):
    bot = rt.bot_manager.bot
    if not bot or not bot.is_ready():
        raise HTTPException(
            status_code=409,
            detail="Bot Discord non connesso. Attendi la connessione e riprova.",
        )
    return bot


def require_guild(rt: Runtime, guild_id: str | None = None) -> discord.Guild:
    bot = require_bot(rt)
    gid = guild_id or rt.config.get()["discord"]["guild_id"]
    if not gid:
        raise HTTPException(status_code=409, detail="Nessun server Discord configurato.")
    guild = bot.get_guild(int(gid))
    if not guild:
        raise HTTPException(
            status_code=404,
            detail="Il bot non è presente nel server configurato. Reinvitalo o scegli un altro server.",
        )
    return guild


def optional_guild(rt: Runtime) -> discord.Guild | None:
    if not rt.bot_manager.is_connected:
        return None
    gid = rt.config.get()["discord"]["guild_id"]
    if not gid:
        return None
    return rt.bot_manager.bot.get_guild(int(gid))  # type: ignore[union-attr]


def snowflake(value: Any, label: str, required: bool = False) -> str:
    if value in (None, ""):
        if required:
            raise bad_request(f"{label} obbligatorio.")
        return ""
    text = str(value).strip()
    if not is_snowflake(text):
        raise bad_request(f"{label} non valido.")
    return text


async def text_channel(guild: discord.Guild, channel_id: Any, label: str):
    cid = snowflake(channel_id, label, required=True)
    channel = guild.get_channel(int(cid))
    if channel is None:
        try:
            channel = await guild.fetch_channel(int(cid))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            channel = None
    if not isinstance(channel, discord.TextChannel):
        raise bad_request(f"{label}: scegli un canale testuale.")
    return channel


async def category_channel(guild: discord.Guild, channel_id: Any, label: str):
    cid = snowflake(channel_id, label, required=True)
    channel = guild.get_channel(int(cid))
    if channel is None:
        try:
            channel = await guild.fetch_channel(int(cid))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            channel = None
    if not isinstance(channel, discord.CategoryChannel):
        raise bad_request(f"{label}: scegli una categoria Discord.")
    return channel


def role(guild: discord.Guild, role_id: Any, label: str) -> discord.Role:
    rid = snowflake(role_id, label, required=True)
    found = guild.get_role(int(rid))
    if not found:
        raise bad_request(f"{label}: ruolo non trovato nel server.")
    return found


def channel_type(channel) -> str:
    if isinstance(channel, discord.CategoryChannel):
        return "category"
    if isinstance(channel, discord.TextChannel):
        return "text"
    if isinstance(channel, discord.VoiceChannel):
        return "voice"
    if isinstance(channel, discord.StageChannel):
        return "stage"
    if isinstance(channel, discord.ForumChannel):
        return "forum"
    return "other"


def serialize_channel(channel) -> dict:
    return {
        "id": str(channel.id),
        "name": str(getattr(channel, "name", "")),
        "type": channel_type(channel),
        "position": int(getattr(channel, "position", 0)),
        "parent_id": str(channel.parent_id) if getattr(channel, "parent_id", None) else None,
    }


def serialize_role(role_obj: discord.Role) -> dict:
    return {
        "id": str(role_obj.id),
        "name": role_obj.name,
        "color": f"#{role_obj.color.value:06X}",
        "position": role_obj.position,
        "managed": role_obj.managed,
    }


def guild_summary(guild: discord.Guild) -> dict:
    return {
        "id": str(guild.id),
        "name": guild.name,
        "member_count": guild.member_count,
        "icon_url": str(guild.icon.url) if guild.icon else None,
    }


def guild_channels_payload(guild: discord.Guild) -> dict:
    channels = sorted(guild.channels, key=lambda c: (getattr(c, "position", 0), c.name))
    roles = sorted(
        [r for r in guild.roles if not r.is_default()],
        key=lambda r: r.position,
        reverse=True,
    )
    return {
        "guild": guild_summary(guild),
        "channels": [serialize_channel(c) for c in channels],
        "roles": [serialize_role(r) for r in roles],
    }


def invite_url(cfg: dict) -> str:
    app_id = cfg["discord"]["application_id"]
    if not app_id:
        return ""
    params = {
        "client_id": app_id,
        "scope": "bot applications.commands",
        "permissions": str(REQUIRED_PERMISSIONS.value),
    }
    return "https://discord.com/oauth2/authorize?" + urlencode(params, quote_via=quote)


def parse_staff_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        sf = snowflake_or_empty(item)
        if sf and sf not in out:
            out.append(sf)
    return out[:20]


def ticket_category_public(row: dict) -> dict:
    try:
        staff = json.loads(row.get("staff_role_ids") or "[]")
    except json.JSONDecodeError:
        staff = []
    return {
        "id": int(row["id"]),
        "name": row["name"],
        "emoji": row["emoji"],
        "description": row["description"],
        "discord_category_id": row.get("discord_category_id") or "",
        "staff_role_ids": staff if isinstance(staff, list) else [],
        "welcome_message": row["welcome_message"],
        "position": row["position"],
    }


def ticket_public(row: dict) -> dict:
    return {
        "id": int(row["id"]),
        "number": f"{int(row['id']):04d}",
        "guild_id": row["guild_id"],
        "channel_id": row.get("channel_id"),
        "user_id": row["user_id"],
        "user_name": row["user_name"],
        "category_id": row.get("category_id"),
        "category_name": row["category_name"],
        "reason": row.get("reason") or "",
        "status": row["status"],
        "claimed_by": row.get("claimed_by"),
        "claimed_by_name": row.get("claimed_by_name"),
        "created_at": row["created_at"],
        "last_activity": row["last_activity"],
        "closed_at": row.get("closed_at"),
        "closed_by": row.get("closed_by"),
        "close_reason": row.get("close_reason"),
        "transcript": row.get("transcript"),
        "transcript_available": bool(row.get("transcript")),
    }
