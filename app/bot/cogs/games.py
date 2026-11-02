from __future__ import annotations

import json
import random
import time
import uuid
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from app.utils import truncate, utcnow, utcnow_iso

if TYPE_CHECKING:
    from app.runtime import Runtime

GAMES = {
    "tris": "Tris",
    "indovina": "Indovina il numero",
    "quiz": "Quiz",
    "rps": "Pietra-carta-forbici",
    "dado": "Dado",
    "moneta": "Lancio di moneta",
    "slot": "Slot",
}

RPS_CHOICES = [("sasso", "Sasso 🪨"), ("carta", "Carta 📄"), ("forbici", "Forbici ✂️")]
RPS_BEATS = {"sasso": "forbici", "carta": "sasso", "forbici": "carta"}
RPS_EMOJI = {"sasso": "🪨", "carta": "📄", "forbici": "✂️"}
SLOT_SYMBOLS = ["🍒", "🍋", "🍇", "⭐", "7️⃣", "💎"]
WIN_LINES = [
    (0, 1, 2), (3, 4, 5), (6, 7, 8),
    (0, 3, 6), (1, 4, 7), (2, 5, 8),
    (0, 4, 8), (2, 4, 6),
]


def _color(runtime: "Runtime") -> discord.Color:
    try:
        return discord.Color(int(runtime.config.get()["ui"]["embed_color"].lstrip("#"), 16))
    except ValueError:
        return discord.Color(0xD2E85C)


def _record(
    runtime: "Runtime",
    guild_id: int | str,
    user: discord.abc.User,
    game: str,
    won: bool,
    coins: int = 0,
) -> None:
    name = str(user)
    runtime.db.execute(
        """INSERT INTO game_stats(guild_id, user_id, user_name, game, wins, plays, coins)
           VALUES(?, ?, ?, ?, ?, 1, ?)
           ON CONFLICT(guild_id, user_id, game) DO UPDATE SET
               wins = wins + excluded.wins, plays = plays + 1,
               coins = coins + excluded.coins, user_name = excluded.user_name""",
        (str(guild_id), str(user.id), name, game, 1 if won else 0, coins),
    )
    if coins:
        runtime.db.execute(
            """INSERT INTO economy(guild_id, user_id, user_name, balance)
               VALUES(?, ?, ?, ?)
               ON CONFLICT(guild_id, user_id) DO UPDATE SET
                   balance = balance + excluded.balance, user_name = excluded.user_name""",
            (str(guild_id), str(user.id), name, coins),
        )


class GuessModal(discord.ui.Modal, title="Il tuo tentativo"):
    guess = discord.ui.TextInput(label="Numero (1-100)", min_length=1, max_length=3)

    def __init__(self, game: "GuessGameView") -> None:
        super().__init__(custom_id=f"frabot:guess:{uuid.uuid4().hex[:8]}")
        self.game = game

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            value = int(str(self.guess.value))
        except ValueError:
            await interaction.response.send_message("Inserisci un numero valido.", ephemeral=True)
            return
        await self.game.submit(interaction, value)


class GuessGameView(discord.ui.View):
    def __init__(self, runtime: "Runtime", user_id: int, reward: int) -> None:
        super().__init__(timeout=180)
        self.runtime = runtime
        self.user_id = user_id
        self.target = random.randint(1, 100)
        self.reward = reward
        self.attempts = 7
        self.finished = False
        self.message: discord.Message | None = None

    def embed(self, feedback: str = "") -> discord.Embed:
        embed = discord.Embed(
            title="🎲 Indovina il numero",
            description=feedback or "Ho scelto un numero tra **1 e 100**. Hai 7 tentativi!",
            color=_color(self.runtime),
        )
        embed.add_field(name="Tentativi rimasti", value=str(self.attempts), inline=True)
        embed.set_footer(text="FraBot · Mini giochi")
        return embed

    @discord.ui.button(label="Fai un tentativo", style=discord.ButtonStyle.primary, emoji="🔢")
    async def attempt(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Non è la tua partita.", ephemeral=True)
            return
        if self.finished:
            await interaction.response.send_message("Partita conclusa.", ephemeral=True)
            return
        await interaction.response.send_modal(GuessModal(self))

    async def submit(self, interaction: discord.Interaction, value: int) -> None:
        if self.finished:
            await interaction.response.send_message("Partita conclusa.", ephemeral=True)
            return
        if value < 1 or value > 100:
            await interaction.response.send_message("Il numero deve essere tra 1 e 100.", ephemeral=True)
            return
        self.attempts -= 1
        if value == self.target:
            self.finished = True
            self.attempt.disabled = True
            _record(self.runtime, interaction.guild_id, interaction.user, "indovina", True, self.reward)
            text = f"🎉 **Esatto!** Era proprio **{self.target}**."
            if self.reward and self.runtime.config.get()["games"]["economy_enabled"]:
                text += f"\nHai guadagnato **{self.reward}** monete."
            await interaction.response.edit_message(embed=self.embed(text), view=self)
            return
        if self.attempts <= 0:
            self.finished = True
            self.attempt.disabled = True
            _record(self.runtime, interaction.guild_id, interaction.user, "indovina", False)
            await interaction.response.edit_message(
                embed=self.embed(f"❌ Tentativi esauriti. Il numero era **{self.target}**."),
                view=self,
            )
            return
        hint = "troppo basso" if value < self.target else "troppo alto"
        await interaction.response.edit_message(
            embed=self.embed(f"**{value}** è {hint}. Ti restano **{self.attempts}** tentativi."),
            view=self,
        )

    async def on_timeout(self) -> None:
        self.finished = True
        if self.message:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass


class QuizView(discord.ui.View):
    def __init__(
        self,
        runtime: "Runtime",
        question: dict,
        options: list[str],
        reward: int,
    ) -> None:
        super().__init__(timeout=90)
        self.runtime = runtime
        self.question = question
        self.options = options
        self.answer = int(question["answer"])
        self.reward = reward
        self.finished = False
        token = uuid.uuid4().hex[:8]
        for index, _ in enumerate(options):
            self.add_item(QuizAnswerButton(index, token))

    def embed(self, result: str = "") -> discord.Embed:
        description = f"**{self.question['question']}**\n\n"
        description += "\n".join(
            f"`{chr(65 + i)}` {truncate(option, 200)}" for i, option in enumerate(self.options)
        )
        if result:
            description += f"\n\n{result}"
        embed = discord.Embed(
            title=f"🧠 Quiz · {self.question['category']}",
            description=description,
            color=_color(self.runtime),
        )
        embed.set_footer(text="FraBot · Rispondi con i pulsanti")
        return embed


class QuizAnswerButton(discord.ui.Button):
    def __init__(self, index: int, token: str) -> None:
        super().__init__(
            label=chr(65 + index),
            style=discord.ButtonStyle.primary,
            custom_id=f"frabot:quiz:{token}:{index}",
        )
        self.index = index

    async def callback(self, interaction: discord.Interaction) -> None:
        view: QuizView = self.view  # type: ignore[assignment]
        if view.finished:
            await interaction.response.send_message("Quiz già concluso.", ephemeral=True)
            return
        view.finished = True
        for child in view.children:
            child.disabled = True
        correct = self.index == view.answer
        result = (
            f"✅ Risposta corretta: **{chr(65 + view.answer)}**."
            if correct
            else f"❌ Sbagliato. La risposta corretta era **{chr(65 + view.answer)}**."
        )
        if correct and view.reward and view.runtime.config.get()["games"]["economy_enabled"]:
            result += f"\nHai guadagnato **{view.reward}** monete."
            _record(view.runtime, interaction.guild_id, interaction.user, "quiz", True, view.reward)
        else:
            _record(view.runtime, interaction.guild_id, interaction.user, "quiz", correct)
        await interaction.response.edit_message(embed=view.embed(result), view=view)


class TrisButton(discord.ui.Button):
    def __init__(self, game: "TrisView", index: int) -> None:
        super().__init__(
            label="·",
            style=discord.ButtonStyle.secondary,
            custom_id=f"frabot:tris:{game.token}:{index}",
            row=index // 3,
        )
        self.game = game
        self.index = index

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.game.play(interaction, self)


class TrisView(discord.ui.View):
    def __init__(self, runtime: "Runtime", players: list[discord.Member], reward: int) -> None:
        super().__init__(timeout=300)
        self.runtime = runtime
        self.players = players
        self.reward = reward
        self.token = uuid.uuid4().hex[:8]
        self.board: list[str | None] = [None] * 9
        self.turn = 0
        self.finished = False
        self.message: discord.Message | None = None
        for index in range(9):
            self.add_item(TrisButton(self, index))

    @property
    def marks(self) -> tuple[str, str]:
        return "X", "O"

    def embed(self, note: str = "") -> discord.Embed:
        mark = self.marks[self.turn]
        embed = discord.Embed(
            title="❌⭕ Tris",
            description=(
                f"{self.players[0].mention} (**X**) vs {self.players[1].mention} (**O**)\n\n"
                + (f"**Turno di {self.players[self.turn].mention} ({mark})**" if not self.finished else "")
                + (f"\n\n{note}" if note else "")
            ),
            color=_color(self.runtime),
        )
        embed.set_footer(text="FraBot · Mini giochi")
        return embed

    def winner(self) -> tuple[str, int] | None:
        for a, b, c in WIN_LINES:
            if self.board[a] and self.board[a] == self.board[b] == self.board[c]:
                mark = str(self.board[a])
                return mark, 0 if mark == self.marks[0] else 1
        return None

    async def play(self, interaction: discord.Interaction, button: TrisButton) -> None:
        if interaction.user.id not in [p.id for p in self.players]:
            await interaction.response.send_message("Stai solo guardando questa partita.", ephemeral=True)
            return
        if self.finished:
            await interaction.response.send_message("Partita già conclusa.", ephemeral=True)
            return
        if interaction.user.id != self.players[self.turn].id:
            await interaction.response.send_message("Non è il tuo turno.", ephemeral=True)
            return
        if self.board[button.index] is not None:
            await interaction.response.send_message("Cella già occupata.", ephemeral=True)
            return
        mark = self.marks[self.turn]
        self.board[button.index] = mark
        button.label = mark
        button.style = discord.ButtonStyle.success if mark == "X" else discord.ButtonStyle.danger
        button.disabled = True

        win = self.winner()
        if win:
            self.finished = True
            winner_mark, winner_index = win
            winner = self.players[winner_index]
            for child in self.children:
                child.disabled = True
            _record(self.runtime, interaction.guild_id, winner, "tris", True, self.reward)
            loser = self.players[1 - winner_index]
            _record(self.runtime, interaction.guild_id, loser, "tris", False)
            note = f"🏆 Vittoria di {winner.mention}!"
            if self.reward and self.runtime.config.get()["games"]["economy_enabled"]:
                note += f" +{self.reward} monete."
            await interaction.response.edit_message(embed=self.embed(note), view=self)
            return
        if all(cell is not None for cell in self.board):
            self.finished = True
            for child in self.children:
                child.disabled = True
            for player in self.players:
                _record(self.runtime, interaction.guild_id, player, "tris", False)
            await interaction.response.edit_message(embed=self.embed("🤝 Pareggio!"), view=self)
            return
        self.turn = 1 - self.turn
        await interaction.response.edit_message(embed=self.embed(), view=self)

    async def on_timeout(self) -> None:
        self.finished = True
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class Games(commands.Cog):
    def __init__(self, bot) -> None:
        self.bot = bot
        self.runtime: "Runtime" = bot.runtime
        self._cooldowns: dict[tuple[int, str], float] = {}

    # -- helpers ----------------------------------------------------------
    def _item(self, game: str) -> dict:
        return self.runtime.config.get()["games"]["items"][game]

    async def _guard(self, interaction: discord.Interaction, game: str) -> bool:
        cfg = self.runtime.config.get()
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Questo comando funziona solo in un server.", ephemeral=True)
            return False
        if not cfg["modules"]["games"]:
            await interaction.response.send_message("I mini giochi sono disattivati.", ephemeral=True)
            return False
        if str(interaction.guild.id) != cfg["discord"]["guild_id"]:
            await interaction.response.send_message("Questo server non è configurato.", ephemeral=True)
            return False
        item = cfg["games"]["items"][game]
        if not item["enabled"]:
            await interaction.response.send_message(f"**{GAMES[game]}** è disattivato.", ephemeral=True)
            return False
        channels = item.get("channels") or []
        if channels and str(interaction.channel_id) not in channels:
            await interaction.response.send_message(
                f"**{GAMES[game]}** non è abilitato in questo canale.", ephemeral=True
            )
            return False
        remaining = self._cooldown_remaining(interaction.user.id, game, item["cooldown"])
        if remaining > 0:
            await interaction.response.send_message(
                f"⏳ Attendi ancora **{remaining}s** prima di rigiocare a {GAMES[game]}.",
                ephemeral=True,
            )
            return False
        self._cooldowns[(interaction.user.id, game)] = time.monotonic()
        return True

    async def _guard_economy(self, interaction: discord.Interaction) -> bool:
        cfg = self.runtime.config.get()
        if not interaction.guild:
            await interaction.response.send_message("Questo comando funziona solo in un server.", ephemeral=True)
            return False
        if not cfg["modules"]["games"]:
            await interaction.response.send_message("I mini giochi sono disattivati.", ephemeral=True)
            return False
        if not cfg["games"]["economy_enabled"]:
            await interaction.response.send_message("L'economia a monete è disattivata.", ephemeral=True)
            return False
        return True

    def _cooldown_remaining(self, user_id: int, game: str, cooldown: int) -> int:
        if cooldown <= 0:
            return 0
        last = self._cooldowns.get((user_id, game))
        if not last:
            return 0
        return max(0, int(cooldown - (time.monotonic() - last)))

    async def quiz_category_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        rows = self.runtime.db.query(
            "SELECT DISTINCT category FROM quiz_questions WHERE category LIKE ? ORDER BY category LIMIT 25",
            (f"%{current}%",),
        )
        return [app_commands.Choice(name=row["category"][:100], value=row["category"]) for row in rows]

    # -- commands ---------------------------------------------------------
    @app_commands.command(name="tris", description="Sfida un altro utente a tris.")
    @app_commands.describe(avversario="L'utente da sfidare")
    async def tris(self, interaction: discord.Interaction, avversario: discord.Member) -> None:
        if not await self._guard(interaction, "tris"):
            return
        if avversario.id == interaction.user.id:
            await interaction.response.send_message("Non puoi sfidare te stesso.", ephemeral=True)
            return
        if avversario.bot:
            await interaction.response.send_message("Non puoi sfidare un bot.", ephemeral=True)
            return
        if not isinstance(interaction.user, discord.Member):
            return
        item = self._item("tris")
        view = TrisView(self.runtime, [interaction.user, avversario], item["reward"])
        await interaction.response.send_message(
            content=f"❌ {interaction.user.mention} sfida {avversario.mention} a tris!",
            embed=view.embed(),
            view=view,
            allowed_mentions=discord.AllowedMentions(users=True),
        )
        view.message = await interaction.original_response()

    @app_commands.command(name="indovina", description="Indovina un numero da 1 a 100.")
    async def indovina(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction, "indovina"):
            return
        item = self._item("indovina")
        view = GuessGameView(self.runtime, interaction.user.id, item["reward"])
        await interaction.response.send_message(embed=view.embed(), view=view, ephemeral=True)
        view.message = await interaction.original_response()

    @app_commands.command(name="quiz", description="Rispondi a una domanda a scelta multipla.")
    @app_commands.describe(categoria="Filtra per categoria (facoltativo)")
    @app_commands.autocomplete(categoria=quiz_category_autocomplete)
    async def quiz(self, interaction: discord.Interaction, categoria: str | None = None) -> None:
        if not await self._guard(interaction, "quiz"):
            return
        if categoria:
            row = self.runtime.db.one(
                "SELECT * FROM quiz_questions WHERE category = ? ORDER BY RANDOM() LIMIT 1",
                (categoria,),
            )
        else:
            row = self.runtime.db.one("SELECT * FROM quiz_questions ORDER BY RANDOM() LIMIT 1")
        if not row:
            await interaction.response.send_message(
                "Nessuna domanda configurata. Aggiungine dal pannello.", ephemeral=True
            )
            return
        try:
            options = json.loads(row["options"])
        except (TypeError, json.JSONDecodeError):
            options = []
        options = [str(o) for o in options if str(o).strip()][:4]
        if len(options) < 2 or not (0 <= int(row["answer"]) < len(options)):
            await interaction.response.send_message("Domanda non valida. Correggila dal pannello.", ephemeral=True)
            return
        item = self._item("quiz")
        view = QuizView(self.runtime, row, options, item["reward"])
        await interaction.response.send_message(embed=view.embed(), view=view)

    @app_commands.command(name="rps", description="Sfida il bot a pietra, carta o forbici.")
    @app_commands.describe(scelta="La tua mossa")
    @app_commands.choices(scelta=[app_commands.Choice(name=label, value=value) for value, label in RPS_CHOICES])
    async def rps(self, interaction: discord.Interaction, scelta: str) -> None:
        if not await self._guard(interaction, "rps"):
            return
        player = scelta
        bot_choice = random.choice(list(RPS_BEATS))
        if player == bot_choice:
            result, won = "🤝 Pareggio!", False
        elif RPS_BEATS[player] == bot_choice:
            result, won = "🏆 Hai vinto!", True
        else:
            result, won = "😅 Hai perso.", False
        item = self._item("rps")
        coins = item["reward"] if won else 0
        _record(self.runtime, interaction.guild_id, interaction.user, "rps", won, coins)
        embed = discord.Embed(
            title="✂️ Pietra, carta, forbici",
            description=(
                f"Tu: {RPS_EMOJI[player]} **{player}**\n"
                f"Bot: {RPS_EMOJI[bot_choice]} **{bot_choice}**\n\n{result}"
            ),
            color=_color(self.runtime),
        )
        if coins and self.runtime.config.get()["games"]["economy_enabled"]:
            embed.add_field(name="Premio", value=f"+{coins} monete", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="dado", description="Lancia un dado.")
    @app_commands.describe(facce="Numero di facce (2-100)", numero="Numero su cui punti (facoltativo)")
    async def dado(
        self, interaction: discord.Interaction, facce: int = 6, numero: int | None = None
    ) -> None:
        if not await self._guard(interaction, "dado"):
            return
        facce = max(2, min(100, facce))
        if numero is not None and not (1 <= numero <= facce):
            await interaction.response.send_message(f"Scegli un numero tra 1 e {facce}.", ephemeral=True)
            return
        result = random.randint(1, facce)
        won = numero is not None and numero == result
        item = self._item("dado")
        coins = item["reward"] if won else 0
        _record(self.runtime, interaction.guild_id, interaction.user, "dado", won, coins)
        desc = f"🎲 **{result}** (dado a {facce} facce)"
        if numero is not None:
            desc += f"\nHai puntato su **{numero}**: " + ("vinto! 🎉" if won else "non è uscito.")
        embed = discord.Embed(title="Lancio di dado", description=desc, color=_color(self.runtime))
        if coins and self.runtime.config.get()["games"]["economy_enabled"]:
            embed.add_field(name="Premio", value=f"+{coins} monete", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="moneta", description="Lancia una moneta.")
    @app_commands.describe(scelta="Testa o croce (facoltativo, per puntare)")
    @app_commands.choices(scelta=[
        app_commands.Choice(name="Testa", value="testa"),
        app_commands.Choice(name="Croce", value="croce"),
    ])
    async def moneta(
        self, interaction: discord.Interaction, scelta: str | None = None
    ) -> None:
        if not await self._guard(interaction, "moneta"):
            return
        result = random.choice(["testa", "croce"])
        won = bool(scelta and scelta == result)
        item = self._item("moneta")
        coins = item["reward"] if won else 0
        _record(self.runtime, interaction.guild_id, interaction.user, "moneta", won, coins)
        desc = f"🪙 È uscito **{result}**!"
        if scelta:
            desc += "\nHai puntato su **{}**: ".format(scelta) + ("vinto! 🎉" if won else "perso.")
        embed = discord.Embed(title="Lancio di moneta", description=desc, color=_color(self.runtime))
        if coins and self.runtime.config.get()["games"]["economy_enabled"]:
            embed.add_field(name="Premio", value=f"+{coins} monete", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="slot", description="Gira la slot machine.")
    async def slot(self, interaction: discord.Interaction) -> None:
        if not await self._guard(interaction, "slot"):
            return
        reels = [random.choice(SLOT_SYMBOLS) for _ in range(3)]
        counts = {symbol: reels.count(symbol) for symbol in set(reels)}
        best = max(counts.values())
        item = self._item("slot")
        if best >= 3:
            coins = item["reward"] * 3
        elif best == 2:
            coins = item["reward"]
        else:
            coins = 0
        won = coins > 0
        _record(self.runtime, interaction.guild_id, interaction.user, "slot", won, coins)
        embed = discord.Embed(
            title="🎰 Slot",
            description=f"## {' | '.join(reels)}\n\n" + (
                "💎 Jackpot! Tre simboli uguali." if best >= 3
                else "✨ Due simboli uguali." if best == 2
                else "Niente da fare, riprova!"
            ),
            color=_color(self.runtime),
        )
        if coins and self.runtime.config.get()["games"]["economy_enabled"]:
            embed.add_field(name="Premio", value=f"+{coins} monete", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="daily", description="Riscuoti le monete giornaliere.")
    async def daily(self, interaction: discord.Interaction) -> None:
        if not await self._guard_economy(interaction):
            return
        cfg = self.runtime.config.get()["games"]
        guild_id, user_id = str(interaction.guild_id), str(interaction.user.id)
        row = self.runtime.db.one(
            "SELECT * FROM economy WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
        )
        now = utcnow()
        if row and row["last_daily"]:
            try:
                from datetime import datetime
                last = datetime.fromisoformat(row["last_daily"])
                elapsed = (now - last).total_seconds()
                if elapsed < 86400:
                    wait = int(86400 - elapsed)
                    await interaction.response.send_message(
                        f"⏳ Hai già riscosso oggi. Riprova tra **{wait // 3600}h {(wait % 3600) // 60}m**.",
                        ephemeral=True,
                    )
                    return
            except ValueError:
                pass
        amount = int(cfg["daily_coins"])
        self.runtime.db.execute(
            """INSERT INTO economy(guild_id, user_id, user_name, balance, last_daily)
               VALUES(?, ?, ?, ?, ?)
               ON CONFLICT(guild_id, user_id) DO UPDATE SET
                   balance = balance + excluded.balance,
                   user_name = excluded.user_name,
                   last_daily = excluded.last_daily""",
            (guild_id, user_id, str(interaction.user), amount, now.isoformat(timespec="seconds")),
        )
        await interaction.response.send_message(
            f"🪙 Hai riscosso **{amount}** monete! Torna tra 24 ore.", ephemeral=True
        )

    @app_commands.command(name="saldo", description="Mostra il tuo saldo di monete.")
    async def saldo(self, interaction: discord.Interaction) -> None:
        if not await self._guard_economy(interaction):
            return
        row = self.runtime.db.one(
            "SELECT balance FROM economy WHERE guild_id = ? AND user_id = ?",
            (str(interaction.guild_id), str(interaction.user.id)),
        )
        balance = int(row["balance"]) if row else 0
        embed = discord.Embed(
            title="🪙 Il tuo saldo",
            description=f"Hai **{balance}** monete.",
            color=_color(self.runtime),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="classifica", description="Mostra la classifica.")
    @app_commands.describe(gioco="Classifica per un gioco specifico (facoltativo)")
    @app_commands.choices(gioco=[app_commands.Choice(name=label, value=key) for key, label in GAMES.items()])
    async def classifica(
        self, interaction: discord.Interaction, gioco: str | None = None
    ) -> None:
        cfg = self.runtime.config.get()
        if not interaction.guild or not cfg["modules"]["games"]:
            await interaction.response.send_message("I mini giochi sono disattivati.", ephemeral=True)
            return
        guild_id = str(interaction.guild.id)
        if gioco:
            rows = self.runtime.db.query(
                """SELECT user_id, user_name, wins, plays, coins FROM game_stats
                   WHERE guild_id = ? AND game = ? ORDER BY wins DESC, plays ASC LIMIT 10""",
                (guild_id, gioco),
            )
            title = f"🏆 Classifica · {GAMES[gioco]}"
            lines = [
                f"**{i + 1}.** <@{r['user_id']}> · {r['wins']} vittorie / {r['plays']} partite"
                for i, r in enumerate(rows)
            ] or ["Nessuna partita registrata."]
        else:
            if not cfg["games"]["economy_enabled"]:
                await interaction.response.send_message("L'economia è disattivata.", ephemeral=True)
                return
            rows = self.runtime.db.query(
                "SELECT user_id, user_name, balance FROM economy WHERE guild_id = ? "
                "ORDER BY balance DESC LIMIT 10",
                (guild_id,),
            )
            title = "🏆 Classifica · Monete"
            lines = [
                f"**{i + 1}.** <@{r['user_id']}> · {r['balance']} monete"
                for i, r in enumerate(rows)
            ] or ["Nessun saldo registrato."]
        embed = discord.Embed(title=title, description="\n".join(lines), color=_color(self.runtime))
        embed.set_footer(text="FraBot · Mini giochi")
        await interaction.response.send_message(embed=embed)


async def setup(bot) -> None:
    await bot.add_cog(Games(bot))
