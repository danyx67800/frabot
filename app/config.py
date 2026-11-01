from __future__ import annotations

import copy
import re
import threading
from typing import Any

from app.db import Database
from app.logging_setup import register_secrets
from app.utils import as_bool, as_int, as_str, is_masked, snowflake_or_empty, utcnow_iso

DEFAULT_TWITCH_TEMPLATE = (
    "🔴 **{streamer}** è live!\n\n"
    "**{titolo}**\n"
    "🎮 {gioco} · 👥 {viewers} spettatori\n\n"
    "{url}"
)

DEFAULT_GAMES: dict[str, dict[str, Any]] = {
    "tris": {"enabled": True, "channels": [], "cooldown": 15, "reward": 20},
    "indovina": {"enabled": True, "channels": [], "cooldown": 15, "reward": 15},
    "quiz": {"enabled": True, "channels": [], "cooldown": 10, "reward": 10},
    "rps": {"enabled": True, "channels": [], "cooldown": 5, "reward": 5},
    "dado": {"enabled": True, "channels": [], "cooldown": 3, "reward": 2},
    "moneta": {"enabled": True, "channels": [], "cooldown": 3, "reward": 2},
    "slot": {"enabled": True, "channels": [], "cooldown": 10, "reward": 5},
}

DEFAULT_CONFIG: dict[str, Any] = {
    "discord": {
        "application_id": "",
        "bot_token": "",
        "bot_user_id": "",
        "bot_name": "",
        "guild_id": "",
        "guild_name": "",
    },
    "modules": {"tickets": False, "games": False, "twitch": False},
    "ui": {"embed_color": "#7C5CFF"},
    "tickets": {
        "panel_channel_id": "",
        "log_channel_id": "",
        "panel_message_id": "",
        "max_open_per_user": 2,
        "auto_close_hours": 72,
        "ask_reason": True,
    },
    "games": {
        "economy_enabled": True,
        "daily_coins": 50,
        "items": DEFAULT_GAMES,
    },
    "twitch": {
        "client_id": "",
        "client_secret": "",
        "update_on_end": True,
    },
    "setup": {"test_channel_id": ""},
}

DEFAULT_WIZARD: dict[str, Any] = {
    "completed": False,
    "step": 1,
    "discord_verified": False,
    "twitch_verified": False,
    "test_sent": False,
}

_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def default_config() -> dict[str, Any]:
    return copy.deepcopy(DEFAULT_CONFIG)


def _clean_channels(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        sf = snowflake_or_empty(item)
        if sf and sf not in out:
            out.append(sf)
    return out[:50]


def normalize_config(raw: Any) -> dict[str, Any]:
    """Merge stored/imported data onto defaults, coercing every known field.

    Unknown keys are dropped on purpose: imported JSON must never inject
    arbitrary configuration into the app.
    """
    raw = raw if isinstance(raw, dict) else {}
    cfg = default_config()

    discord = raw.get("discord") if isinstance(raw.get("discord"), dict) else {}
    cfg["discord"]["application_id"] = snowflake_or_empty(discord.get("application_id"))
    cfg["discord"]["bot_token"] = as_str(discord.get("bot_token"), "", 300)
    cfg["discord"]["bot_user_id"] = snowflake_or_empty(discord.get("bot_user_id"))
    cfg["discord"]["bot_name"] = as_str(discord.get("bot_name"), "", 100)
    cfg["discord"]["guild_id"] = snowflake_or_empty(discord.get("guild_id"))
    cfg["discord"]["guild_name"] = as_str(discord.get("guild_name"), "", 100)

    modules = raw.get("modules") if isinstance(raw.get("modules"), dict) else {}
    for key in ("tickets", "games", "twitch"):
        cfg["modules"][key] = as_bool(modules.get(key), False)

    ui = raw.get("ui") if isinstance(raw.get("ui"), dict) else {}
    color = as_str(ui.get("embed_color"), "", 7)
    cfg["ui"]["embed_color"] = color.upper() if _COLOR_RE.match(color) else "#7C5CFF"

    tickets = raw.get("tickets") if isinstance(raw.get("tickets"), dict) else {}
    cfg["tickets"]["panel_channel_id"] = snowflake_or_empty(tickets.get("panel_channel_id"))
    cfg["tickets"]["log_channel_id"] = snowflake_or_empty(tickets.get("log_channel_id"))
    cfg["tickets"]["panel_message_id"] = snowflake_or_empty(tickets.get("panel_message_id"))
    cfg["tickets"]["max_open_per_user"] = as_int(
        tickets.get("max_open_per_user"), 2, minimum=1, maximum=10
    )
    cfg["tickets"]["auto_close_hours"] = as_int(
        tickets.get("auto_close_hours"), 72, minimum=0, maximum=720
    )
    cfg["tickets"]["ask_reason"] = as_bool(tickets.get("ask_reason"), True)

    games = raw.get("games") if isinstance(raw.get("games"), dict) else {}
    cfg["games"]["economy_enabled"] = as_bool(games.get("economy_enabled"), True)
    cfg["games"]["daily_coins"] = as_int(games.get("daily_coins"), 50, minimum=0, maximum=100000)
    stored_items = games.get("items") if isinstance(games.get("items"), dict) else {}
    for key, item_defaults in DEFAULT_GAMES.items():
        item = stored_items.get(key) if isinstance(stored_items.get(key), dict) else {}
        cfg["games"]["items"][key] = {
            "enabled": as_bool(item.get("enabled"), item_defaults["enabled"]),
            "channels": _clean_channels(item.get("channels", [])),
            "cooldown": as_int(
                item.get("cooldown"), item_defaults["cooldown"], minimum=0, maximum=3600
            ),
            "reward": as_int(item.get("reward"), item_defaults["reward"], minimum=0, maximum=100000),
        }

    twitch = raw.get("twitch") if isinstance(raw.get("twitch"), dict) else {}
    cfg["twitch"]["client_id"] = as_str(twitch.get("client_id"), "", 100)
    secret = twitch.get("client_secret")
    cfg["twitch"]["client_secret"] = "" if is_masked(secret) else as_str(secret, "", 200)
    cfg["twitch"]["update_on_end"] = as_bool(twitch.get("update_on_end"), True)

    setup = raw.get("setup") if isinstance(raw.get("setup"), dict) else {}
    cfg["setup"]["test_channel_id"] = snowflake_or_empty(setup.get("test_channel_id"))

    return cfg


def normalize_wizard(raw: Any) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    return {
        "completed": as_bool(raw.get("completed"), False),
        "step": as_int(raw.get("step"), 1, minimum=1, maximum=7),
        "discord_verified": as_bool(raw.get("discord_verified"), False),
        "twitch_verified": as_bool(raw.get("twitch_verified"), False),
        "test_sent": as_bool(raw.get("test_sent"), False),
    }


class ConfigManager:
    def __init__(self, db: Database) -> None:
        self.db = db
        self._lock = threading.RLock()
        self._config = normalize_config(db.get_setting("config", {}))
        self._wizard = normalize_wizard(db.get_setting("wizard", {}))
        self._refresh_secrets()

    def _refresh_secrets(self) -> None:
        register_secrets(
            [
                self._config["discord"]["bot_token"],
                self._config["twitch"]["client_secret"],
            ]
        )

    def get(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._config)

    def public(self) -> dict[str, Any]:
        """Config safe for the browser: secrets are replaced, never sent."""
        with self._lock:
            out = copy.deepcopy(self._config)
            bot_token = out["discord"].pop("bot_token", "")
            twitch_secret = out["twitch"].pop("client_secret", "")
            out["discord"]["has_bot_token"] = bool(bot_token)
            out["discord"]["bot_token_masked"] = "••••••••" if bot_token else ""
            out["twitch"]["has_client_secret"] = bool(twitch_secret)
            out["twitch"]["client_secret_masked"] = "••••••••" if twitch_secret else ""
            return out

    def save(self, cfg: dict[str, Any]) -> dict[str, Any]:
        normalized = normalize_config(cfg)
        with self._lock:
            self._config = normalized
            self.db.set_setting("config", normalized)
            self._refresh_secrets()
            return copy.deepcopy(normalized)

    def patch(self, section: str, values: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            cfg = copy.deepcopy(self._config)
            current = cfg.get(section)
            if not isinstance(current, dict):
                current = {}
            current.update(values or {})
            cfg[section] = current
            return self.save(cfg)

    def get_wizard(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._wizard)

    def public_wizard(self) -> dict[str, Any]:
        with self._lock:
            out = copy.deepcopy(self._wizard)
            out["updated_at"] = self.db.get_setting("wizard", {}).get("updated_at") or utcnow_iso()
            return out

    def save_wizard(self, wizard: dict[str, Any]) -> dict[str, Any]:
        normalized = normalize_wizard(wizard)
        normalized["updated_at"] = utcnow_iso()
        with self._lock:
            self._wizard = normalized
            self.db.set_setting("wizard", normalized)
            return copy.deepcopy(normalized)

    def reset_all(self) -> None:
        with self._lock:
            self._config = default_config()
            self._wizard = normalize_wizard({})
            self.db.set_setting("config", self._config)
            self.db.set_setting("wizard", self._wizard)
            self._refresh_secrets()
