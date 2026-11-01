import { api } from "./api.js";
import { clearGuildData } from "./data.js";
import { loadI18n, t } from "./i18n.js";
import { setStatus, store } from "./store.js";
import { button, clear, errorBox, h, icon, spinner, statusDot } from "./ui.js";
import { renderWizard } from "./wizard.js";
import * as dashboard from "./pages/dashboard.js";
import * as tickets from "./pages/tickets.js";
import * as games from "./pages/games.js";
import * as twitch from "./pages/twitch.js";
import * as logs from "./pages/logs.js";
import * as settings from "./pages/settings.js";

const PAGES = { dashboard, tickets, games, twitch, logs, settings };
const NAV = [
  { route: "dashboard", icon: "dashboard" },
  { route: "tickets", icon: "tickets" },
  { route: "games", icon: "games" },
  { route: "twitch", icon: "twitch" },
  { route: "logs", icon: "logs" },
  { route: "settings", icon: "settings" },
];

const root = document.getElementById("app");
let cleanup = null;
let pollTimer = null;
let wizardMode = false;
let chrome = {};
let hashBound = false;

function parseRoute() {
  const hash = window.location.hash.replace(/^#\/?/, "").split("?")[0];
  return PAGES[hash] ? hash : "dashboard";
}

function navLink(item) {
  return h(
    "a",
    { class: "nav-link", href: `#/${item.route}`, "data-route": item.route },
    icon(item.icon),
    h("span", { text: t(`nav.${item.route}`) }),
  );
}

function buildShell() {
  const sidebar = h(
    "aside",
    { class: "sidebar", id: "sidebar" },
    h(
      "a",
      { class: "brand", href: "#/dashboard" },
      h("div", { class: "brand-mark", text: "FB" }),
      h(
        "div",
        { class: "brand-copy" },
        h("strong", { text: t("app.name") }),
        h("span", { text: t("app.tagline") }),
      ),
    ),
    h("div", { class: "nav-section", text: t("nav.section_main") }),
    h("nav", { class: "nav" }, ...NAV.filter((item) => item.route !== "settings").map(navLink)),
    h("div", { class: "nav-section", text: t("nav.section_system") }),
    h("nav", { class: "nav" }, ...NAV.filter((item) => item.route === "settings").map(navLink)),
    h(
      "div",
      { class: "sidebar-foot" },
      h(
        "div",
        { class: "bot-mini" },
        h("span", { class: "dot", id: "side-dot" }),
        h("div", {}, h("strong", { id: "side-bot", text: "—" }), h("small", { text: t("layout.logoutHint") })),
      ),
      h("div", { class: "version", id: "side-version", text: "" }),
    ),
  );

  const menuButton = button("", {
    variant: "ghost",
    title: t("nav.menu"),
    icon: "menu",
    onClick: () => sidebar.classList.toggle("open"),
  });
  menuButton.classList.add("menu-btn");
  menuButton.setAttribute("aria-label", t("nav.menu"));

  const serverName = h("span", { id: "top-server", text: t("layout.noServer") });
  const botDot = h("span", { class: "dot", id: "top-dot" });
  const botLabel = h("span", { id: "top-bot", text: t("layout.botDisconnected") });
  const pageTitle = h("span", { id: "top-title", class: "top-title", text: "" });
  const version = h("span", { id: "top-version", class: "top-version", text: "" });

  const topbar = h(
    "header",
    { class: "topbar" },
    h("div", { class: "topbar-left" }, menuButton, pageTitle),
    h(
      "div",
      { class: "topbar-right" },
      h("span", { class: "top-server" }, h("span", { class: "top-label", text: t("layout.server") }), serverName),
      h("span", { class: "top-bot" }, botDot, botLabel),
      version,
      button(t("common.refresh"), {
        variant: "ghost",
        icon: "refresh",
        title: t("layout.refreshStatus"),
        onClick: () => refreshStatus(true),
      }),
    ),
  );

  const page = h("main", { class: "page", id: "page" });
  const overlay = h("div", {
    class: "sidebar-overlay",
    onclick: () => sidebar.classList.remove("open"),
  });
  const shell = h("div", { class: "shell" }, sidebar, overlay, h("div", { class: "main" }, topbar, page));
  chrome = { sidebar, page, serverName, botDot, botLabel, pageTitle, version, sideDot: null, sideBot: null, sideVersion: null };
  return shell;
}

function updateChrome() {
  const status = store.status;
  const connected = Boolean(status?.bot?.connected);
  if (chrome.serverName) chrome.serverName.textContent = status?.guild?.name || t("layout.noServer");
  for (const dot of [chrome.botDot, document.getElementById("side-dot")]) {
    if (!dot) continue;
    dot.className = `dot ${connected ? "dot-ok" : "dot-off"}`;
  }
  const label = document.getElementById("top-bot");
  if (label) label.textContent = connected ? (status?.bot?.user || t("layout.botConnected")) : t("layout.botDisconnected");
  const sideBot = document.getElementById("side-bot");
  if (sideBot) sideBot.textContent = connected ? (status?.bot?.user || t("layout.botConnected")) : t("layout.botDisconnected");
  const version = document.getElementById("top-version");
  if (version) version.textContent = status ? `v${status.version}` : "";
  const sideVersion = document.getElementById("side-version");
  if (sideVersion) sideVersion.textContent = status ? `${t("layout.version")} ${status.version}` : "";
  const title = document.getElementById("top-title");
  if (title) title.textContent = t(`nav.${parseRoute()}`);
  document.querySelectorAll(".nav-link").forEach((link) => {
    link.classList.toggle("active", link.dataset.route === parseRoute());
  });
}

export async function refreshStatus(forcePage = false) {
  try {
    const status = await api("/api/status");
    setStatus(status);
    updateChrome();
    window.dispatchEvent(new CustomEvent("frabot:status", { detail: status }));
    if (!status.wizard?.completed && !wizardMode) {
      showWizard();
      return;
    }
    if (forcePage) await renderRoute(true);
  } catch (error) {
    if (error.status === 0) return;
  }
}

export function navigate(route) {
  const target = `#/${route}`;
  if (window.location.hash === target) {
    renderRoute(true);
  } else {
    window.location.hash = target;
  }
}

async function renderRoute(force = false) {
  const route = parseRoute();
  if (!chrome.page) return;
  if (cleanup) {
    try { cleanup(); } catch { /* page cleanup must not break navigation */ }
    cleanup = null;
  }
  updateChrome();
  clear(chrome.page);
  chrome.page.append(spinner(t("common.loading")));
  try {
    const ctx = {
      state: store,
      navigate,
      refreshStatus,
      reload: () => renderRoute(true),
      showWizard,
    };
    const result = await PAGES[route].render(ctx);
    if (typeof result === "function") cleanup = result;
  } catch (error) {
    clear(chrome.page);
    const retry = button(t("common.retry"), { variant: "primary", onClick: () => renderRoute(true) });
    chrome.page.append(
      errorBox(error.message || t("common.errorGeneric")),
      h("div", { class: "page-actions" }, retry),
    );
  }
}

function startPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(() => {
    if (!document.hidden) refreshStatus(false);
  }, 10000);
}

function startApp() {
  clearGuildData();
  wizardMode = false;
  if (pollTimer) clearInterval(pollTimer);
  if (cleanup) { try { cleanup(); } catch { /* ignore */ } cleanup = null; }
  root.replaceChildren(buildShell());
  updateChrome();
  startPolling();
  if (!hashBound) {
    window.addEventListener("hashchange", () => renderRoute());
    hashBound = true;
  }
  renderRoute();
}

function showWizardShell() {
  wizardMode = true;
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
  if (cleanup) { try { cleanup(); } catch { /* ignore */ } cleanup = null; }
  root.replaceChildren();
  renderWizard({
    onComplete: async () => {
      await loadI18n().catch(() => {});
      await refreshStatus(false);
      startApp();
    },
    onStatus: async () => {
      try {
        const status = await api("/api/status");
        setStatus(status);
      } catch { /* the wizard surfaces its own errors */ }
    },
  });
}

export function showWizard() {
  if (wizardMode) return;
  showWizardShell();
}

async function boot() {
  try {
    await loadI18n();
  } catch {
    root.replaceChildren(
      h("div", { class: "boot" }, h("div", { class: "boot-logo", text: "FB" }), h("p", { text: "Errore nel caricamento della lingua." })),
    );
    return;
  }
  document.title = t("app.title");
  try {
    const status = await api("/api/status");
    setStatus(status);
  } catch (error) {
    root.replaceChildren(
      h("div", { class: "boot" }, h("div", { class: "boot-logo", text: "FB" }), h("h1", { text: t("app.name") }), h("p", { text: error.message || t("common.errorGeneric") }),
        button(t("common.retry"), { variant: "primary", onClick: () => window.location.reload() })),
    );
    return;
  }
  if (!store.wizard?.completed) {
    showWizardShell();
  } else {
    startApp();
  }
}

boot();
