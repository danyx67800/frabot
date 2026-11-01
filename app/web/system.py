from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.web.common import get_rt, guild_channels_payload, require_bot, require_guild

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/status")
async def status(request: Request) -> dict:
    return get_rt(request).status()


@router.get("/logs")
async def logs(request: Request, limit: int = 200, level: str | None = None) -> dict:
    runtime = get_rt(request)
    limit = max(1, min(limit, 800))
    if level and level.upper() not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise HTTPException(status_code=400, detail="Livello di log non valido.")
    return {"items": runtime.logs.snapshot(limit=limit, level=level)}


@router.get("/discord/guilds")
async def guilds(request: Request) -> dict:
    bot = require_bot(get_rt(request))
    return {
        "guilds": [
            {
                "id": str(guild.id),
                "name": guild.name,
                "member_count": guild.member_count,
                "icon_url": str(guild.icon.url) if guild.icon else None,
            }
            for guild in bot.guilds
        ]
    }


@router.get("/discord/guild/{guild_id}")
async def guild_detail(request: Request, guild_id: str) -> dict:
    runtime = get_rt(request)
    guild = require_guild(runtime, guild_id)
    return guild_channels_payload(guild)
