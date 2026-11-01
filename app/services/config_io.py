from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

from app.config import normalize_config
from app.utils import as_str, snowflake_or_empty, utcnow_iso

if TYPE_CHECKING:
    from app.runtime import Runtime

log = logging.getLogger("frabot.configio")

LOGIN_RE = re.compile(r"^[a-zA-Z0-9_]{3,25}$")


class ConfigError(Exception):
    pass


def export_bundle(runtime: "Runtime") -> dict:
    cfg = runtime.config.get()
    cfg["discord"].pop("bot_token", None)
    cfg["discord"].pop("bot_user_id", None)
    cfg["discord"].pop("bot_name", None)
    cfg["discord"].pop("application_id", None)
    cfg["discord"].pop("guild_id", None)
    cfg["discord"].pop("guild_name", None)
    cfg["twitch"].pop("client_secret", None)
    cfg["tickets"].pop("panel_message_id", None)
    categories = runtime.db.query("SELECT * FROM ticket_categories ORDER BY position, id")
    for category in categories:
        try:
            category["staff_role_ids"] = json.loads(category["staff_role_ids"] or "[]")
        except json.JSONDecodeError:
            category["staff_role_ids"] = []
        category.pop("id", None)
    questions = runtime.db.query("SELECT * FROM quiz_questions ORDER BY id")
    for question in questions:
        try:
            question["options"] = json.loads(question["options"] or "[]")
        except json.JSONDecodeError:
            question["options"] = []
        question.pop("id", None)
        question.pop("created_at", None)
    streamers = runtime.db.query(
        """SELECT login, display_name, channel_id, mention_type, mention_role_id, template
           FROM twitch_streamers ORDER BY id"""
    )
    return {
        "app": "frabot",
        "version": "1.0.0",
        "exported_at": utcnow_iso(),
        "config": cfg,
        "ticket_categories": categories,
        "quiz_questions": questions,
        "twitch_streamers": streamers,
    }


def _clean_category(raw: Any, position: int) -> dict:
    if not isinstance(raw, dict):
        raise ConfigError("Categoria ticket non valida.")
    name = as_str(raw.get("name"), "", 80)
    if not name:
        raise ConfigError("Ogni categoria ticket deve avere un nome (max 80 caratteri).")
    secret = raw.get("staff_role_ids", [])
    if not isinstance(secret, list):
        secret = []
    return {
        "name": name,
        "emoji": as_str(raw.get("emoji"), "🎫", 32) or "🎫",
        "description": as_str(raw.get("description"), "", 500),
        "discord_category_id": snowflake_or_empty(raw.get("discord_category_id")),
        "staff_role_ids": [sf for sf in (snowflake_or_empty(v) for v in secret) if sf][:20],
        "welcome_message": as_str(raw.get("welcome_message"), "", 2000),
        "position": position,
    }


def _clean_question(raw: Any) -> dict:
    if not isinstance(raw, dict):
        raise ConfigError("Domanda quiz non valida.")
    question = as_str(raw.get("question"), "", 500)
    if not question:
        raise ConfigError("Ogni domanda quiz deve avere un testo.")
    options = raw.get("options")
    if not isinstance(options, list) or not (2 <= len(options) <= 4):
        raise ConfigError(f"La domanda «{question[:40]}» deve avere da 2 a 4 opzioni.")
    clean_options = [as_str(option, "", 200) for option in options]
    if any(not option for option in clean_options):
        raise ConfigError("Le opzioni del quiz non possono essere vuote.")
    try:
        answer = int(raw.get("answer", 0))
    except (TypeError, ValueError):
        answer = -1
    if not 0 <= answer < len(clean_options):
        raise ConfigError(f"Risposta corretta non valida per la domanda «{question[:40]}».")
    return {
        "category": as_str(raw.get("category"), "Generale", 60) or "Generale",
        "question": question,
        "options": clean_options,
        "answer": answer,
    }


def _clean_streamer(raw: Any) -> dict:
    if not isinstance(raw, dict):
        raise ConfigError("Streamer Twitch non valido.")
    login = as_str(raw.get("login"), "", 25).lower()
    if not LOGIN_RE.match(login):
        raise ConfigError(f"Login Twitch non valido: {login or '(vuoto)'}")
    mention = as_str(raw.get("mention_type"), "none", 10).lower()
    if mention not in {"none", "everyone", "role"}:
        raise ConfigError(f"Tipo menzione non valido per {login}.")
    role_id = snowflake_or_empty(raw.get("mention_role_id"))
    if mention == "role" and not role_id:
        raise ConfigError(f"Scegli un ruolo da menzionare per {login}.")
    return {
        "login": login,
        "display_name": as_str(raw.get("display_name"), login, 100),
        "channel_id": snowflake_or_empty(raw.get("channel_id")),
        "mention_type": mention,
        "mention_role_id": role_id,
        "template": as_str(raw.get("template"), "", 4096),
    }


def import_bundle(runtime: "Runtime", data: Any) -> dict:
    if not isinstance(data, dict) or data.get("app") != "frabot":
        raise ConfigError("File non riconosciuto: serve un export di FraBot.")
    raw_config = data.get("config")
    if not isinstance(raw_config, dict):
        raise ConfigError("Il file non contiene una configurazione valida.")

    categories_raw = data.get("ticket_categories", [])
    questions_raw = data.get("quiz_questions", [])
    streamers_raw = data.get("twitch_streamers", [])
    if not isinstance(categories_raw, list) or len(categories_raw) > 20:
        raise ConfigError("Puoi importare al massimo 20 categorie ticket.")
    if not isinstance(questions_raw, list) or len(questions_raw) > 500:
        raise ConfigError("Puoi importare al massimo 500 domande quiz.")
    if not isinstance(streamers_raw, list) or len(streamers_raw) > 100:
        raise ConfigError("Puoi importare al massimo 100 streamer.")

    categories = [_clean_category(item, index) for index, item in enumerate(categories_raw)]
    questions = [_clean_question(item) for item in questions_raw]
    streamers = [_clean_streamer(item) for item in streamers_raw]
    if len({s["login"] for s in streamers}) != len(streamers):
        raise ConfigError("Ci sono streamer duplicati nel file.")
    for streamer in streamers:
        if not streamer["channel_id"]:
            raise ConfigError(f"Canale di annuncio mancante per {streamer['login']}.")

    current = runtime.config.get()
    incoming = normalize_config(raw_config)
    # Identity, token and panel message are local to this installation.
    incoming["discord"] = current["discord"]
    if incoming["twitch"]["client_id"] != current["twitch"]["client_id"]:
        incoming["twitch"]["client_secret"] = ""
    else:
        incoming["twitch"]["client_secret"] = current["twitch"]["client_secret"]
    if incoming["tickets"]["panel_channel_id"] == current["tickets"]["panel_channel_id"]:
        incoming["tickets"]["panel_message_id"] = current["tickets"]["panel_message_id"]
    else:
        incoming["tickets"]["panel_message_id"] = ""
    runtime.config.save(incoming)

    with runtime.db.transaction() as conn:
        conn.execute("DELETE FROM ticket_categories")
        conn.execute("DELETE FROM quiz_questions")
        conn.execute("DELETE FROM twitch_streamers")
        conn.executemany(
            """INSERT INTO ticket_categories(name, emoji, description, discord_category_id,
                   staff_role_ids, welcome_message, position) VALUES(?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    c["name"], c["emoji"], c["description"], c["discord_category_id"],
                    json.dumps(c["staff_role_ids"]), c["welcome_message"], c["position"],
                )
                for c in categories
            ],
        )
        conn.executemany(
            """INSERT INTO quiz_questions(category, question, options, answer, created_at)
               VALUES(?, ?, ?, ?, ?)""",
            [
                (q["category"], q["question"], json.dumps(q["options"]), q["answer"], utcnow_iso())
                for q in questions
            ],
        )
        conn.executemany(
            """INSERT INTO twitch_streamers(login, display_name, channel_id, mention_type,
                   mention_role_id, template, created_at) VALUES(?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    s["login"], s["display_name"], s["channel_id"], s["mention_type"],
                    s["mention_role_id"], s["template"], utcnow_iso(),
                )
                for s in streamers
            ],
        )
    _refresh_views(runtime)
    log.info(
        "Configurazione importata",
        extra={"ctx_categories": len(categories), "ctx_questions": len(questions), "ctx_streamers": len(streamers)},
    )
    return {"categories": len(categories), "questions": len(questions), "streamers": len(streamers)}


def reset_all(runtime: "Runtime") -> dict:
    runtime.config.reset_all()
    with runtime.db.transaction() as conn:
        conn.execute("DELETE FROM ticket_categories")
        conn.execute("DELETE FROM quiz_questions")
        conn.execute("DELETE FROM twitch_streamers")
    _refresh_views(runtime)
    log.warning("Configurazione di FraBot azzerata dal pannello")
    return {"ok": True}


def _refresh_views(runtime: "Runtime") -> None:
    bot = runtime.bot_manager.bot
    if not bot or not bot.is_ready():
        return
    cog = bot.get_cog("Tickets")
    if cog and hasattr(cog, "refresh_persistent_views"):
        cog.refresh_persistent_views()
