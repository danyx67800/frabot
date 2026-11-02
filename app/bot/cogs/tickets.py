from __future__ import annotations

import asyncio
import json
import logging
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import discord
from discord.ext import commands, tasks

from app.services.transcripts import generate_transcript
from app.utils import channel_slug, render_template, truncate, utcnow, utcnow_iso

if TYPE_CHECKING:
    from app.runtime import Runtime

log = logging.getLogger("frabot.tickets")

DEFAULT_WELCOME = (
    "Ciao {utente}, grazie per aver aperto un ticket!\n\n"
    "**Categoria:** {categoria}\n"
    "**Motivo:** {motivo}\n\n"
    "Descrivi qui il tuo problema: lo staff ti risponderà il prima possibile."
)


class TicketError(Exception):
    """An error whose message can be shown directly to a Discord user."""


def color_for(runtime: "Runtime") -> discord.Color:
    raw = runtime.config.get()["ui"]["embed_color"].lstrip("#")
    try:
        return discord.Color(int(raw, 16))
    except ValueError:
        return discord.Color(0xD2E85C)


def staff_ids(category: dict) -> list[int]:
    try:
        values = json.loads(category.get("staff_role_ids") or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    out = []
    for value in values if isinstance(values, list) else []:
        try:
            out.append(int(value))
        except (TypeError, ValueError):
            continue
    return out


def is_staff(member: discord.Member, category: dict | None) -> bool:
    if member.guild_permissions.manage_channels or member.guild_permissions.manage_guild:
        return True
    if not category:
        return False
    ids = set(staff_ids(category))
    return any(role.id in ids for role in member.roles)


def get_tickets_cog(runtime: "Runtime") -> "Tickets | None":
    bot = runtime.bot_manager.bot
    return bot.get_cog("Tickets") if bot else None  # type: ignore[return-value]


def build_panel_view(runtime: "Runtime", categories: list[dict] | None = None) -> discord.ui.View:
    if categories is None:
        categories = runtime.db.query(
            "SELECT * FROM ticket_categories ORDER BY position, id"
        )
    view = discord.ui.View(timeout=None)
    for category in categories[:25]:
        view.add_item(TicketOpenButton(runtime, category))
    return view


class TicketOpenButton(discord.ui.Button):
    def __init__(self, runtime: "Runtime", category: dict) -> None:
        super().__init__(
            label=truncate(str(category["name"]), 80),
            emoji=category.get("emoji") or None,
            style=discord.ButtonStyle.primary,
            custom_id=f"frabot:ticket:open:{category['id']}",
        )
        self.runtime = runtime
        self.category_id = int(category["id"])

    async def callback(self, interaction: discord.Interaction) -> None:
        category = self.runtime.db.one(
            "SELECT * FROM ticket_categories WHERE id = ?", (self.category_id,)
        )
        if not category:
            await interaction.response.send_message(
                "Questa categoria non è più disponibile. Aggiorna il pannello.", ephemeral=True
            )
            return
        cog = get_tickets_cog(self.runtime)
        if not cog:
            await interaction.response.send_message(
                "Il bot non è pronto. Riprova tra poco.", ephemeral=True
            )
            return
        if not self.runtime.config.get()["modules"]["tickets"]:
            await interaction.response.send_message("Il modulo Ticket è disattivato.", ephemeral=True)
            return
        if not isinstance(interaction.user, discord.Member) or not interaction.guild:
            await interaction.response.send_message(
                "I ticket si aprono solo dentro un server.", ephemeral=True
            )
            return
        cfg = self.runtime.config.get()["tickets"]
        if cfg["ask_reason"]:
            # A modal must be the first response: never defer before this.
            await interaction.response.send_modal(TicketReasonModal(self.runtime, category))
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            ticket, channel = await cog.create_ticket(
                interaction.guild, interaction.user, category, ""
            )
        except TicketError as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)
            return
        except Exception:
            log.exception("Errore imprevisto aprendo un ticket")
            await interaction.followup.send("❌ Errore imprevisto. Riprova.", ephemeral=True)
            return
        await interaction.followup.send(f"✅ Ticket creato: {channel.mention}", ephemeral=True)


class TicketReasonModal(discord.ui.Modal, title="Apri un ticket"):
    reason = discord.ui.TextInput(
        label="Motivo (facoltativo)",
        placeholder="Descrivi brevemente di cosa hai bisogno",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500,
    )

    def __init__(self, runtime: "Runtime", category: dict) -> None:
        super().__init__(custom_id=f"frabot:ticket:reason:{category['id']}")
        self.runtime = runtime
        self.category = category

    async def on_submit(self, interaction: discord.Interaction) -> None:
        cog = get_tickets_cog(self.runtime)
        if not cog or not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Contesto non valido.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            ticket, channel = await cog.create_ticket(
                interaction.guild, interaction.user, self.category, str(self.reason.value or "")
            )
        except TicketError as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)
            return
        except Exception:
            log.exception("Errore imprevisto aprendo un ticket")
            await interaction.followup.send("❌ Errore imprevisto. Riprova.", ephemeral=True)
            return
        await interaction.followup.send(
            f"✅ Ticket **#{ticket['id']:04d}** creato: {channel.mention}", ephemeral=True
        )


class TicketControlView(discord.ui.View):
    def __init__(self, runtime: "Runtime", ticket_id: int) -> None:
        super().__init__(timeout=None)
        self.add_item(CloseTicketButton(runtime, ticket_id))
        self.add_item(ClaimTicketButton(runtime, ticket_id))
        self.add_item(AddUserButton(runtime, ticket_id))


class CloseTicketButton(discord.ui.Button):
    def __init__(self, runtime: "Runtime", ticket_id: int) -> None:
        super().__init__(
            label="Chiudi",
            emoji="🔒",
            style=discord.ButtonStyle.danger,
            custom_id=f"frabot:ticket:close:{ticket_id}",
        )
        self.runtime = runtime
        self.ticket_id = ticket_id

    async def callback(self, interaction: discord.Interaction) -> None:
        ticket = self.runtime.db.one("SELECT * FROM tickets WHERE id = ?", (self.ticket_id,))
        if not ticket or ticket["status"] != "open":
            await interaction.response.send_message("Questo ticket è già chiuso.", ephemeral=True)
            return
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Azione non consentita.", ephemeral=True)
            return
        category = (
            self.runtime.db.one(
                "SELECT * FROM ticket_categories WHERE id = ?", (ticket["category_id"],)
            )
            if ticket["category_id"]
            else None
        )
        if not is_staff(interaction.user, category) and str(interaction.user.id) != ticket["user_id"]:
            await interaction.response.send_message(
                "Solo chi ha aperto il ticket o lo staff può chiuderlo.", ephemeral=True
            )
            return
        await interaction.response.send_modal(CloseTicketModal(self.runtime, self.ticket_id))


class CloseTicketModal(discord.ui.Modal, title="Chiudi il ticket"):
    reason = discord.ui.TextInput(
        label="Motivo della chiusura",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=400,
        placeholder="Facoltativo, sarà visibile nel transcript",
    )

    def __init__(self, runtime: "Runtime", ticket_id: int) -> None:
        super().__init__(custom_id=f"frabot:ticket:close_modal:{ticket_id}")
        self.runtime = runtime
        self.ticket_id = ticket_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        cog = get_tickets_cog(self.runtime)
        if not cog:
            await interaction.response.send_message("Il bot non è pronto.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        ticket = await cog.close_ticket(
            self.ticket_id,
            closed_by_id=str(interaction.user.id),
            closed_by_name=str(interaction.user),
            reason=str(self.reason.value or ""),
        )
        if not ticket:
            await interaction.followup.send("Il ticket era già chiuso.", ephemeral=True)
            return
        await interaction.followup.send(
            f"✅ Ticket **#{self.ticket_id:04d}** chiuso. Il transcript è stato salvato.",
            ephemeral=True,
        )


class ClaimTicketButton(discord.ui.Button):
    def __init__(self, runtime: "Runtime", ticket_id: int) -> None:
        super().__init__(
            label="Prendi in carico",
            emoji="🙋",
            style=discord.ButtonStyle.success,
            custom_id=f"frabot:ticket:claim:{ticket_id}",
        )
        self.runtime = runtime
        self.ticket_id = ticket_id

    async def callback(self, interaction: discord.Interaction) -> None:
        ticket = self.runtime.db.one("SELECT * FROM tickets WHERE id = ?", (self.ticket_id,))
        if not ticket or ticket["status"] != "open":
            await interaction.response.send_message("Questo ticket è chiuso.", ephemeral=True)
            return
        category = (
            self.runtime.db.one(
                "SELECT * FROM ticket_categories WHERE id = ?", (ticket["category_id"],)
            )
            if ticket["category_id"]
            else None
        )
        if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user, category):
            await interaction.response.send_message(
                "Solo lo staff può prendere in carico un ticket.", ephemeral=True
            )
            return
        self.runtime.db.execute(
            """UPDATE tickets SET claimed_by = ?, claimed_by_name = ?, last_activity = ?
               WHERE id = ? AND status = 'open'""",
            (str(interaction.user.id), str(interaction.user), utcnow_iso(), self.ticket_id),
        )
        await interaction.response.send_message(
            f"🙋 Ticket preso in carico da {interaction.user.mention}.", ephemeral=False
        )


class AddUserSelect(discord.ui.UserSelect):
    def __init__(self, runtime: "Runtime", ticket: dict, channel: discord.TextChannel) -> None:
        super().__init__(placeholder="Scegli l'utente da aggiungere", min_values=1, max_values=1)
        self.runtime = runtime
        self.ticket = ticket
        self.channel = channel

    async def callback(self, interaction: discord.Interaction) -> None:
        user = self.values[0]
        try:
            await self.channel.set_permissions(
                user,
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "Non ho i permessi per aggiungere l'utente (controlla la gerarchia dei ruoli).",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            f"✅ {user.mention} è stato aggiunto al ticket.", ephemeral=True
        )


class AddUserView(discord.ui.View):
    def __init__(self, runtime: "Runtime", ticket: dict, channel: discord.TextChannel) -> None:
        super().__init__(timeout=120)
        self.add_item(AddUserSelect(runtime, ticket, channel))


class AddUserButton(discord.ui.Button):
    def __init__(self, runtime: "Runtime", ticket_id: int) -> None:
        super().__init__(
            label="Aggiungi utente",
            emoji="➕",
            style=discord.ButtonStyle.secondary,
            custom_id=f"frabot:ticket:add:{ticket_id}",
        )
        self.runtime = runtime
        self.ticket_id = ticket_id

    async def callback(self, interaction: discord.Interaction) -> None:
        ticket = self.runtime.db.one("SELECT * FROM tickets WHERE id = ?", (self.ticket_id,))
        if not ticket or ticket["status"] != "open":
            await interaction.response.send_message("Questo ticket è chiuso.", ephemeral=True)
            return
        category = (
            self.runtime.db.one(
                "SELECT * FROM ticket_categories WHERE id = ?", (ticket["category_id"],)
            )
            if ticket["category_id"]
            else None
        )
        if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user, category):
            await interaction.response.send_message(
                "Solo lo staff può aggiungere utenti al ticket.", ephemeral=True
            )
            return
        channel = self.runtime.bot_manager.bot.get_channel(int(ticket["channel_id"]))
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("Canale del ticket non disponibile.", ephemeral=True)
            return
        await interaction.response.send_message(
            "Scegli l'utente da aggiungere:", view=AddUserView(self.runtime, ticket, channel),
            ephemeral=True,
        )


class Tickets(commands.Cog):
    def __init__(self, bot) -> None:
        self.bot = bot
        self.runtime: "Runtime" = bot.runtime
        self.panel_view: discord.ui.View | None = None
        self.control_views: dict[int, TicketControlView] = {}
        self._close_lock = asyncio.Lock()
        self._register_persistent_views()

    def _register_persistent_views(self) -> None:
        self.panel_view = build_panel_view(self.runtime)
        self.bot.add_view(self.panel_view)
        rows = self.runtime.db.query("SELECT id FROM tickets WHERE status = 'open'")
        for row in rows:
            view = TicketControlView(self.runtime, int(row["id"]))
            self.control_views[int(row["id"])] = view
            self.bot.add_view(view)
        log.info(
            "View persistenti registrate",
            extra={"ctx_open_tickets": len(rows), "ctx_categories": len(self.panel_view.children)},
        )

    def refresh_persistent_views(self) -> None:
        """Re-register the panel buttons after categories change.

        The published message is not edited here; the admin republishes it so a
        component batch never exceeds Discord's limits unexpectedly.
        """
        new_view = build_panel_view(self.runtime)
        if self.panel_view:
            try:
                self.bot.remove_view(self.panel_view)
            except Exception:
                pass
        self.panel_view = new_view
        self.bot.add_view(new_view)

    async def cog_load(self) -> None:
        self.auto_close_loop.start()

    async def cog_unload(self) -> None:
        self.auto_close_loop.cancel()

    # -- creation ---------------------------------------------------------
    async def create_ticket(
        self,
        guild: discord.Guild,
        member: discord.Member,
        category: dict,
        reason: str,
    ) -> tuple[dict, discord.TextChannel]:
        cfg = self.runtime.config.get()
        if str(guild.id) != cfg["discord"]["guild_id"]:
            raise TicketError("Questo server non è quello configurato nel pannello.")
        open_count = self.runtime.db.one(
            "SELECT COUNT(*) AS n FROM tickets WHERE guild_id = ? AND user_id = ? AND status = 'open'",
            (str(guild.id), str(member.id)),
        )
        limit = int(cfg["tickets"]["max_open_per_user"])
        if open_count and int(open_count["n"]) >= limit:
            raise TicketError(f"Hai già {open_count['n']} ticket aperti (massimo {limit}).")

        ticket_id = int(
            self.runtime.db.execute(
                """INSERT INTO tickets(guild_id, user_id, user_name, category_id, category_name,
                                       reason, status, created_at, last_activity)
                   VALUES(?, ?, ?, ?, ?, ?, 'open', ?, ?)""",
                (
                    str(guild.id), str(member.id), str(member),
                    int(category["id"]), str(category["name"]), truncate(reason, 500),
                    utcnow_iso(), utcnow_iso(),
                ),
            )
        )

        parent = None
        discord_category_id = category.get("discord_category_id")
        if discord_category_id:
            parent = guild.get_channel(int(discord_category_id))
            if not isinstance(parent, discord.CategoryChannel):
                self.runtime.db.execute("DELETE FROM tickets WHERE id = ?", (ticket_id,))
                raise TicketError("La categoria Discord configurata non esiste più.")

        overwrites: dict = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True, attach_files=True
            ),
        }
        if guild.me:
            overwrites[guild.me] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True,
                attach_files=True, embed_links=True, manage_channels=True,
            )
        for role_id in staff_ids(category):
            role = guild.get_role(role_id)
            if role:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, read_message_history=True, attach_files=True
                )

        channel_name = f"ticket-{ticket_id:04d}-{channel_slug(member.display_name)}"
        try:
            channel = await guild.create_text_channel(
                channel_name,
                category=parent,
                overwrites=overwrites,
                topic=f"Ticket #{ticket_id:04d} · {member} · {category['name']}",
                reason=f"Ticket aperto da {member}",
            )
        except discord.Forbidden:
            self.runtime.db.execute("DELETE FROM tickets WHERE id = ?", (ticket_id,))
            raise TicketError(
                "Non ho i permessi per creare il canale. Controlla i permessi del bot "
                "(Gestisci canali e Gestisci ruoli) e che il suo ruolo sia in alto."
            )
        except discord.HTTPException as exc:
            self.runtime.db.execute("DELETE FROM tickets WHERE id = ?", (ticket_id,))
            log.warning("Creazione canale ticket fallita: %s", exc)
            raise TicketError("Discord ha rifiutato la creazione del canale. Riprova.")
        self.runtime.db.execute(
            "UPDATE tickets SET channel_id = ? WHERE id = ?", (str(channel.id), ticket_id)
        )

        welcome = category.get("welcome_message") or DEFAULT_WELCOME
        welcome_text = render_template(
            welcome,
            {
                "utente": member.mention,
                "nome": member.display_name,
                "categoria": category["name"],
                "numero": f"{ticket_id:04d}",
                "motivo": reason or "—",
                "server": guild.name,
            },
        )
        embed = discord.Embed(
            title=f"Ticket #{ticket_id:04d} · {category['name']}",
            description=truncate(welcome_text, 4000),
            color=color_for(self.runtime),
        )
        embed.add_field(name="Utente", value=member.mention, inline=True)
        embed.add_field(name="Categoria", value=str(category["name"]), inline=True)
        if reason:
            embed.add_field(name="Motivo", value=truncate(reason, 1000), inline=False)
        embed.set_footer(text="Usa i pulsanti qui sotto · FraBot")
        view = TicketControlView(self.runtime, ticket_id)
        self.control_views[ticket_id] = view
        self.bot.add_view(view)
        message = await channel.send(
            content=f"{member.mention} · <@&{staff_ids(category)[0]}>" if staff_ids(category) else member.mention,
            embed=embed,
            view=view,
            allowed_mentions=discord.AllowedMentions(users=True),
        )
        self.runtime.db.execute(
            "UPDATE tickets SET message_id = ? WHERE id = ?", (str(message.id), ticket_id)
        )
        ticket = self.runtime.db.one("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
        log.info(
            "Ticket aperto",
            extra={"ctx_ticket": ticket_id, "ctx_user": str(member.id), "ctx_channel": str(channel.id)},
        )
        return ticket, channel  # type: ignore[return-value]

    # -- closing ----------------------------------------------------------
    async def close_ticket(
        self,
        ticket_id: int,
        closed_by_id: str | None,
        closed_by_name: str,
        reason: str,
    ) -> dict | None:
        async with self._close_lock:
            ticket = self.runtime.db.one("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
            if not ticket or ticket["status"] != "open":
                return None
            guild = self.bot.get_guild(int(ticket["guild_id"]))
            channel = None
            if ticket["channel_id"]:
                channel = self.bot.get_channel(int(ticket["channel_id"]))
                if channel is None and guild:
                    try:
                        channel = await guild.fetch_channel(int(ticket["channel_id"]))
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                        channel = None

            transcript_name = None
            if isinstance(channel, discord.TextChannel):
                try:
                    transcript_name = await generate_transcript(
                        self.runtime.transcripts_dir, channel, ticket
                    )
                except Exception:
                    log.exception("Transcript non generato per il ticket %s", ticket_id)

            closed_at = utcnow_iso()
            self.runtime.db.execute(
                """UPDATE tickets SET status = 'closed', closed_at = ?, closed_by = ?,
                       close_reason = ?, transcript = ?, last_activity = ? WHERE id = ?""",
                (closed_at, closed_by_name, truncate(reason, 500), transcript_name, closed_at, ticket_id),
            )
            ticket.update(
                status="closed", closed_at=closed_at, closed_by=closed_by_name,
                close_reason=truncate(reason, 500), transcript=transcript_name,
            )
            view = self.control_views.pop(ticket_id, None)
            if view:
                try:
                    self.bot.remove_view(view)
                except Exception:
                    pass

            await self._notify_closed(ticket)
            if isinstance(channel, discord.TextChannel):
                asyncio.create_task(self._close_channel(channel, ticket_id))
            log.info("Ticket chiuso", extra={"ctx_ticket": ticket_id, "ctx_by": closed_by_name})
            return ticket

    async def _notify_closed(self, ticket: dict) -> None:
        cfg = self.runtime.config.get()
        number = int(ticket["id"])
        log_channel = None
        if cfg["tickets"]["log_channel_id"]:
            log_channel = self.bot.get_channel(int(cfg["tickets"]["log_channel_id"]))
            if log_channel is None:
                try:
                    log_channel = await self.bot.fetch_channel(int(cfg["tickets"]["log_channel_id"]))
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    log_channel = None
        path = (
            self.runtime.transcripts_dir / ticket["transcript"]
            if ticket.get("transcript")
            else None
        )
        embed = discord.Embed(
            title=f"Ticket #{number:04d} chiuso",
            color=discord.Color.dark_gray(),
            timestamp=utcnow(),
        )
        embed.add_field(name="Utente", value=f"<@{ticket['user_id']}>", inline=True)
        embed.add_field(name="Categoria", value=str(ticket["category_name"]), inline=True)
        embed.add_field(name="Chiuso da", value=str(ticket.get("closed_by") or "—"), inline=True)
        embed.add_field(name="Motivo", value=truncate(str(ticket.get("close_reason") or "—"), 1000), inline=False)
        if path and path.exists():
            embed.set_footer(text="Transcript allegato")
        if isinstance(log_channel, discord.TextChannel):
            try:
                if path and path.exists():
                    await log_channel.send(
                        embed=embed, file=discord.File(path, filename=path.name)
                    )
                else:
                    await log_channel.send(embed=embed)
            except discord.HTTPException:
                log.warning("Invio transcript al canale log fallito", extra={"ctx_ticket": number})

        try:
            user = self.bot.get_user(int(ticket["user_id"])) or await self.bot.fetch_user(
                int(ticket["user_id"])
            )
            dm = discord.Embed(
                title=f"Ticket #{number:04d} chiuso",
                description=f"Motivo: {ticket.get('close_reason') or '—'}",
                color=discord.Color.dark_gray(),
                timestamp=utcnow(),
            )
            if path and path.exists():
                await user.send(embed=dm, file=discord.File(path, filename=path.name))
            else:
                await user.send(embed=dm)
        except discord.Forbidden:
            log.info("DM di chiusura non recapitato (DM chiusi)", extra={"ctx_ticket": number})
        except Exception:
            log.warning("DM di chiusura non recapitato", exc_info=True, extra={"ctx_ticket": number})

    async def _close_channel(self, channel: discord.TextChannel, ticket_id: int) -> None:
        try:
            await channel.send("🔒 Ticket chiuso. Questo canale verrà eliminato tra pochi secondi.")
            await asyncio.sleep(3)
            await channel.delete(reason=f"Ticket #{ticket_id:04d} chiuso")
        except discord.HTTPException:
            pass
        except Exception:
            log.warning("Eliminazione canale ticket fallita", exc_info=True)

    # -- panel ------------------------------------------------------------
    async def publish_panel(self) -> dict:
        cfg = self.runtime.config.get()
        guild_id = cfg["discord"]["guild_id"]
        channel_id = cfg["tickets"]["panel_channel_id"]
        if not guild_id or not channel_id:
            raise TicketError("Configura il server e il canale del pannello ticket.")
        guild = self.bot.get_guild(int(guild_id))
        if not guild:
            raise TicketError("Il bot non è nel server configurato.")
        channel = guild.get_channel(int(channel_id)) or await guild.fetch_channel(int(channel_id))
        if not isinstance(channel, discord.TextChannel):
            raise TicketError("Il canale scelto non è un canale testuale.")
        categories = self.runtime.db.query(
            "SELECT * FROM ticket_categories ORDER BY position, id"
        )
        view = build_panel_view(self.runtime, categories)
        embed = discord.Embed(
            title="🎫 Supporto · Apri un ticket",
            description=(
                "Scegli la categoria più adatta. Verrà creato un canale privato "
                "visibile solo a te e allo staff.\n\n"
                + (
                    "\n".join(
                        f"{c.get('emoji') or '•'} **{c['name']}**"
                        + (f" — {truncate(c['description'], 120)}" if c.get("description") else "")
                        for c in categories
                    )
                    or "_Nessuna categoria configurata. Aggiungine una dal pannello._"
                )
            ),
            color=color_for(self.runtime),
        )
        embed.set_footer(text="FraBot · Ticket")

        message = None
        panel_message_id = cfg["tickets"]["panel_message_id"]
        panel_channel_id = cfg["tickets"]["panel_channel_id"]
        if panel_message_id:
            try:
                message = await channel.fetch_message(int(panel_message_id))
                await message.edit(embed=embed, view=view)
            except (discord.NotFound, discord.Forbidden):
                message = None
        if message is None:
            message = await channel.send(embed=embed, view=view)

        # If the panel moved to another channel, remove the stale copy.
        old_channel_id = (panel_channel_id or "") if panel_message_id else ""
        if old_channel_id and old_channel_id != str(channel.id):
            old_channel = self.bot.get_channel(int(old_channel_id))
            if isinstance(old_channel, discord.TextChannel):
                try:
                    old_message = await old_channel.fetch_message(int(panel_message_id))
                    await old_message.delete()
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass

        if self.panel_view:
            try:
                self.bot.remove_view(self.panel_view)
            except Exception:
                pass
        self.panel_view = view
        self.bot.add_view(view)
        self.runtime.config.patch(
            "tickets",
            {"panel_channel_id": str(channel.id), "panel_message_id": str(message.id)},
        )
        log.info("Pannello ticket pubblicato", extra={"ctx_message": str(message.id)})
        return {"message_id": str(message.id), "channel_id": str(channel.id), "url": message.jump_url}

    async def send_test_message(self, channel_id: str) -> dict:
        cfg = self.runtime.config.get()
        guild = self.bot.get_guild(int(cfg["discord"]["guild_id"]))
        if not guild:
            raise TicketError("Il bot non è nel server configurato.")
        channel = guild.get_channel(int(channel_id)) or await guild.fetch_channel(int(channel_id))
        if not isinstance(channel, discord.TextChannel):
            raise TicketError("Il canale scelto non è un canale testuale.")
        embed = discord.Embed(
            title="✅ FraBot è operativo",
            description="Questo è il messaggio di prova inviato dalla configurazione guidata.",
            color=color_for(self.runtime),
            timestamp=utcnow(),
        )
        embed.set_footer(text="FraBot")
        message = await channel.send(embed=embed)
        return {"message_id": str(message.id), "channel_id": str(channel.id), "url": message.jump_url}

    @tasks.loop(minutes=10)
    async def auto_close_loop(self) -> None:
        if not self.bot.is_ready():
            return
        cfg = self.runtime.config.get()
        if not cfg["modules"]["tickets"]:
            return
        hours = int(cfg["tickets"]["auto_close_hours"])
        if hours <= 0:
            return
        cutoff = (utcnow() - timedelta(hours=hours)).isoformat(timespec="seconds")
        rows = self.runtime.db.query(
            "SELECT id FROM tickets WHERE status = 'open' AND last_activity < ?", (cutoff,)
        )
        for row in rows:
            log.info("Chiusura automatica ticket", extra={"ctx_ticket": row["id"]})
            await self.close_ticket(
                int(row["id"]), None, "Chiusura automatica",
                f"Nessuna attività da {hours} ore.",
            )

    @auto_close_loop.before_loop
    async def _before_auto_close(self) -> None:
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild or not message.channel:
            return
        self.runtime.db.execute(
            "UPDATE tickets SET last_activity = ? WHERE channel_id = ? AND status = 'open'",
            (utcnow_iso(), str(message.channel.id)),
        )


async def setup(bot) -> None:
    await bot.add_cog(Tickets(bot))
