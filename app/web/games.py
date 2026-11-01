from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request, Response

from app.bot.cogs.games import GAMES
from app.utils import as_bool, as_int, as_str, is_snowflake, snowflake_or_empty, utcnow_iso
from app.web.common import bad_request, get_rt, optional_guild, snowflake, text_channel

log = logging.getLogger("frabot.web.games")
router = APIRouter(prefix="/api/games", tags=["games"])


def _public(runtime) -> dict:
    games = runtime.config.get()["games"]
    categories = [
        row["category"]
        for row in runtime.db.query("SELECT DISTINCT category FROM quiz_questions ORDER BY category")
    ]
    return {
        "games": games,
        "questions": runtime.db.one("SELECT COUNT(*) AS n FROM quiz_questions")["n"],
        "categories": categories,
    }


@router.get("")
async def get_games(request: Request) -> dict:
    return _public(get_rt(request))


@router.put("")
async def update_games(request: Request, payload: dict[str, Any] = Body(...)) -> dict:
    runtime = get_rt(request)
    cfg = runtime.config.get()
    guild = optional_guild(runtime)
    games = cfg["games"]
    if "economy_enabled" in payload:
        games["economy_enabled"] = as_bool(payload["economy_enabled"], games["economy_enabled"])
    if "daily_coins" in payload:
        games["daily_coins"] = as_int(payload["daily_coins"], games["daily_coins"], minimum=0, maximum=100000)
    items = payload.get("items")
    if isinstance(items, dict):
        for key in GAMES:
            incoming = items.get(key)
            if not isinstance(incoming, dict):
                continue
            item = games["items"][key]
            if "enabled" in incoming:
                item["enabled"] = as_bool(incoming["enabled"], item["enabled"])
            if "cooldown" in incoming:
                item["cooldown"] = as_int(incoming["cooldown"], item["cooldown"], minimum=0, maximum=3600)
            if "reward" in incoming:
                item["reward"] = as_int(incoming["reward"], item["reward"], minimum=0, maximum=100000)
            if "channels" in incoming:
                channels_raw = incoming["channels"]
                if not isinstance(channels_raw, list):
                    raise bad_request(f"Canali non validi per {key}.")
                channels: list[str] = []
                for channel_id in channels_raw:
                    if guild:
                        channel = await text_channel(guild, channel_id, f"Canale {key}")
                        cid = str(channel.id)
                    else:
                        cid = snowflake(channel_id, f"Canale {key}")
                    if cid not in channels:
                        channels.append(cid)
                item["channels"] = channels
    runtime.config.save(cfg)
    return _public(runtime)


def _clean_question(payload: dict[str, Any]) -> dict:
    category = as_str(payload.get("category"), "Generale", 60)
    question = as_str(payload.get("question"), "", 500)
    if len(question) < 3:
        raise bad_request("La domanda deve avere almeno 3 caratteri.")
    options_raw = payload.get("options")
    if not isinstance(options_raw, list) or not (2 <= len(options_raw) <= 4):
        raise bad_request("Servono da 2 a 4 opzioni.")
    options = [as_str(option, "", 200) for option in options_raw]
    if any(not option for option in options):
        raise bad_request("Le opzioni non possono essere vuote.")
    try:
        answer = int(payload.get("answer", 0))
    except (TypeError, ValueError):
        answer = -1
    if not 0 <= answer < len(options):
        raise bad_request("La risposta corretta deve essere una delle opzioni.")
    return {"category": category or "Generale", "question": question, "options": options, "answer": answer}


def _question_public(row: dict) -> dict:
    try:
        options = json.loads(row["options"])
    except json.JSONDecodeError:
        options = []
    return {
        "id": row["id"],
        "category": row["category"],
        "question": row["question"],
        "options": options,
        "answer": row["answer"],
        "created_at": row.get("created_at"),
    }


@router.get("/quiz")
async def list_quiz(request: Request, category: str | None = None) -> dict:
    runtime = get_rt(request)
    if category:
        rows = runtime.db.query(
            "SELECT id, category, question, options, answer FROM quiz_questions "
            "WHERE category = ? ORDER BY id",
            (category,),
        )
    else:
        rows = runtime.db.query(
            "SELECT id, category, question, options, answer FROM quiz_questions ORDER BY id"
        )
    return {"items": [_question_public(row) for row in rows]}


@router.post("/quiz")
async def create_question(request: Request, payload: dict[str, Any] = Body(...)) -> dict:
    runtime = get_rt(request)
    count = runtime.db.one("SELECT COUNT(*) AS n FROM quiz_questions")["n"]
    if count >= 500:
        raise bad_request("Hai raggiunto il limite di 500 domande.")
    data = _clean_question(payload)
    question_id = runtime.db.execute(
        "INSERT INTO quiz_questions(category, question, options, answer, created_at) VALUES(?, ?, ?, ?, ?)",
        (data["category"], data["question"], json.dumps(data["options"]), data["answer"], utcnow_iso()),
    )
    row = runtime.db.one("SELECT * FROM quiz_questions WHERE id = ?", (question_id,))
    return {"item": _question_public(row)}


@router.put("/quiz/{question_id}")
async def update_question(
    request: Request, question_id: int, payload: dict[str, Any] = Body(...)
) -> dict:
    runtime = get_rt(request)
    existing = runtime.db.one("SELECT id FROM quiz_questions WHERE id = ?", (question_id,))
    if not existing:
        raise HTTPException(status_code=404, detail="Domanda non trovata.")
    data = _clean_question(payload)
    runtime.db.execute(
        "UPDATE quiz_questions SET category = ?, question = ?, options = ?, answer = ? WHERE id = ?",
        (data["category"], data["question"], json.dumps(data["options"]), data["answer"], question_id),
    )
    row = runtime.db.one("SELECT * FROM quiz_questions WHERE id = ?", (question_id,))
    return {"item": _question_public(row)}


@router.delete("/quiz/{question_id}")
async def delete_question(request: Request, question_id: int) -> dict:
    runtime = get_rt(request)
    existing = runtime.db.one("SELECT id FROM quiz_questions WHERE id = ?", (question_id,))
    if not existing:
        raise HTTPException(status_code=404, detail="Domanda non trovata.")
    runtime.db.execute("DELETE FROM quiz_questions WHERE id = ?", (question_id,))
    return {"ok": True}


@router.get("/quiz/export")
async def export_quiz(request: Request) -> Response:
    runtime = get_rt(request)
    rows = runtime.db.query(
        "SELECT category, question, options, answer FROM quiz_questions ORDER BY id"
    )
    questions = []
    for row in rows:
        try:
            options = json.loads(row["options"])
        except json.JSONDecodeError:
            options = []
        questions.append(
            {
                "category": row["category"],
                "question": row["question"],
                "options": options,
                "answer": row["answer"],
            }
        )
    payload = {
        "app": "frabot",
        "version": "1.0.0",
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "questions": questions,
    }
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    return Response(
        content=json.dumps(payload, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="frabot-quiz-{stamp}.json"'},
    )


@router.post("/quiz/import")
async def import_quiz(request: Request, payload: dict[str, Any] = Body(...)) -> dict:
    runtime = get_rt(request)
    questions_raw = payload.get("questions") if isinstance(payload.get("questions"), list) else []
    if len(questions_raw) > 500:
        raise bad_request("Puoi importare al massimo 500 domande.")
    cleaned = []
    for raw in questions_raw:
        if not isinstance(raw, dict):
            raise bad_request("Formato domanda non valido.")
        cleaned.append(_clean_question(raw))
    with runtime.db.transaction() as conn:
        conn.execute("DELETE FROM quiz_questions")
        conn.executemany(
            "INSERT INTO quiz_questions(category, question, options, answer, created_at) VALUES(?, ?, ?, ?, ?)",
            [
                (q["category"], q["question"], json.dumps(q["options"]), q["answer"], utcnow_iso())
                for q in cleaned
            ],
        )
    return {"ok": True, "imported": len(cleaned)}


@router.get("/leaderboard")
async def leaderboard(request: Request, game: str = "coins", limit: int = 10) -> dict:
    runtime = get_rt(request)
    limit = max(1, min(limit, 50))
    if game != "coins" and game not in GAMES:
        raise bad_request("Gioco non valido.")
    guild_id = runtime.config.get()["discord"]["guild_id"]
    coins = runtime.db.query(
        "SELECT user_id, user_name, balance FROM economy WHERE guild_id = ? "
        "ORDER BY balance DESC LIMIT ?",
        (guild_id, limit),
    )
    stats = []
    if game in GAMES:
        stats = runtime.db.query(
            """SELECT user_id, user_name, wins, plays, coins FROM game_stats
               WHERE guild_id = ? AND game = ? ORDER BY wins DESC, plays ASC LIMIT ?""",
            (guild_id, game, limit),
        )
    return {
        "coins": coins,
        "game": game if game in GAMES else None,
        "stats": stats,
        "economy_enabled": runtime.config.get()["games"]["economy_enabled"],
    }


@router.post("/leaderboard/reset")
async def reset_leaderboard(request: Request, payload: dict[str, Any] = Body(...)) -> dict:
    runtime = get_rt(request)
    if payload.get("confirm") is not True:
        raise bad_request("Conferma richiesta.")
    scope = as_str(payload.get("scope"), "", 10)
    guild_id = runtime.config.get()["discord"]["guild_id"]
    if scope == "coins":
        runtime.db.execute("DELETE FROM economy WHERE guild_id = ?", (guild_id,))
    elif scope == "game":
        game = as_str(payload.get("game"), "", 20)
        if game not in GAMES:
            raise bad_request("Gioco non valido.")
        runtime.db.execute(
            "DELETE FROM game_stats WHERE guild_id = ? AND game = ?", (guild_id, game)
        )
    elif scope == "all":
        runtime.db.execute("DELETE FROM economy WHERE guild_id = ?", (guild_id,))
        runtime.db.execute("DELETE FROM game_stats WHERE guild_id = ?", (guild_id,))
    else:
        raise bad_request("Ambito di reset non valido.")
    return {"ok": True}
