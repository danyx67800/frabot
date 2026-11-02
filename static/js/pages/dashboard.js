import { api, errorMessage } from "../api.js";
import { t } from "../i18n.js";
import {
  badge, button, clear, emptyState, fmtDate, fmtNumber, fmtUptime, h, statusDot,
} from "../ui.js";

function statCard(label, valueNode, hintNode, accent = false, small = false) {
  return h(
    "article",
    { class: `stat-card${accent ? " accent" : ""}` },
    h("div", { class: "stat-top" }, h("span", { class: "stat-label", text: label })),
    h("div", { class: small ? "stat-strong" : "stat-value" }, valueNode),
    hintNode,
  );
}

function warningCard(tone, title, text, actionLabel, onClick) {
  const warn = tone === "warn";
  return h(
    "div",
    { class: `warning-card${warn ? " warn" : ""}` },
    h("span", { class: "warning-icon", text: warn ? "!" : "i" }),
    h("div", {}, h("strong", { text: title }), h("p", { text })),
    button(actionLabel, { variant: "ghost", onClick }),
  );
}

function instanceRow(index, label, valueNode) {
  return h(
    "div",
    { class: "instance-row" },
    h("span", { class: "instance-index", text: index }),
    h("span", { class: "instance-label", text: label }),
    valueNode,
  );
}

function logRows(items) {
  if (!items.length) return [h("tr", {}, h("td", { colspan: 3 }, emptyState(t("logs.noLogs"))))];
  return items.map((item) =>
    h(
      "tr",
      {},
      h("td", { class: "log-time mono", text: new Date(item.ts).toLocaleTimeString("it-IT") }),
      h("td", {}, badge(item.level, item.level === "ERROR" || item.level === "CRITICAL" ? "error" : item.level === "WARNING" ? "warn" : "neutral")),
      h("td", { class: "log-message", text: item.message }),
    ));
}

export async function render(ctx) {
  const status = ctx.state.status || {};
  const page = h("div", { class: "dashboard-page" });
  page.append(
    h(
      "div",
      { class: "page-head" },
      h(
        "div",
        { class: "page-head-copy" },
        h("div", { class: "page-eyebrow" }, h("span", { class: "eyebrow-dot" }), h("span", { text: t("dashboard.overview") })),
        h("h1", { text: t("dashboard.title") }),
        h("p", { text: t("dashboard.subtitle") }),
      ),
      h("div", { class: "page-actions" },
        button(t("common.refresh"), { variant: "ghost", onClick: () => ctx.reload() })),
    ),
  );

  const warnings = h("div", { class: "warnings" });
  const panelWarnings = h("div", { class: "warnings" });
  const botValue = h("div", { class: "stat-inline" });
  const botHint = h("div", { class: "stat-hint" });
  const serverValue = h("span", { text: "—" });
  const serverHint = h("div", { class: "stat-hint" });
  const moduleValue = h("span", { text: "—" });
  const moduleHint = h("div", { class: "stat-hint" });
  const twitchValue = h("span", { text: "—" });
  const twitchHint = h("div", { class: "stat-hint" });

  page.append(
    h("div", { class: "stats-grid dashboard-kpis" },
      statCard(t("dashboard.botStatus"), botValue, botHint, true),
      statCard(t("layout.server"), serverValue, serverHint, false, true),
      statCard(t("dashboard.activeModules"), moduleValue, moduleHint, false, true),
      statCard(t("dashboard.twitchLive"), twitchValue, twitchHint, false, true)),
    warnings,
    panelWarnings,
  );

  const moduleCount = h("span", { class: "badge badge-neutral", text: "—" });
  const moduleList = h("div", { class: "module-list" });
  const moduleCard = h(
    "section",
    { class: "card module-card-panel" },
    h("div", { class: "card-head" },
      h("div", { class: "card-heading" },
        h("h2", { text: t("dashboard.modules") }),
        h("p", { class: "card-subtitle", text: t("dashboard.modulesHint") })),
      moduleCount),
    h("div", { class: "card-body" }, moduleList),
  );

  const instanceUptime = h("span", { class: "instance-value", text: "—" });
  const instanceDb = h("span", { class: "instance-value" });
  const instanceVersion = h("span", { class: "instance-value", text: "—" });
  const instanceStarted = h("span", { class: "instance-value", text: fmtDate(status.started_at) });
  const instanceCard = h(
    "section",
    { class: "card instance-card" },
    h("div", { class: "card-head" },
      h("div", { class: "card-heading" },
        h("h2", { text: t("dashboard.instance") }),
        h("p", { class: "card-subtitle", text: t("dashboard.instanceHint") }))),
    h("div", { class: "card-body" },
      instanceRow("01", t("dashboard.uptime"), instanceUptime),
      instanceRow("02", t("dashboard.database"), instanceDb),
      instanceRow("03", t("dashboard.version"), instanceVersion),
      instanceRow("04", t("dashboard.started"), instanceStarted)),
  );

  const logsBody = h("tbody", {});
  const logsCard = h(
    "section",
    { class: "card logs-card" },
    h("div", { class: "card-head" },
      h("div", { class: "card-heading" },
        h("h2", { text: t("dashboard.recentLogs") }),
        h("p", { class: "card-subtitle", text: t("dashboard.recentLogsHint") })),
      button(t("dashboard.viewAllLogs"), { variant: "ghost", onClick: () => ctx.navigate("logs") })),
    h("div", { class: "card-body logs-card-body" },
      h("div", { class: "table-wrap" },
        h("table", { class: "table logs-table" },
          h("thead", {}, h("tr", {},
            h("th", { text: t("logs.time") }),
            h("th", { text: t("logs.level") }),
            h("th", { text: t("logs.message") }))),
          logsBody))),
  );

  page.append(
    logsCard,
    h("div", { class: "dash-bottom" }, moduleCard, instanceCard),
  );

  const host = document.getElementById("page");
  host.replaceChildren(page);

  async function loadPanelWarning() {
    if (!status?.modules?.tickets) return;
    try {
      const panel = await api("/api/tickets/panel");
      if (!panel.published) {
        panelWarnings.append(
          warningCard(
            "info",
            t("dashboard.panelMissing"),
            t("dashboard.panelMissingHint"),
            t("dashboard.manage"),
            () => ctx.navigate("tickets"),
          ),
        );
      }
    } catch { /* non-blocking */ }
  }

  function updateWarnings(current) {
    clear(warnings);
    if (!current.bot?.connected) {
      warnings.append(
        warningCard(
          "warn",
          t("common.noBot"),
          current.bot?.last_error || t("common.noBotHint"),
          t("common.retry"),
          () => ctx.refreshStatus(true),
        ),
      );
    }
    if (current.twitch?.errors) {
      warnings.append(
        warningCard(
          "warn",
          t("dashboard.twitchErrors"),
          t("dashboard.twitchErrorsHint"),
          t("dashboard.manage"),
          () => ctx.navigate("twitch"),
        ),
      );
    }
  }

  function renderModules(current) {
    clear(moduleList);
    const entries = [
      ["tickets", t("dashboard.moduleTickets"), t("dashboard.moduleTicketsHint"), "TK"],
      ["games", t("dashboard.moduleGames"), t("dashboard.moduleGamesHint"), "MG"],
      ["twitch", t("dashboard.moduleTwitch"), t("dashboard.moduleTwitchHint"), "TW"],
    ];
    let active = 0;
    for (const [key, label, hint, code] of entries) {
      const on = Boolean(current.modules?.[key]);
      if (on) active += 1;
      moduleList.append(
        h("div", { class: "module-row" },
          h("span", { class: `module-tile${on ? " on" : ""}`, text: code }),
          h("div", { class: "module-row-copy" }, h("strong", { text: label }), h("small", { text: hint })),
          badge(on ? t("common.enabled") : t("common.disabled"), on ? "ok" : "neutral"),
          button("", {
            variant: "ghost",
            icon: "chevron",
            title: t("dashboard.manage"),
            ariaLabel: `${t("dashboard.manage")} ${label}`,
            onClick: () => ctx.navigate(key === "games" ? "games" : key),
          })),
      );
    }
    moduleCount.textContent = `${active} / ${entries.length}`;
    moduleCount.className = `badge ${active === entries.length ? "badge-ok" : "badge-neutral"}`;
  }

  function renderInstance(current) {
    instanceUptime.textContent = fmtUptime(current.uptime_seconds);
    instanceDb.replaceChildren(badge(current.database ? "OK" : "KO", current.database ? "ok" : "error"));
    instanceVersion.textContent = current.version ? `v${current.version}` : "—";
    instanceStarted.textContent = fmtDate(current.started_at);
  }

  function updateStats(current) {
    const connected = Boolean(current.bot?.connected);
    clear(botValue);
    botValue.append(
      statusDot(connected),
      h("span", { text: connected ? current.bot.user || t("common.online") : t("common.offline") }),
    );
    botHint.textContent = connected
      ? `${t("dashboard.ping")} ${current.bot.latency_ms ?? "—"} ms · ${t("dashboard.uptime")} ${fmtUptime(current.bot.uptime_seconds)}`
      : current.bot?.last_error || t("common.noBotHint");

    serverValue.textContent = current.guild?.name || t("layout.noServer");
    const guild = current.bot?.guilds?.find((item) => item.id === current.guild?.id);
    serverHint.textContent = guild?.member_count ? `${fmtNumber(guild.member_count)} membri` : t("dashboard.guild");

    const active = Object.values(current.modules || {}).filter(Boolean).length;
    moduleValue.textContent = `${active} / 3`;
    moduleHint.textContent = t("dashboard.modulesHint");

    twitchValue.textContent = `${current.twitch?.live ?? 0} / ${current.twitch?.total ?? 0}`;
    twitchHint.textContent = current.twitch?.last_error || t("twitch.polling", { s: current.twitch?.poll_seconds || 60 });

    renderModules(current);
    renderInstance(current);
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
