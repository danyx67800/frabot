import { api, errorMessage } from "../api.js";
import { t } from "../i18n.js";
import {
  badge, button, card, clear, emptyState, fmtDate, fmtNumber, fmtUptime, h,
  pageHeader, spinner, statusDot,
} from "../ui.js";

function statCard(label, valueNode, hint = "", accent = "") {
  return h(
    "div",
    { class: `stat-card ${accent}` },
    h("div", { class: "stat-label", text: label }),
    h("div", { class: "stat-value" }, valueNode),
    hint ? h("div", { class: "stat-hint", text: hint }) : null,
  );
}

function logRows(items) {
  if (!items.length) return [h("tr", {}, h("td", { colspan: 3 }, emptyState(t("logs.noLogs"))))];
  return items.map((item) =>
    h(
      "tr",
      {},
      h("td", { class: "mono muted", text: new Date(item.ts).toLocaleTimeString("it-IT") }),
      h("td", {}, badge(item.level, item.level === "ERROR" ? "error" : item.level === "WARNING" ? "warn" : "neutral")),
      h("td", { class: "log-message", text: item.message }),
    ),
  );
}

export async function render(ctx) {
  const status = ctx.state.status;
  const page = h("div", {});
  page.append(
    pageHeader(t("dashboard.title"), t("dashboard.subtitle"), [
      button(t("common.refresh"), { variant: "ghost", onClick: () => ctx.reload() }),
    ]),
  );

  const warnings = h("div", { class: "warnings" });
  const panelWarnings = h("div", { class: "warnings" });
  const botValue = h("div", {});
  const botHint = h("div", { class: "stat-hint" });
  const serverValue = h("div", {});
  const serverHint = h("div", { class: "stat-hint" });
  const moduleValue = h("div", {});
  const moduleHint = h("div", { class: "stat-hint" });
  const twitchValue = h("div", {});
  const twitchHint = h("div", { class: "stat-hint" });

  page.append(
    h("div", { class: "stats-grid" },
      statCard(t("dashboard.botStatus"), botValue, "", "accent"),
      statCard(t("layout.server"), serverValue, "", ""),
      statCard(t("dashboard.activeModules"), moduleValue, "", ""),
      statCard(t("dashboard.twitchLive"), twitchValue, "", "")),
    warnings,
    panelWarnings,
  );

  const moduleList = h("div", { class: "module-list" });
  const moduleCard = card(t("dashboard.modules"), moduleList,
    h("p", { class: "muted small", text: t("dashboard.modulesHint") }));

  const logsBody = h("tbody", {});
  const logsCard = h(
    "section",
    { class: "card" },
    h("div", { class: "card-head" },
      h("h2", { text: t("dashboard.recentLogs") }),
      button(t("dashboard.viewAllLogs"), { variant: "ghost", onClick: () => ctx.navigate("logs") })),
    h("div", { class: "card-body table-wrap" },
      h("table", { class: "table" },
        h("thead", {}, h("tr", {}, h("th", { text: t("logs.time") }), h("th", { text: t("logs.level") }), h("th", { text: t("logs.message") }))),
        logsBody)),
  );

  page.append(h("div", { class: "dash-grid" }, moduleCard, logsCard));
  page.append(h("div", { class: "dash-foot", text: `${t("dashboard.startedAt")} ${fmtDate(status?.started_at)}` }));
  const root = h("div", {});
  root.append(page);
  const host = document.getElementById("page");
  host.replaceChildren(root);

  async function loadPanelWarning() {
    if (!status?.modules?.tickets) return;
    try {
      const panel = await api("/api/tickets/panel");
      if (!panel.published) {
        panelWarnings.append(
          h("div", { class: "warning-card" },
            h("div", {}, h("strong", { text: t("dashboard.panelMissing") }), h("p", { text: t("dashboard.panelMissingHint") })),
            button(t("dashboard.manage"), { variant: "secondary", onClick: () => ctx.navigate("tickets") })),
        );
      }
    } catch { /* non-blocking */ }
  }

  function updateWarnings(current) {
    clear(warnings);
    if (!current.bot.connected) {
      warnings.append(
        h("div", { class: "warning-card warn" },
          h("div", {}, h("strong", { text: t("common.noBot") }), h("p", { text: current.bot.last_error || t("common.noBotHint") })),
          button(t("common.retry"), { variant: "ghost", onClick: () => ctx.refreshStatus(true) })),
      );
    }
    if (current.twitch.errors) {
      warnings.append(
        h("div", { class: "warning-card warn" },
          h("div", {}, h("strong", { text: t("dashboard.twitchErrors") }), h("p", { text: t("dashboard.twitchErrorsHint") })),
          button(t("dashboard.manage"), { variant: "ghost", onClick: () => ctx.navigate("twitch") })),
      );
    }
  }

  function renderModules(current) {
    clear(moduleList);
    const entries = [
      ["tickets", t("dashboard.moduleTickets"), t("dashboard.moduleTicketsHint")],
      ["games", t("dashboard.moduleGames"), t("dashboard.moduleGamesHint")],
      ["twitch", t("dashboard.moduleTwitch"), t("dashboard.moduleTwitchHint")],
    ];
    for (const [key, label, hint] of entries) {
      const on = current.modules[key];
      moduleList.append(
        h("div", { class: "module-row" },
          h("span", { class: `module-dot ${on ? "on" : ""}` }),
          h("div", { class: "module-row-copy" }, h("strong", { text: label }), h("small", { text: hint })),
          badge(on ? t("common.enabled") : t("common.disabled"), on ? "ok" : "neutral"),
          button(t("dashboard.manage"), { variant: "ghost", onClick: () => ctx.navigate(key === "games" ? "games" : key) })),
      );
    }
  }

  function updateStats(current) {
    const connected = current.bot.connected;
    clear(botValue);
    botValue.append(h("div", { class: "stat-inline" }, statusDot(connected), h("span", { text: connected ? current.bot.user || t("common.online") : t("common.offline") })));
    botHint.textContent = connected
      ? `${t("dashboard.ping")} ${current.bot.latency_ms ?? "—"} ms · ${t("dashboard.uptime")} ${fmtUptime(current.bot.uptime_seconds)}`
      : current.bot.last_error || t("common.noBotHint");

    clear(serverValue);
    serverValue.append(h("div", { class: "stat-strong", text: current.guild?.name || t("layout.noServer") }));
    const guild = current.bot.guilds?.find((item) => item.id === current.guild?.id);
    serverHint.textContent = guild?.member_count ? `${fmtNumber(guild.member_count)} membri` : t("dashboard.guild");

    const active = Object.values(current.modules || {}).filter(Boolean).length;
    clear(moduleValue);
    moduleValue.append(h("div", { class: "stat-strong", text: `${active} / 3` }));
    moduleHint.textContent = t("dashboard.modulesHint");

    clear(twitchValue);
    twitchValue.append(h("div", { class: "stat-strong", text: `${current.twitch.live ?? 0} / ${current.twitch.total ?? 0}` }));
    twitchHint.textContent = current.twitch.last_error || t("twitch.polling", { s: current.twitch.poll_seconds || 60 });
    renderModules(current);
  }

  async function loadLogs() {
    try {
      const response = await api("/api/logs?limit=8");
      clear(logsBody);
      logsBody.append(...logRows(response.items));
    } catch (error) {
      clear(logsBody);
      logsBody.append(h("tr", {}, h("td", { colspan: 3, text: errorMessage(error) })));
    }
  }

  updateStats(status);
  updateWarnings(status);
  renderModules(status);
  loadPanelWarning();
  await loadLogs();

  const interval = setInterval(() => {
    if (!document.hidden) loadLogs();
  }, 8000);
  const onStatus = (event) => {
    updateStats(event.detail);
    updateWarnings(event.detail);
  };
  window.addEventListener("frabot:status", onStatus);
  return () => {
    clearInterval(interval);
    window.removeEventListener("frabot:status", onStatus);
  };
}
