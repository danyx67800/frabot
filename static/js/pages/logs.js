import { api, errorMessage } from "../api.js";
import { t } from "../i18n.js";
import {
  badge, button, card, checkbox, clear, emptyState, h, pageHeader, select, spinner,
} from "../ui.js";

const LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"];

export async function render(ctx) {
  let level = "";
  let limit = 200;
  let auto = true;
  let loading = false;

  const page = h("div", {});
  const refresh = button(t("common.refresh"), { variant: "ghost", onClick: () => load() });
  page.append(pageHeader(t("logs.title"), t("logs.subtitle"), [refresh]));

  const levelSelect = select({
    options: LEVELS.map((value) => ({ value, label: value })),
    value: "",
    placeholder: t("logs.allLevels"),
    onChange: () => { level = levelSelect.value; load(); },
  });
  const limitSelect = select({
    options: ["50", "100", "200", "400", "800"].map((value) => ({ value, label: value })),
    value: "200",
    onChange: () => { limit = Number(limitSelect.value); load(); },
  });
  const autoBox = checkbox(t("logs.autoRefresh"), true, (event) => {
    auto = event.target.checked;
    if (auto) startTimer();
    else stopTimer();
  });
  const filters = h("div", { class: "filters" },
    h("div", { class: "field inline" }, h("span", { class: "field-label", text: t("logs.level") }), levelSelect),
    h("div", { class: "field inline" }, h("span", { class: "field-label", text: t("logs.limit") }), limitSelect),
    autoBox);
  const tbody = h("tbody", {});
  const table = h("div", { class: "table-wrap" },
    h("table", { class: "table logs-table" },
      h("thead", {}, h("tr", {},
        h("th", { text: t("logs.time") }),
        h("th", { text: t("logs.level") }),
        h("th", { text: t("logs.logger") }),
        h("th", { text: t("logs.message") }),
        h("th", { text: t("logs.context") }))),
      tbody));
  page.append(card("", filters, table));

  const host = document.getElementById("page");
  host.replaceChildren(page);

  let timer = null;
  function startTimer() {
    stopTimer();
    timer = setInterval(() => {
      if (!document.hidden) load(true);
    }, 5000);
  }
  function stopTimer() {
    if (timer) clearInterval(timer);
    timer = null;
  }

  async function load(silent = false) {
    if (loading) return;
    loading = true;
    if (!silent) {
      clear(tbody);
      tbody.append(h("tr", {}, h("td", { colspan: 5 }, spinner(t("common.loading")))));
    }
    try {
      const params = new URLSearchParams({ limit: String(limit) });
      if (level) params.set("level", level);
      const response = await api(`/api/logs?${params}`);
      clear(tbody);
      if (!response.items.length) {
        tbody.append(h("tr", {}, h("td", { colspan: 5 }, emptyState(t("logs.noLogs")))));
      } else {
        for (const entry of response.items) {
          const extra = Object.fromEntries(Object.entries(entry).filter(([key]) => !["ts", "level", "logger", "message"].includes(key)));
          const hasExtra = Object.keys(extra).length > 0;
          tbody.append(h("tr", {},
            h("td", { class: "mono muted nowrap", text: new Date(entry.ts).toLocaleString("it-IT") }),
            h("td", {}, badge(entry.level, entry.level === "ERROR" || entry.level === "CRITICAL" ? "error" : entry.level === "WARNING" ? "warn" : entry.level === "DEBUG" ? "neutral" : "ok")),
            h("td", { class: "mono small", text: entry.logger }),
            h("td", { class: "log-message", text: entry.message }),
            h("td", { class: "mono small" },
              hasExtra ? h("details", {}, h("summary", { text: "JSON" }), h("pre", { class: "json", text: JSON.stringify(extra) })) : "—")));
        }
      }
    } catch (error) {
      if (!silent) {
        clear(tbody);
        tbody.append(h("tr", {}, h("td", { colspan: 5, text: errorMessage(error) })));
      }
    } finally {
      loading = false;
    }
  }

  await load();
  startTimer();
  return () => stopTimer();
}
