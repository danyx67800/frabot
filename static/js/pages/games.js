import { api, downloadJson, errorMessage } from "../api.js";
import { guildData } from "../data.js";
import { t } from "../i18n.js";
import {
  badge, button, card, clear, confirmDialog, emptyState, field, h, input,
  openModal, pageHeader, select, spinner, textarea, toast, toggleRow,
} from "../ui.js";

const GAME_KEYS = ["tris", "indovina", "quiz", "rps", "dado", "moneta", "slot"];
const GAME_LABELS = {
  tris: "games.gameTris",
  indovina: "games.gameIndovina",
  quiz: "games.gameQuiz",
  rps: "games.gameRps",
  dado: "games.gameDado",
  moneta: "games.gameMoneta",
  slot: "games.gameSlot",
};
const GAME_ICONS = { tris: "❌", indovina: "🔢", quiz: "🧠", rps: "✂️", dado: "🎲", moneta: "🪙", slot: "🎰" };

function optionText(question) {
  const options = question.options || [];
  const answer = options[question.answer] || "—";
  return answer.length > 45 ? `${answer.slice(0, 44)}…` : answer;
}

async function chooseFile() {
  return new Promise((resolve) => {
    const fileInput = h("input", { type: "file", accept: "application/json,.json", hidden: true });
    fileInput.addEventListener("change", () => resolve(fileInput.files?.[0] || null));
    document.body.append(fileInput);
    fileInput.click();
    setTimeout(() => fileInput.remove(), 60000);
  });
}

export async function render(ctx) {
  const [data, guild] = await Promise.all([
    api("/api/games"),
    guildData().catch(() => null),
  ]);
  const channels = guild?.channels?.filter((c) => c.type === "text") || [];
  const channelSelectOptions = channels.map((c) => ({ value: c.id, label: `# ${c.name}` }));
  const cfg = data.games;
  const itemRefs = {};
  let quizQuestions = [];
  let leaderboardGame = "coins";

  const page = h("div", {});
  page.append(pageHeader(t("games.title"), t("games.subtitle"), [
    button(t("common.refresh"), { variant: "ghost", onClick: () => ctx.reload() }),
  ]));

  // -- economy ---------------------------------------------------------
  const economyBox = h("input", { type: "checkbox", class: "switch-input" });
  economyBox.checked = cfg.economy_enabled;
  const dailyInput = input({ type: "number", min: 0, max: 100000, value: cfg.daily_coins });
  const saveEconomy = button(t("common.save"), {
    variant: "primary",
    onClick: async (event) => {
      event.currentTarget.disabled = true;
      try {
        await api("/api/games", { method: "PUT", body: { economy_enabled: economyBox.checked, daily_coins: Number(dailyInput.value) } });
        toast(t("games.configSaved"), "success");
      } catch (error) {
        toast(errorMessage(error), "error");
      } finally {
        event.currentTarget.disabled = false;
      }
    },
  });
  page.append(card(t("games.economyTitle"),
    h("p", { class: "muted", text: t("games.economyHint") }),
    h("div", { class: "form-grid two" },
      toggleRow(t("games.economyEnabled"), "", cfg.economy_enabled, (event) => { economyBox.checked = event.target.checked; }),
      field(t("games.dailyCoins"), dailyInput)),
    h("div", { class: "page-actions" }, saveEconomy)));

  // -- games -----------------------------------------------------------
  const gameGrid = h("div", { class: "game-grid" });
  for (const key of GAME_KEYS) {
    const item = cfg.items[key];
    const channelSelect = select({
      options: channelSelectOptions,
      value: item.channels,
      multiple: true,
      size: Math.min(5, Math.max(3, channelSelectOptions.length || 3)),
      disabled: !channelSelectOptions.length,
    });
    const cooldown = input({ type: "number", min: 0, max: 3600, value: item.cooldown });
    const reward = input({ type: "number", min: 0, max: 100000, value: item.reward });
    const enabled = h("input", { type: "checkbox", class: "switch-input" });
    enabled.checked = item.enabled;
    itemRefs[key] = { enabled, channelSelect, cooldown, reward };
    gameGrid.append(
      h("div", { class: `game-card ${item.enabled ? "" : "off"}` },
        h("div", { class: "game-head" },
          h("div", { class: "game-icon", text: GAME_ICONS[key] }),
          h("div", { class: "game-title" }, h("strong", { text: t(GAME_LABELS[key]) }), h("small", { text: `/ ${key}` })),
          h("label", { class: "switch" }, enabled, h("span", { class: "switch-track" }))),
        field(t("games.channels"), channelSelect, channelSelectOptions.length ? t("games.channelsHint") : t("common.noChannels")),
        h("div", { class: "form-grid two" },
          field(t("games.cooldown"), cooldown),
          field(t("games.reward"), reward))),
    );
  }
  const saveGames = button(t("games.saveConfig"), {
    variant: "primary",
    onClick: async (event) => {
      const items = {};
      for (const key of GAME_KEYS) {
        const ref = itemRefs[key];
        items[key] = {
          enabled: ref.enabled.checked,
          channels: Array.from(ref.channelSelect.selectedOptions).map((option) => option.value),
          cooldown: Number(ref.cooldown.value),
          reward: Number(ref.reward.value),
        };
        const card = ref.enabled.closest(".game-card");
        card?.classList.toggle("off", !ref.enabled.checked);
      }
      event.currentTarget.disabled = true;
      try {
        await api("/api/games", { method: "PUT", body: { items } });
        toast(t("games.configSaved"), "success");
      } catch (error) {
        toast(errorMessage(error), "error");
      } finally {
        event.currentTarget.disabled = false;
      }
    },
  });
  page.append(card(t("games.gamesTitle"), h("p", { class: "muted", text: t("games.gamesHint") }), gameGrid,
    h("div", { class: "page-actions" }, saveGames)));

  // -- quiz ------------------------------------------------------------
  const quizTbody = h("tbody", {});
  const quizTable = h("div", { class: "table-wrap" },
    h("table", { class: "table" },
      h("thead", {}, h("tr", {},
        h("th", { text: t("games.questionCategory") }),
        h("th", { text: t("games.question") }),
        h("th", { text: t("games.correctAnswer") }),
        h("th", { text: t("common.actions") }))),
      quizTbody));

  async function loadQuiz() {
    const response = await api("/api/games/quiz");
    quizQuestions = response.items;
    clear(quizTbody);
    if (!quizQuestions.length) {
      quizTbody.append(h("tr", {}, h("td", { colspan: 4 }, emptyState(t("games.noQuestions")))));
      return;
    }
    for (const question of quizQuestions) {
      const edit = button("", { variant: "ghost", icon: "edit", title: t("common.edit"), onClick: () => questionModal(question) });
      const remove = button("", { variant: "ghost", icon: "trash", title: t("common.delete"), onClick: async () => {
        if (!(await confirmDialog({ title: t("common.confirmDeleteTitle"), text: t("games.deleteQuestion"), danger: true }))) return;
        try {
          await api(`/api/games/quiz/${question.id}`, { method: "DELETE" });
          toast(t("games.questionDeleted"), "success");
          loadQuiz();
        } catch (error) { toast(errorMessage(error), "error"); }
      } });
      quizTbody.append(h("tr", {},
        h("td", {}, badge(question.category, "neutral")),
        h("td", { class: "quiz-question", text: question.question }),
        h("td", { text: optionText(question) }),
        h("td", { class: "actions-cell" }, edit, remove)));
    }
  }

  function questionModal(question = null) {
    const category = input({ value: question?.category || "Generale", maxlength: 60 });
    const text = textarea({ value: question?.question || "", rows: 3, maxlength: 500 });
    const optionInputs = [0, 1, 2, 3].map((index) =>
      input({ value: question?.options?.[index] || "", placeholder: t("games.option", { n: index + 1 }), maxlength: 200 }));
    const answer = select({
      options: [0, 1, 2, 3].map((index) => ({ value: index, label: t("games.option", { n: index + 1 }) })),
      value: question?.answer ?? 0,
    });
    const body = h("div", { class: "form-stack" },
      h("div", { class: "form-grid two" }, field(t("games.questionCategory"), category)),
      field(t("games.question"), text),
      field(t("games.options"), h("div", { class: "form-stack" }, ...optionInputs.map((item, index) => h("div", { class: "option-row" }, h("span", { class: "option-letter", text: String.fromCharCode(65 + index) }), item)))),
      field(t("games.correctAnswer"), answer));
    const modal = openModal({
      title: question ? t("games.editQuestion") : t("games.addQuestion"),
      body,
      wide: true,
      actions: [
        button(t("common.cancel"), { onClick: () => modal.close() }),
        button(t("common.save"), {
          variant: "primary",
          onClick: async () => {
            const values = optionInputs.map((item) => item.value.trim());
            const nonEmpty = values.map((value, index) => ({ value, index })).filter((item) => item.value);
            if (!text.value.trim()) { toast(t("games.questionRequired"), "error"); return; }
            if (nonEmpty.length < 2) { toast(t("games.optionsRequired"), "error"); return; }
            const selectedOriginal = Number(answer.value);
            if (!values[selectedOriginal]) { toast(t("games.answerRequired"), "error"); return; }
            const correct = nonEmpty.findIndex((item) => item.index === selectedOriginal);
            const payload = {
              category: category.value.trim() || "Generale",
              question: text.value.trim(),
              options: nonEmpty.map((item) => item.value),
              answer: correct,
            };
            try {
              if (question) await api(`/api/games/quiz/${question.id}`, { method: "PUT", body: payload });
              else await api("/api/games/quiz", { method: "POST", body: payload });
              toast(question ? t("games.questionUpdated") : t("games.questionCreated"), "success");
              modal.close();
              loadQuiz();
            } catch (error) { toast(errorMessage(error), "error"); }
          },
        }),
      ],
    });
  }

  const importInput = h("input", { type: "file", accept: "application/json,.json", hidden: true });
  importInput.addEventListener("change", async () => {
    const file = importInput.files?.[0];
    if (!file) return;
    try {
      const parsed = JSON.parse(await file.text());
      if (!(await confirmDialog({ title: t("games.quizImport"), text: t("games.quizImportHint"), danger: true, confirmLabel: t("games.quizImport") }))) return;
      const response = await api("/api/games/quiz/import", { method: "POST", body: parsed });
      toast(t("games.quizImportSuccess", { n: response.imported }), "success");
      loadQuiz();
    } catch (error) {
      toast(errorMessage(error), "error");
    } finally {
      importInput.value = "";
    }
  });

  page.append(card(t("games.quizTitle"),
    h("p", { class: "muted", text: t("games.quizHint") }),
    quizTable,
    h("div", { class: "page-actions" },
      button(t("games.addQuestion"), { variant: "primary", icon: "plus", onClick: () => questionModal() }),
      button(t("games.quizExport"), { variant: "secondary", onClick: () => downloadJson("/api/games/quiz/export").catch((error) => toast(errorMessage(error), "error")) }),
      button(t("games.quizImport"), { variant: "secondary", onClick: () => importInput.click() }),
      importInput)));

  // -- leaderboard -----------------------------------------------------
  const leaderboardSelect = select({
    options: [{ value: "coins", label: t("games.coins") }, ...GAME_KEYS.map((key) => ({ value: key, label: t(GAME_LABELS[key]) }))],
    value: "coins",
    onChange: () => { leaderboardGame = leaderboardSelect.value; loadLeaderboard(); },
  });
  const leaderboardBody = h("div", {});
  async function loadLeaderboard() {
    leaderboardBody.replaceChildren(spinner(t("common.loading")));
    try {
      const response = await api(`/api/games/leaderboard?game=${encodeURIComponent(leaderboardGame)}&limit=10`);
      const rows = leaderboardGame === "coins" ? response.coins : response.stats;
      clear(leaderboardBody);
      if (!rows.length) {
        leaderboardBody.append(emptyState(t("games.noLeaderboard")));
        return;
      }
      const isCoins = leaderboardGame === "coins";
      leaderboardBody.append(h("div", { class: "table-wrap" },
        h("table", { class: "table" },
          h("thead", {}, h("tr", {},
            h("th", { text: t("games.position") }),
            h("th", { text: t("games.user") }),
            h("th", { text: isCoins ? t("games.balance") : t("games.wins") }),
            isCoins ? null : h("th", { text: t("games.plays") }),
            isCoins ? null : h("th", { text: t("games.coins") }))),
          h("tbody", {}, ...rows.map((row, index) =>
            h("tr", {},
              h("td", { text: `#${index + 1}` }),
              h("td", { text: row.user_name || `<@${row.user_id}>` }),
              h("td", { text: isCoins ? row.balance : row.wins }),
              isCoins ? null : h("td", { text: row.plays }),
              isCoins ? null : h("td", { text: row.coins })))))));
    } catch (error) {
      leaderboardBody.replaceChildren(h("div", { class: "inline-error", text: errorMessage(error) }));
    }
  }

  function resetModal() {
    const scope = select({
      options: [
        { value: "coins", label: t("games.resetCoins") },
        { value: "game", label: t("games.resetGame") },
        { value: "all", label: t("games.resetAll") },
      ],
      value: "coins",
    });
    const game = select({
      options: GAME_KEYS.map((key) => ({ value: key, label: t(GAME_LABELS[key]) })),
      value: leaderboardGame === "coins" ? "tris" : leaderboardGame,
    });
    const modal = openModal({
      title: t("games.resetLeaderboardTitle"),
      body: h("div", { class: "form-stack" },
        h("p", { class: "modal-text", text: t("games.resetLeaderboardText") }),
        field(t("games.resetScope"), scope),
        field(t("games.game"), game)),
      actions: [
        button(t("common.cancel"), { onClick: () => modal.close() }),
        button(t("games.resetLeaderboard"), {
          variant: "danger",
          onClick: async () => {
            try {
              await api("/api/games/leaderboard/reset", { method: "POST", body: { confirm: true, scope: scope.value, game: game.value } });
              toast(t("games.resetDone"), "success");
              modal.close();
              loadLeaderboard();
            } catch (error) { toast(errorMessage(error), "error"); }
          },
        }),
      ],
    });
  }

  page.append(card(t("games.leaderboardTitle"),
    h("p", { class: "muted", text: t("games.leaderboardHint") }),
    h("div", { class: "toolbar" },
      field(t("games.leaderboardType"), leaderboardSelect),
      button(t("games.resetLeaderboard"), { variant: "danger", onClick: resetModal })),
    leaderboardBody));

  document.getElementById("page").replaceChildren(page);
  await Promise.all([loadQuiz(), loadLeaderboard()]);
  return () => {};
}
