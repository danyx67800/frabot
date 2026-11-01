from __future__ import annotations

import asyncio
import html
import logging
from datetime import datetime, timezone
from pathlib import Path

import discord

log = logging.getLogger("frabot.transcripts")

_CSS = """
body{background:#0b0d14;color:#e7e9f3;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
margin:0;padding:32px;line-height:1.5}
.wrap{max-width:860px;margin:0 auto}
h1{font-size:22px;margin:0 0 4px}
.meta{color:#9aa0b4;font-size:13px;margin-bottom:24px}
.msg{background:#151827;border:1px solid #232840;border-radius:10px;padding:12px 14px;margin:10px 0}
.head{display:flex;justify-content:space-between;gap:12px;font-size:13px;color:#9aa0b4;margin-bottom:6px}
.author{color:#c8b6ff;font-weight:600}
.content{white-space:pre-wrap;word-break:break-word}
.redacted{color:#8b90a5;font-style:italic}
.attach a{color:#7dd3fc;font-size:13px;display:block;margin-top:6px}
.embed{border-left:3px solid #7c5cff;padding:8px 12px;margin-top:8px;background:#101322}
.embed .etitle{font-weight:600;color:#fff}
.footer{margin-top:28px;color:#6f7488;font-size:12px}
"""


def _fmt_ts(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")


def _render_embed(embed: discord.Embed) -> str:
    parts = []
    if embed.title:
        parts.append(f'<div class="etitle">{html.escape(embed.title)}</div>')
    if embed.description:
        parts.append(f'<div class="content">{html.escape(embed.description)}</div>')
    for field in embed.fields:
        parts.append(
            f'<div class="content"><b>{html.escape(field.name)}</b><br>'
            f'{html.escape(field.value)}</div>'
        )
    if not parts:
        return ""
    return '<div class="embed">' + "".join(parts) + "</div>"


async def generate_transcript(directory: Path, channel: discord.TextChannel, ticket: dict) -> str:
    """Fetch history and write an HTML transcript. Returns the file name.

    Discord does not expose message text without the privileged Message Content
    intent. FraBot never requests it, so text authored by members (not by the
    bot) is unavailable and rendered as a clearly marked placeholder. Metadata,
    attachments, embeds sent by the bot and bot messages are preserved.
    """
    directory.mkdir(parents=True, exist_ok=True)
    rows: list[str] = []
    fetched = 0
    async for message in channel.history(limit=5000, oldest_first=True):
        fetched += 1
        content = message.content or ""
        has_other = bool(message.attachments or message.embeds)
        if not message.author.bot and not content.strip() and not has_other:
            body = '<div class="redacted">[testo non disponibile: FraBot non usa l\'intent Message Content]</div>'
        else:
            body = f'<div class="content">{html.escape(content)}</div>' if content else ""
        if message.embeds:
            body += "".join(_render_embed(embed) for embed in message.embeds)
        if message.attachments:
            links = "".join(
                f'<a href="{html.escape(a.url)}" rel="noreferrer noopener">📎 {html.escape(a.filename)}</a>'
                for a in message.attachments
            )
            body += f'<div class="attach">{links}</div>'
        rows.append(
            '<div class="msg">'
            f'<div class="head"><span class="author">{html.escape(str(message.author))}</span>'
            f'<span>{_fmt_ts(message.created_at)}</span></div>{body}</div>'
        )

    ticket_number = int(ticket["id"])
    title = f"Ticket #{ticket_number:04d} · {ticket.get('category_name', '')}"
    closed_at = ticket.get("closed_at") or ""
    doc = f"""<!doctype html>
<html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Transcript ticket #{ticket_number:04d}</title><style>{_CSS}</style></head>
<body><div class="wrap">
<h1>{html.escape(title)}</h1>
<div class="meta">
Aperto da <b>{html.escape(str(ticket.get('user_name', '')))}</b>
il {html.escape(str(ticket.get('created_at', '')))}
· Stato: {html.escape(str(ticket.get('status', '')))}
{('· Chiuso il ' + html.escape(closed_at)) if closed_at else ''}<br>
Motivo: {html.escape(str(ticket.get('reason') or '—'))}<br>
Messaggi nel transcript: {fetched}
</div>
{''.join(rows) if rows else '<p class="meta">Nessun messaggio.</p>'}
<div class="footer">Generato da FraBot · il testo dei membri può essere assente senza l'intent Message Content.</div>
</div></body></html>"""

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    filename = f"ticket-{ticket_number:04d}-{stamp}.html"
    path = directory / filename
    await asyncio.to_thread(path.write_text, doc, "utf-8")
    log.info("Transcript generato", extra={"ctx_ticket": ticket_number, "ctx_file": filename})
    return filename
