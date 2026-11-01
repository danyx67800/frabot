import { t } from "./i18n.js";

export function h(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key === "dataset") Object.assign(node.dataset, value);
    else if (key.startsWith("on") && typeof value === "function") {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (key === "value") node.value = value;
    else if (["checked", "disabled", "selected", "multiple", "required"].includes(key)) {
      node[key] = Boolean(value);
    } else if (key === "html") node.innerHTML = value;
    else node.setAttribute(key, value);
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
  return node;
}

export const ICONS = {
  dashboard: "▦",
  tickets: "🎫",
  games: "🎮",
  twitch: "📡",
  logs: "≣",
  settings: "⚙",
  plus: "＋",
  trash: "🗑",
  edit: "✎",
  refresh: "↻",
  external: "↗",
  chevron: "›",
  check: "✓",
  close: "✕",
  menu: "☰",
  copy: "⧉",
  search: "⌕",
};

export function button(label, options = {}) {
  const node = h(
    "button",
    {
      class: `btn ${options.variant || "secondary"}${options.small ? " btn-sm" : ""}`,
      type: options.type || "button",
      disabled: options.disabled,
      title: options.title || null,
      "aria-label": options.ariaLabel || (label ? null : options.title),
      onclick: options.onClick,
    },
    options.emoji ? h("span", { class: "btn-emoji", text: options.emoji }) : null,
    label ? h("span", { text: label }) : null,
  );
  if (options.icon) {
    node.prepend(h("span", { class: "btn-emoji", "aria-hidden": "true", text: ICONS[options.icon] || options.icon }));
  }
  return node;
}

export function icon(name) {
  return h("span", { class: "ico", "aria-hidden": "true", text: ICONS[name] || "•" });
}

export function card(title, ...children) {
  return h(
    "section",
    { class: "card" },
    title ? h("div", { class: "card-head" }, h("h2", { text: title })) : null,
    h("div", { class: "card-body" }, ...children),
  );
}

export function field(label, control, hint = "", className = "") {
  return h(
    "label",
    { class: `field ${className}` },
    h("span", { class: "field-label", text: label }),
    control,
    hint ? h("span", { class: "field-hint", text: hint }) : null,
  );
}

export function input(options = {}) {
  return h("input", {
    class: "input",
    type: options.type || "text",
    value: options.value ?? "",
    placeholder: options.placeholder || "",
    min: options.min,
    max: options.max,
    step: options.step,
    maxlength: options.maxlength,
    autocomplete: "off",
    disabled: options.disabled,
    name: options.name,
  });
}

export function textarea(options = {}) {
  const node = h("textarea", {
    class: "input textarea",
    placeholder: options.placeholder || "",
    maxlength: options.maxlength,
    rows: options.rows || 4,
    disabled: options.disabled,
  });
  node.value = options.value || "";
  return node;
}

export function select(options = {}) {
  const node = h("select", {
    class: "input",
    multiple: options.multiple,
    size: options.multiple ? options.size || 5 : undefined,
    disabled: options.disabled,
  });
  if (options.placeholder) {
    node.append(h("option", { value: "", text: options.placeholder, disabled: options.required }));
  }
  const values = options.multiple
    ? new Set((options.value || []).map(String))
    : String(options.value ?? "");
  for (const option of options.options || []) {
    const opt = h("option", { value: option.value, text: option.label });
    opt.selected = options.multiple ? values.has(String(option.value)) : values === String(option.value);
    node.append(opt);
  }
  if (options.onChange) node.addEventListener("change", options.onChange);
  return node;
}

export function checkbox(label, checked = false, onChange = null) {
  const box = h("input", { type: "checkbox" });
  box.checked = Boolean(checked);
  if (onChange) box.addEventListener("change", onChange);
  return h("label", { class: "checkbox" }, box, h("span", { text: label }));
}

export function toggleRow(label, description, checked, onChange = null) {
  const box = h("input", { type: "checkbox", class: "switch-input" });
  box.checked = Boolean(checked);
  if (onChange) box.addEventListener("change", onChange);
  return h(
    "label",
    { class: "toggle-row" },
    h("span", { class: "toggle-copy" }, h("strong", { text: label }), description ? h("small", { text: description }) : null),
    h("span", { class: "switch" }, box, h("span", { class: "switch-track" })),
  );
}

export function badge(text, tone = "neutral") {
  return h("span", { class: `badge badge-${tone}`, text });
}

export function spinner(label = "") {
  return h(
    "div",
    { class: "spinner-wrap" },
    h("span", { class: "spinner" }),
    label ? h("span", { text: label }) : null,
  );
}

export function emptyState(text) {
  return h("div", { class: "empty" }, h("span", { class: "empty-mark", text: "◇" }), h("p", { text }));
}

export function pageHeader(title, subtitle, actions = []) {
  return h(
    "div",
    { class: "page-head" },
    h("div", {}, h("h1", { text: title }), subtitle ? h("p", { text: subtitle }) : null),
    h("div", { class: "page-actions" }, ...actions),
  );
}

export function errorBox(message) {
  return h("div", { class: "error-box" }, h("strong", { text: t("common.loadingError") }), h("span", { text: message }));
}

export function toast(message, type = "info") {
  const root = document.getElementById("toasts");
  const node = h("div", { class: `toast toast-${type}`, role: "status" }, h("span", { text: message }));
  root.append(node);
  setTimeout(() => {
    node.classList.add("toast-out");
    setTimeout(() => node.remove(), 250);
  }, 4200);
}

let modalClose = null;

export function openModal({ title, body, actions = [], wide = false, onClose = null }) {
  const root = document.getElementById("modal-root");
  if (modalClose) modalClose(true);
  const close = (silent = false) => {
    overlay.remove();
    document.body.classList.remove("modal-open");
    document.removeEventListener("keydown", onKey);
    modalClose = null;
    if (!silent && onClose) onClose();
  };
  const onKey = (event) => {
    if (event.key === "Escape") close();
  };
  const footer = actions.length
    ? h("div", { class: "modal-foot" }, ...actions.map((action) =>
        action instanceof Node ? action : button(action.label, action)))
    : null;
  const closeButton = h("button", {
    class: "icon-btn",
    type: "button",
    "aria-label": t("common.close"),
    onclick: () => close(),
    text: "✕",
  });
  const overlay = h(
    "div",
    { class: "modal-overlay", role: "presentation", onclick: (event) => { if (event.target === overlay) close(); } },
    h(
      "div",
      { class: `modal ${wide ? "modal-wide" : ""}`, role: "dialog", "aria-modal": "true" },
      h("div", { class: "modal-head" }, h("h2", { text: title }), closeButton),
      h("div", { class: "modal-body" }, body),
      footer,
    ),
  );
  root.replaceChildren(overlay);
  document.body.classList.add("modal-open");
  document.addEventListener("keydown", onKey);
  modalClose = close;
  setTimeout(() => overlay.querySelector("input,textarea,select,button")?.focus(), 30);
  return { close, overlay };
}

export function confirmDialog({ title, text, confirmLabel, danger = false }) {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      modal.close(true);
      resolve(value);
    };
    const modal = openModal({
      title: title || t("common.confirmDeleteTitle"),
      body: h("p", { class: "modal-text", text: text || t("common.confirmDeleteText") }),
      actions: [
        button(t("common.cancel"), { onClick: () => finish(false) }),
        button(confirmLabel || t("common.confirm"), {
          variant: danger ? "danger" : "primary",
          onClick: () => finish(true),
        }),
      ],
      onClose: () => finish(false),
    });
  });
}

export function fmtDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString("it-IT", { dateStyle: "short", timeStyle: "short" });
}

export function fmtNumber(value) {
  const number = Number(value);
  if (Number.isNaN(number)) return "—";
  return number.toLocaleString("it-IT");
}

export function fmtDuration(seconds) {
  if (seconds === null || seconds === undefined) return "—";
  let rest = Math.max(0, Math.round(Number(seconds)));
  const days = Math.floor(rest / 86400);
  rest %= 86400;
  const hours = Math.floor(rest / 3600);
  rest %= 3600;
  const minutes = Math.floor(rest / 60);
  const secs = rest % 60;
  if (days) return `${days} ${t("common.days")} ${hours} ${t("common.hours")}`;
  if (hours) return `${hours} ${t("common.hours")} ${minutes} ${t("common.minutes")}`;
  if (minutes) return `${minutes} ${t("common.minutes")}`;
  return `${secs} ${t("common.seconds")}`;
}

export function fmtUptime(seconds) {
  if (seconds === null || seconds === undefined) return "—";
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (days) return `${days}g ${hours}h`;
  if (hours) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast(t("common.copied"), "success");
  } catch {
    const area = h("textarea", { class: "sr-only" });
    area.value = text;
    document.body.append(area);
    area.select();
    document.execCommand("copy");
    area.remove();
    toast(t("common.copied"), "success");
  }
}

export function statusDot(connected) {
  return h("span", { class: `dot ${connected ? "dot-ok" : "dot-off"}` });
}

export function channelOptions(channels, types = ["text"]) {
  return channels
    .filter((channel) => types.includes(channel.type))
    .map((channel) => ({
      value: channel.id,
      label: channel.type === "category" ? `▸ ${channel.name}` : `# ${channel.name}`,
    }));
}

export function roleOptions(roles) {
  return roles.map((role) => ({ value: role.id, label: `@ ${role.name}` }));
}

export function embedPreview(embed, content = "", footerOverride = "") {
  if (!embed) return emptyState(t("common.noData"));
  const color = embed.color ? `#${Number(embed.color).toString(16).padStart(6, "0")}` : "#8b6dff";
  const thumbnail = embed.thumbnail?.url;
  return h(
    "div",
    { class: "discord-preview" },
    content ? h("div", { class: "discord-mention", text: content }) : null,
    h(
      "div",
      { class: "discord-embed", style: `border-left-color:${color}` },
      h(
        "div",
        { class: "discord-embed-grid" },
        h(
          "div",
          {},
          embed.title ? h("div", { class: "discord-title", text: embed.title }) : null,
          embed.description ? h("div", { class: "discord-desc", text: embed.description }) : null,
          ...(embed.fields || []).map((item) =>
            h("div", { class: "discord-field" }, h("b", { text: item.name }), h("div", { text: item.value }))),
        ),
        thumbnail ? h("img", { class: "discord-thumb", src: thumbnail, alt: "", loading: "lazy" }) : null,
      ),
      h("div", { class: "discord-footer", text: footerOverride || embed.footer?.text || "" }),
    ),
  );
}

export function showFormError(container, message) {
  container.replaceChildren(h("div", { class: "inline-error", text: message }));
}

export function hide(node) {
  node?.classList.add("hidden");
}

export function show(node) {
  node?.classList.remove("hidden");
}
