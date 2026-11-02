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

const SVG_ICONS = {
  dashboard: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  tickets: '<path d="M4 7a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v2a2 2 0 0 0 0 4v2a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-2a2 2 0 0 0 0-4Z"/><path d="M13 5v2M13 11v2M13 17v2"/>',
  games: '<path d="M7 8h10a4 4 0 0 1 3.9 4.9l-.6 2.8A3 3 0 0 1 15.7 17l-1.2-1.4H9.5L8.3 17a3 3 0 0 1-4.6-1.3l-.6-2.8A4 4 0 0 1 7 8Z"/><path d="M8 11v3M6.5 12.5h3M15 11h.01M17 13h.01"/>',
  twitch: '<path d="M4.5 11a7.5 7.5 0 0 1 15 0"/><path d="M7.5 11a4.5 4.5 0 0 1 9 0"/><circle cx="12" cy="11" r="1"/><path d="M12 18v3M8 21h8"/>',
  logs: '<path d="M8 6h12M8 12h12M8 18h12"/><circle cx="4" cy="6" r="1"/><circle cx="4" cy="12" r="1"/><circle cx="4" cy="18" r="1"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06A1.7 1.7 0 0 0 15 19.4a1.7 1.7 0 0 0-1 .6 1.7 1.7 0 0 0-.4 1.1V21a2 2 0 1 1-4 0v-.09A1.7 1.7 0 0 0 8.6 19.4a1.7 1.7 0 0 0-1.88.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-.6-1 1.7 1.7 0 0 0-1.1-.4H3a2 2 0 1 1 0-4h.09A1.7 1.7 0 0 0 4.6 8.6a1.7 1.7 0 0 0-.34-1.88l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-.6 1.7 1.7 0 0 0 .4-1.1V3a2 2 0 1 1 4 0v.09a1.7 1.7 0 0 0 1 1.51 1.7 1.7 0 0 0 1.88-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.7 1.7 0 0 0 19.4 9c.2.36.5.7.9.9.35.2.75.3 1.1.3H21a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.51.8Z"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  trash: '<path d="M3 6h18M8 6V4h8v2M19 6l-1 15H6L5 6M10 11v5M14 11v5"/>',
  edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
  refresh: '<path d="M20 11a8 8 0 1 0-2.3 5.7M20 5v6h-6"/>',
  external: '<path d="M15 3h6v6M10 14 21 3M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
  chevron: '<path d="m9 18 6-6-6-6"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  close: '<path d="M6 6l12 12M18 6 6 18"/>',
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
  copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/>',
  bot: '<rect x="4" y="8" width="16" height="12" rx="3"/><path d="M12 4v4M9 13h.01M15 13h.01M9 16h6"/><circle cx="12" cy="3" r="1"/>',
  server: '<rect x="4" y="3" width="16" height="7" rx="2"/><rect x="4" y="14" width="16" height="7" rx="2"/><path d="M8 7h.01M8 17h.01"/>',
  activity: '<path d="M3 12h4l2.5-6 4 12 2.5-6h5"/>',
  database: '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  tag: '<path d="M20.6 13.4 12 22l-9-9V3h10l7.6 7.6a2 2 0 0 1 0 2.8Z"/><circle cx="7.5" cy="7.5" r="1"/>',
  alert: '<path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9 2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
};

export const ICONS = SVG_ICONS;

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
  if (options.icon) node.prepend(icon(options.icon, "btn-icon"));
  return node;
}

export function icon(name, className = "ico") {
  const node = h("span", { class: className, "aria-hidden": "true" });
  const markup = SVG_ICONS[name];
  if (!markup) {
    node.textContent = "•";
    return node;
  }
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "1.8");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.innerHTML = markup;
  node.append(svg);
  return node;
}

export function brandMark(className = "brand-mark") {
  return h(
    "span",
    { class: className, "aria-hidden": "true" },
    h("img", { src: "/static/icon.svg", alt: "" }),
  );
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
  const color = embed.color ? `#${Number(embed.color).toString(16).padStart(6, "0")}` : "#D2E85C";
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
