import { api, errorMessage } from "./api.js";
import { t, tList } from "./i18n.js";
import {
  brandMark, button, card, channelOptions, clear, copyText, field, h, input, select, spinner,
  textarea, toast, toggleRow,
} from "./ui.js";

let data = null;
let step = 1;
let body = null;
let errorEl = null;
let callbacks = {};
let busy = false;

const TOTAL = 7;
const DEV_PORTAL = "https://discord.com/developers/applications";
const TWITCH_CONSOLE = "https://dev.twitch.tv/console/apps";

function brandPanel() {
  return h(
    "aside",
    { class: "wizard-brand" },
    h(
      "div",
      { class: "brand" },
      brandMark(),
      h("div", { class: "brand-copy" },
        h("strong", {}, h("span", { text: "fra" }), h("em", { text: "/" }), h("span", { text: "bot" })),
        h("span", { text: t("app.tagline") })),
    ),
    h("h1", { text: t("wizard.title") }),
    h("p", { class: "wizard-brand-lead", text: t("wizard.step1Lead") }),
    h(
      "ul",
      { class: "feature-list" },
      h("li", {}, h("span", { class: "feature-index", text: "01" }), h("span", { text: t("wizard.step1NoMessageIntent") })),
      h("li", {}, h("span", { class: "feature-index", text: "02" }), h("span", { text: t("wizard.step1Volume") })),
      h("li", {}, h("span", { class: "feature-index", text: "03" }), h("span", { text: t("wizard.step1HowText") })),
    ),
    h("div", { class: "wizard-brand-foot" }, h("span", { text: "fra/bot" }), h("span", { text: "self-hosted / Umbrel" })),
  );
}

function progress() {
  const labels = tList("wizard.steps");
  return h(
    "div",
    { class: "wizard-progress" },
    ...Array.from({ length: TOTAL }, (_, index) => {
      const n = index + 1;
      const done = n < step;
      const active = n === step;
      return h(
        "div",
        { class: `wizard-step ${done ? "done" : ""} ${active ? "active" : ""}`, title: labels[index] || "" },
        h("span", { class: "wizard-step-dot", text: done ? "✓" : String(n) }),
        h("span", { class: "wizard-step-label", text: labels[index] || "" }),
      );
    }),
  );
}

function stepHeader(title, lead, back = true) {
  return h(
    "div",
    { class: "wizard-head" },
    h(
      "div",
      { class: "wizard-head-top" },
      h("div", { class: "eyebrow", text: t("wizard.step", { n: step }) }),
      back && step > 1
        ? button(t("common.back"), { variant: "ghost", onClick: () => setStep(step - 1) })
        : null,
    ),
    h("h2", { text: title }),
    lead ? h("p", { class: "wizard-lead", text: lead }) : null,
  );
}

function errorNode() {
  errorEl = h("div", { class: "inline-error hidden" });
  return errorEl;
}

function showError(message) {
  if (!errorEl) return;
  errorEl.textContent = message;
  errorEl.classList.remove("hidden");
}

function clearError() {
  errorEl?.classList.add("hidden");
}

function setLoading(target, loading, label = null) {
  if (!target) return;
  if (loading) {
    target.dataset.label = target.textContent;
    target.disabled = true;
    target.textContent = label || t("wizard.step2Verifying");
    target.classList.add("loading");
  } else {
    target.disabled = false;
    target.textContent = target.dataset.label || target.textContent;
    target.classList.remove("loading");
  }
}

function setStep(next) {
  if (busy) return;
  step = Math.max(1, Math.min(TOTAL, next));
  if (step === 6 && data && !data.config.modules.twitch) step = 7;
  render();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function saveStep(n, payload, target, loadingLabel) {
  if (busy) return null;
  busy = true;
  clearError();
  setLoading(target, true, loadingLabel);
  try {
    const response = await api(`/api/wizard/step/${n}`, { method: "PUT", body: payload });
    data = response;
    step = response.state?.step || n + 1;
    if (step === 6 && !data.config.modules.twitch) step = 7;
    render();
    return response;
  } catch (error) {
    showError(errorMessage(error));
    return null;
  } finally {
    busy = false;
    setLoading(target, false);
  }
}

async function showResult(message, type = "success") {
  showError("");
  const node = h("div", { class: `inline-success ${type}` }, h("span", { text: message }));
  errorEl?.replaceWith(node);
  errorEl = node;
}

function modulesSummary() {
  const modules = data.config.modules;
  const labels = [];
  if (modules.tickets) labels.push(t("nav.tickets"));
  if (modules.games) labels.push(t("nav.games"));
  if (modules.twitch) labels.push(t("nav.twitch"));
  return labels.length ? labels.join(" · ") : t("wizard.step7NoModules");
}

function step1() {
  return h(
    "div",
    {},
    stepHeader(t("wizard.step1Title"), t("wizard.step1Lead"), false),
    h(
      "div",
      { class: "wizard-grid" },
      card(t("wizard.step1Needs"),
        h("p", { text: t("wizard.step1Discord") }),
        h("p", { class: "muted", text: t("wizard.step1Twitch") })),
      card(t("wizard.step1How"),
        h("p", { text: t("wizard.step1HowText") }),
        h("p", { class: "muted", text: t("wizard.step1NoMessageIntent") })),
    ),
    h("div", { class: "wizard-actions" },
      button(t("wizard.start"), {
        variant: "primary",
        onClick: async (event) => {
          const response = await saveStep(1, {}, event.currentTarget, t("common.loading"));
          if (response) setStep(2);
        },
      })),
  );
}

function step2() {
  const appId = input({
    value: data.config.discord.application_id || "",
    placeholder: t("wizard.step2AppIdPlaceholder"),
    maxlength: 22,
  });
  const token = input({
    type: "password",
    placeholder: data.config.discord.has_bot_token ? t("wizard.step2TokenSaved") : t("wizard.step2TokenPlaceholder"),
    autocomplete: "new-password",
  });
  const verify = button(t("wizard.step2Verify"), {
    variant: "primary",
    onClick: async (event) => {
      if (!appId.value.trim()) {
        showError(t("wizard.needAppId"));
        return;
      }
      if (!token.value.trim() && !data.config.discord.has_bot_token) {
        showError(t("wizard.needToken"));
        return;
      }
      const response = await saveStep(2, { application_id: appId.value.trim(), bot_token: token.value.trim() }, event.currentTarget);
      if (response) {
        toast(t("wizard.step2Verified", { name: response.config.discord.bot_name || "FraBot" }), "success");
        setStep(3);
      }
    },
  });
  return h(
    "div",
    {},
    stepHeader(t("wizard.step2Title"), t("wizard.step2Lead")),
    h("div", { class: "instructions" },
      h("ol", {},
        h("li", { text: t("wizard.step2Instruction1") }),
        h("li", { text: t("wizard.step2Instruction2") }),
        h("li", { text: t("wizard.step2Instruction3") }),
        h("li", { text: t("wizard.step2Instruction4") }))),
    h("a", { class: "text-link", href: DEV_PORTAL, target: "_blank", rel: "noreferrer noopener", text: `${t("wizard.step2OpenPortal")} ↗` }),
    h("div", { class: "form-grid two" },
      field(t("wizard.step2AppId"), appId),
      field(t("wizard.step2Token"), token)),
    errorNode(),
    h("p", { class: "security-note", text: t("wizard.step2Security") }),
    h("div", { class: "wizard-actions" }, verify),
  );
}

function step3() {
  const link = data.invite_url;
  const urlInput = input({ value: link, disabled: true });
  const check = button(t("wizard.step3Added"), {
    variant: "primary",
    onClick: async (event) => {
      const response = await saveStep(3, {}, event.currentTarget, t("wizard.step3Checking"));
      if (!response) return;
      if (response.auto_selected) {
        toast(t("wizard.step3Found", { count: 1 }), "success");
        step = 5;
        render();
      } else {
        step = 4;
        render();
      }
    },
  });
  return h(
    "div",
    {},
    stepHeader(t("wizard.step3Title"), t("wizard.step3Lead")),
    link
      ? h("div", { class: "copy-row" },
          field(t("wizard.step3Link"), urlInput),
          h("div", { class: "copy-actions" },
            button(t("common.copyLink"), { variant: "secondary", onClick: () => copyText(link) }),
            h("a", { class: "btn primary", href: link, target: "_blank", rel: "noreferrer noopener", text: t("wizard.step3OpenLink") })))
      : h("div", { class: "inline-error", text: t("wizard.step3NoLink") }),
    h("div", { class: "permission-box" },
      h("strong", { text: t("wizard.step3Permissions") }),
      h("p", { text: t("wizard.step3PermissionsText") }),
      h("div", { class: "chips" },
        h("span", { class: "chip", text: t("wizard.step3Scopes") }),
        h("span", { class: "chip", text: `permissions=${data.permissions}` }))),
    errorNode(),
    h("div", { class: "wizard-actions" }, check),
  );
}

function step4() {
  const guilds = data.bot?.guilds || [];
  let selected = data.config.discord.guild_id || guilds[0]?.id || "";
  const list = h("div", { class: "guild-grid" });
  for (const guild of guilds) {
    const radio = h("input", { type: "radio", name: "guild", value: guild.id });
    radio.checked = guild.id === selected;
    radio.addEventListener("change", () => { selected = guild.id; });
    const label = h("label", { class: `guild-card ${guild.id === selected ? "selected" : ""}` },
      radio,
      h("div", { class: "guild-icon", text: (guild.name || "?").slice(0, 2).toUpperCase() }),
      h("div", {}, h("strong", { text: guild.name }), h("small", { text: `${guild.member_count ?? "—"} membri` })));
    radio.addEventListener("change", () => {
      list.querySelectorAll(".guild-card").forEach((card) => card.classList.remove("selected"));
      label.classList.add("selected");
    });
    list.append(label);
  }
  const refreshButton = button(t("common.refresh"), {
    variant: "ghost",
    onClick: async () => {
      try {
        data = await api("/api/wizard");
        render();
      } catch (error) {
        showError(errorMessage(error));
      }
    },
  });
  return h(
    "div",
    {},
    stepHeader(t("wizard.step4Title"), t("wizard.step4Lead")),
    guilds.length ? list : h("div", { class: "empty" }, h("p", { text: t("wizard.step3NoGuild") })),
    errorNode(),
    h("div", { class: "wizard-actions" },
      refreshButton,
      button(t("common.next"), {
        variant: "primary",
        disabled: !guilds.length,
        onClick: async (event) => {
          if (!selected) { showError(t("wizard.needGuild")); return; }
          const response = await saveStep(4, { guild_id: selected }, event.currentTarget);
          if (response) {
            toast(t("wizard.step4Selected", { name: response.config.discord.guild_name || "" }), "success");
            setStep(5);
          }
        },
      })),
  );
}

async function step5() {
  const wrap = h("div", {});
  wrap.append(spinner(t("common.loading")));
  const guildId = data.config.discord.guild_id || data.bot?.guilds?.[0]?.id;
  let detail;
  try {
    detail = await api(`/api/discord/guild/${guildId}`);
  } catch (error) {
    wrap.replaceChildren(h("div", { class: "inline-error", text: errorMessage(error) }));
    return wrap;
  }
  if (step !== 5) return h("div", {});
  const channels = channelOptions(detail.channels, ["text"]);
  const modules = { ...data.config.modules };
  const tickets = { ...data.config.tickets };
  const gamesChannels = data.config.games_channels?.[0] || "";

  const panelSelect = select({
    options: channels,
    value: tickets.panel_channel_id,
    placeholder: t("common.selectChannel"),
  });
  const logSelect = select({
    options: channels,
    value: tickets.log_channel_id,
    placeholder: t("common.none"),
  });
  const gamesSelect = select({
    options: channels,
    value: gamesChannels,
    placeholder: t("wizard.step5AllChannels"),
  });
  const ticketFields = h("div", { class: "module-config" },
    field(t("wizard.step5PanelChannel"), panelSelect),
    field(t("wizard.step5LogChannel"), logSelect),
    h("p", { class: "field-hint", text: t("wizard.step5TicketNote") }));
  const gamesField = h("div", { class: "module-config" },
    field(t("wizard.step5GamesChannel"), gamesSelect));

  const syncVisibility = () => {
    ticketFields.classList.toggle("hidden", !modules.tickets);
    gamesField.classList.toggle("hidden", !modules.games);
  };

  const moduleCard = (key, title, hint, iconText) => {
    const box = h("input", { type: "checkbox", class: "switch-input" });
    box.checked = modules[key];
    box.addEventListener("change", (event) => {
      modules[key] = event.target.checked;
      syncVisibility();
    });
    return h(
      "div",
      { class: "module-card" },
      h("div", { class: "module-icon", text: iconText }),
      h("div", { class: "module-copy" }, h("strong", { text: title }), h("small", { text: hint })),
      h("label", { class: "switch" }, box, h("span", { class: "switch-track" })),
    );
  };

  wrap.replaceChildren(
    stepHeader(t("wizard.step5Title"), t("wizard.step5Lead")),
    h("div", { class: "module-grid" },
      moduleCard("tickets", t("wizard.step5Tickets"), t("wizard.step5TicketsHint"), "🎫"),
      moduleCard("games", t("wizard.step5Games"), t("wizard.step5GamesHint"), "🎮"),
      moduleCard("twitch", t("wizard.step5Twitch"), t("wizard.step5TwitchHint"), "📡")),
    ticketFields,
    gamesField,
    errorNode(),
    h("div", { class: "wizard-actions" },
      button(t("common.next"), {
        variant: "primary",
        onClick: async (event) => {
          if (modules.tickets && !panelSelect.value) {
            showError(t("wizard.step5Required"));
            return;
          }
          const response = await saveStep(5, {
            modules,
            tickets: {
              panel_channel_id: panelSelect.value,
              log_channel_id: logSelect.value,
            },
            games_channels: gamesSelect.value ? [gamesSelect.value] : [],
          }, event.currentTarget);
          if (response) {
            setStep(response.state.step);
          }
        },
      })),
  );
  syncVisibility();
  return wrap;
}

function step6() {
  const cfg = data.config.twitch;
  const clientId = input({ value: cfg.client_id || "", placeholder: "Client ID" });
  const secret = input({
    type: "password",
    placeholder: cfg.has_client_secret ? t("wizard.step6SecretSaved") : t("wizard.step6Secret"),
    autocomplete: "new-password",
  });
  return h(
    "div",
    {},
    stepHeader(t("wizard.step6Title"), t("wizard.step6Lead")),
    h("div", { class: "instructions" },
      h("ol", {},
        h("li", { text: t("wizard.step6Instruction1") }),
        h("li", { text: t("wizard.step6Instruction2") }),
        h("li", { text: t("wizard.step6Instruction3") }))),
    h("a", { class: "text-link", href: TWITCH_CONSOLE, target: "_blank", rel: "noreferrer noopener", text: `${t("wizard.step6Portal")} ↗` }),
    h("div", { class: "form-grid two" },
      field(t("wizard.step6ClientId"), clientId),
      field(t("wizard.step6Secret"), secret)),
    errorNode(),
    h("div", { class: "wizard-actions" },
      button(t("wizard.step6Verify"), {
        variant: "primary",
        onClick: async (event) => {
          if (!clientId.value.trim() || (!secret.value.trim() && !cfg.has_client_secret)) {
            showError(t("wizard.needTwitch"));
            return;
          }
          const response = await saveStep(6, {
            client_id: clientId.value.trim(),
            client_secret: secret.value.trim(),
            update_on_end: true,
          }, event.currentTarget);
          if (response) {
            toast(t("wizard.step6Verified"), "success");
            setStep(7);
          }
        },
      })),
  );
}

async function step7() {
  const channels = [];
  try {
    const guildId = data.config.discord.guild_id;
    if (guildId) {
      const detail = await api(`/api/discord/guild/${guildId}`);
      channels.push(...channelOptions(detail.channels, ["text"]));
    }
  } catch { /* the test select simply stays empty */ }
  if (step !== 7) return h("div", {});
  const testSelect = select({
    options: channels,
    value: data.config.setup?.test_channel_id || data.config.tickets?.panel_channel_id || channels[0]?.value || "",
    placeholder: t("common.selectChannel"),
  });
  let testLink = null;
  const testResult = h("div", { class: "inline-success hidden" });
  const sendTest = button(t("wizard.step7SendTest"), {
    variant: "secondary",
    onClick: async (event) => {
      if (!testSelect.value) { showError(t("wizard.needTestChannel")); return; }
      clearError();
      setLoading(event.currentTarget, true, t("common.loading"));
      try {
        const response = await api("/api/wizard/test-message", { method: "POST", body: { channel_id: testSelect.value } });
        testLink = response.message?.url;
        data.state = { ...data.state, ...response.wizard, completed: false };
        testResult.classList.remove("hidden");
        clear(testResult);
        testResult.append(h("span", { text: t("wizard.step7TestSent") }));
        if (testLink) {
          testResult.append(" ", h("a", { href: testLink, target: "_blank", rel: "noreferrer noopener", class: "text-link", text: t("wizard.step7OpenLink") }));
        }
        toast(t("common.testSent"), "success");
        render();
      } catch (error) {
        showError(errorMessage(error));
      } finally {
        setLoading(event.currentTarget, false);
      }
    },
  });

  const finish = button(t("wizard.step7Finish"), {
    variant: "primary",
    disabled: !data.state.test_sent,
    onClick: async (event) => {
      if (!data.state.test_sent) { showError(t("wizard.step7NeedTest")); return; }
      setLoading(event.currentTarget, true, t("wizard.step7Finishing"));
      try {
        await api("/api/wizard/complete", { method: "POST" });
        toast(t("wizard.step7TestSent"), "success");
        callbacks.onComplete?.();
      } catch (error) {
        showError(errorMessage(error));
        setLoading(event.currentTarget, false);
      }
    },
  });

  const summary = h("div", { class: "summary" },
    h("div", { class: "summary-row" }, h("span", { text: t("wizard.step7Discord") }), h("strong", { text: data.config.discord.bot_name || "—" })),
    h("div", { class: "summary-row" }, h("span", { text: t("settings.applicationId") }), h("strong", { text: data.config.discord.application_id || "—" })),
    h("div", { class: "summary-row" }, h("span", { text: t("wizard.step7Guild") }), h("strong", { text: data.config.discord.guild_name || data.bot?.guild_name || "—" })),
    h("div", { class: "summary-row" }, h("span", { text: t("wizard.step7Modules") }), h("strong", { text: modulesSummary() })),
    data.config.modules.tickets
      ? h("div", { class: "summary-row" }, h("span", { text: t("tickets.panelChannel") }), h("strong", { text: channels.find((c) => c.value === data.config.tickets.panel_channel_id)?.label || "—" }))
      : null,
    data.config.modules.twitch
      ? h("div", { class: "summary-row" }, h("span", { text: "Twitch" }), h("strong", { text: data.state.twitch_verified ? t("wizard.step7TwitchVerified") : "—" }))
      : null,
  );

  return h(
    "div",
    {},
    stepHeader(t("wizard.step7Title"), t("wizard.step7Lead")),
    summary,
    h("div", { class: "test-panel" },
      field(t("wizard.step7TestChannel"), testSelect, t("wizard.step7TestHint")),
      h("div", { class: "page-actions" }, sendTest),
      testResult),
    errorNode(),
    h("div", { class: "wizard-actions" }, finish),
  );
}

function render() {
  const shell = document.getElementById("app");
  const bodyHolder = h("div", { class: "wizard-body-host" });
  body = bodyHolder;
  const panel = h(
    "section",
    { class: "wizard-panel" },
    progress(),
    h("div", { class: "wizard-card" }, bodyHolder),
  );
  shell.replaceChildren(h("div", { class: "wizard-shell" }, brandPanel(), panel));
  const renderers = { 1: step1, 2: step2, 3: step3, 4: step4, 5: step5, 6: step6, 7: step7 };
  const output = renderers[step]?.();
  if (output instanceof Node) {
    bodyHolder.replaceChildren(output);
  } else if (output && typeof output.then === "function") {
    bodyHolder.replaceChildren(spinner(t("common.loading")));
    output.then((node) => {
      if (step === 5 || step === 7) bodyHolder.replaceChildren(node);
    }).catch((error) => {
      bodyHolder.replaceChildren(h("div", { class: "inline-error", text: errorMessage(error) }));
    });
  }
}

export async function renderWizard(options = {}) {
  callbacks = options;
  step = 1;
  const shell = document.getElementById("app");
  shell.replaceChildren(h("div", { class: "wizard-shell" }, brandPanel(), h("section", { class: "wizard-panel" }, spinner(t("common.loading")))));
  try {
    data = await api("/api/wizard");
    step = data.state?.step || 1;
    if (step === 6 && !data.config.modules.twitch) step = 7;
    render();
  } catch (error) {
    shell.replaceChildren(
      h("div", { class: "boot" }, brandMark("boot-logo"), h("p", { text: errorMessage(error) }),
        button(t("common.retry"), { variant: "primary", onClick: () => renderWizard(options) })),
    );
  }
}
