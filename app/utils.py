from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from typing import Any

_MASK = "••••••••"
_SNOWFLAKE_RE = re.compile(r"^\d{15,22}$")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def utcnow_iso() -> str:
    return utcnow().isoformat(timespec="seconds")


def mask_secret(value: str) -> str:
    return _MASK if value else ""


def is_masked(value: Any) -> bool:
    return isinstance(value, str) and (_MASK in value or set(value) == {"•"})


def is_snowflake(value: Any) -> bool:
    return isinstance(value, str) and bool(_SNOWFLAKE_RE.match(value))


def snowflake_or_empty(value: Any) -> str:
    if isinstance(value, int):
        value = str(value)
    if isinstance(value, str) and _SNOWFLAKE_RE.match(value.strip()):
        return value.strip()
    return ""


def channel_slug(name: str, limit: int = 24) -> str:
    """Discord-safe suffix for ticket channel names."""
    normalized = unicodedata.normalize("NFKD", name)
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii").lower()
    ascii_name = re.sub(r"[^a-z0-9]+", "-", ascii_name).strip("-")
    return (ascii_name or "utente")[:limit].strip("-") or "utente"


def render_template(template: str, variables: dict[str, Any]) -> str:
    """Replace only known {placeholders}; unknown/format specifiers stay intact."""
    out = template
    for key, value in variables.items():
        out = out.replace("{" + key + "}", str(value))
    return out


def truncate(value: str, limit: int) -> str:
    value = value or ""
    return value if len(value) <= limit else value[: max(0, limit - 1)] + "…"


def as_int(value: Any, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    if minimum is not None:
        number = max(minimum, number)
    if maximum is not None:
        number = min(maximum, number)
    return number


def as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "si", "sì"}
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def as_str(value: Any, default: str = "", limit: int = 2000) -> str:
    if not isinstance(value, str):
        return default
    return value.strip()[:limit]


def deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, value in (override or {}).items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result
