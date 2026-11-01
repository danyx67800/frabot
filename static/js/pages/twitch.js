import { api, errorMessage } from "../api.js";
import { guildData } from "../data.js";
import { t } from "../i18n.js";
import {
  badge, button, card, channelOptions, confirmDialog, embedPreview, emptyState, field,
  fmtDate, h, input, openModal, pageHeader, roleOptions, select, textarea, toast,
} from "../ui.js";

function mentionLabel(streamer, roles) {
  if (streamer.mention_type === "everyone") return t("twitch.mentionEveryone");
  if (streamer.mention_type === "role") {
    const role = roles.find((item) => item.value === streamer.mention_role_id);
    return role ? role.label : t("common.roleFallback", { id: streamer.mention_role_id });
  }
  return t("twitch.mentionNone");
}

function streamerStatus(streamer) {
  if (streamer.not_found) return [t("twitch.statusNotFound"), "error"];
  if (streamer.is_live) return [t("twitch.statusLive"), "ok"];
  if (streamer.last_error) return [t("twitch.statusError"), "warn"];
  return [t("twitch.statusOffline"), "neutral"];
}

export async function render(ctx) {
  const [data, guild] = await Promise.all([
    api("/api/twitch"),
    guildData().catch(() => null),
  ]);
  let streamers = data.streamers;
  const textChannels = channelOptions(guild?.channels || [], ["text"]);
  const roles = roleOptions(guild?.roles || []);
  const channelName = (id) => textChannels.find((channel) => channel.value === id)?.label || (id ? `#${id}` : "—");

  const page = h("div", {});
  page.append(pageHeader(t("twitch.title"), t("twitch.subtitle"), [
    button(t("common.refresh"), { variant: "ghost", onClick: () => ctx.reload() }),
  ]));

  // -- credentials -----------------------------------------------------
  const enabled = h("input", { type: "checkbox", class: "switch-input" });
  enabled.checked = data.enabled;
  const clientId = input({ value: data.config.client_id || "", placeholder: "Client ID", maxlength: 100 });
  const secret = input({
    type: "password",
    placeholder: data.config.has_client_secret ? t("twitch.secretSaved") : t("twitch.clientSecret"),
    autocomplete: "new-password",
  });
  const updateOnEnd = h("input", { type: "checkbox" });
  updateOnEnd.checked = data.config.update_on_end;
  const monitorInfo = h("div", { class: "monitor-info" });
  function renderMonitor() {
    // Node.replaceChildren() stringifies null, so conditional nodes must be
    // filtered before being passed to it.
    monitorInfo.replaceChildren(...[
      badge(data.monitor.running ? t("common.online") : t("common.offline"), data.monitor.running ? "ok" : "warn"),
      h("span", { class: "muted small", text: t("twitch.polling", { s: data.monitor.poll_seconds }) }),
      h("span", { class: "muted small", text: `${t("twitch.lastChecked")}: ${data.monitor.last_run ? fmtDate(data.monitor.last_run) : t("common.never")}` }),
      data.monitor.last_error ? h("span", { class: "small error-text", text: data.monitor.last_error }) : null,
    ].filter(Boolean));
  }
  renderMonitor();

  const testButton = button(t("twitch.testConfig"), {
    variant: "ghost",
    onClick: async (event) => {
      event.currentTarget.disabled = true;
      try {
        await api("/api/twitch/config/test", {
          method: "POST",
          body: { client_id: clientId.value.trim(), client_secret: secret.value.trim() },
        });
        toast(t("twitch.testOk"), "success");
      } catch (error) {
        toast(errorMessage(error), "error");
      } finally {
        event.currentTarget.disabled = false;
      }
    },
  });
  const saveConfig = button(t("twitch.saveConfig"), {
    variant: "primary",
    onClick: async (event) => {
      event.currentTarget.disabled = true;
      try {
        data = await api("/api/twitch/config", {
          method: "PUT",
          body: {
            client_id: clientId.value.trim(),
            client_secret: secret.value.trim(),
            update_on_end: updateOnEnd.checked,
            enabled: enabled.checked,
          },
        });
        streamers = data.streamers;
        renderStreamers();
        renderMonitor();
        toast(t("twitch.configSaved"), "success");
      } catch (error) {
        toast(errorMessage(error), "error");
      } finally {
        event.currentTarget.disabled = false;
      }
    },
  });

  page.append(card(t("twitch.configTitle"),
    h("p", { class: "muted", text: t("twitch.configHint") }),
    h("div", { class: "form-grid two" },
      field(t("twitch.clientId"), clientId),
      field(t("twitch.clientSecret"), secret)),
    h("div", { class: "inline-options" },
      h("label", { class: "switch-row" }, h("span", { text: t("twitch.enabled") }), h("span", { class: "switch" }, enabled, h("span", { class: "switch-track" }))),
      h("label", { class: "checkbox" }, updateOnEnd, h("span", { text: t("twitch.updateOnEnd") }))),
    h("div", { class: "page-actions" }, testButton, saveConfig),
    monitorInfo));

  // -- streamers -------------------------------------------------------
  const streamerBody = h("div", {});
  function renderStreamers() {
    streamerBody.replaceChildren();
    if (!streamers.length) {
      streamerBody.append(emptyState(t("twitch.noStreamers")));
      return;
    }
    const grid = h("div", { class: "streamer-grid" });
    for (const streamer of streamers) {
      const [statusLabel, tone] = streamerStatus(streamer);
      grid.append(h("div", { class: `streamer-card ${streamer.is_live ? "live" : ""}` },
        h("div", { class: "streamer-head" },
          h("div", { class: "avatar", text: (streamer.display_name || streamer.login).slice(0, 2).toUpperCase() }),
          h("div", { class: "streamer-title" },
            h("strong", { text: streamer.display_name || streamer.login }),
            h("small", { text: `@${streamer.login}` })),
          badge(statusLabel, tone)),
        h("div", { class: "streamer-meta" },
          h("div", {}, h("span", { class: "meta-label", text: t("twitch.channel") }), h("span", { text: channelName(streamer.channel_id) })),
          h("div", {}, h("span", { class: "meta-label", text: t("twitch.mention") }), h("span", { text: mentionLabel(streamer, roles) })),
          h("div", {}, h("span", { class: "meta-label", text: t("twitch.lastChecked") }), h("span", { text: streamer.last_checked ? fmtDate(streamer.last_checked) : t("common.never") }))),
        streamer.last_error ? h("div", { class: "inline-warn", text: streamer.last_error }) : null,
        h("div", { class: "actions-row" },
          button(t("common.edit"), { variant: "ghost", onClick: () => streamerModal(streamer) }),
          button(t("twitch.testAnnouncement"), { variant: "secondary", onClick: () => testAnnouncement(streamer) }),
          button(t("common.delete"), { variant: "danger", onClick: () => deleteStreamer(streamer) }))));
    }
    streamerBody.append(grid);
  }

  async function testAnnouncement(streamer) {
    try {
      await api(`/api/twitch/streamers/${streamer.id}/test`, { method: "POST" });
      toast(t("twitch.testSent"), "success");
    } catch (error) {
      toast(errorMessage(error), "error");
    }
  }

  async function deleteStreamer(streamer) {
    if (!(await confirmDialog({ title: t("common.confirmDeleteTitle"), text: t("twitch.deleteStreamer"), danger: true }))) return;
    try {
      await api(`/api/twitch/streamers/${streamer.id}`, { method: "DELETE" });
      streamers = streamers.filter((item) => item.id !== streamer.id);
      renderStreamers();
      toast(t("twitch.streamerDeleted"), "success");
    } catch (error) { toast(errorMessage(error), "error"); }
  }

  function streamerModal(streamer = null) {
    const isEdit = Boolean(streamer);
    const login = input({ value: streamer?.login || "", placeholder: t("twitch.loginPlaceholder"), maxlength: 25, disabled: isEdit });
    const channel = select({
      options: textChannels,
      value: streamer?.channel_id || "",
      placeholder: t("common.selectChannel"),
    });
    const mention = select({
      options: [
        { value: "none", label: t("twitch.mentionNone") },
        { value: "everyone", label: t("twitch.mentionEveryone") },
        { value: "role", label: t("twitch.mentionRole") },
      ],
      value: streamer?.mention_type || "none",
    });
    const roleSelect = select({
      options: roles,
      value: streamer?.mention_role_id || "",
      placeholder: t("common.selectRole"),
    });
    const roleField = field(t("twitch.mentionRoleSelect"), roleSelect);
    const template = textarea({
      value: streamer?.template || "",
      rows: 5,
      maxlength: 4096,
      placeholder: data.default_template,
    });
    const count = h("span", { class: "muted small" });
    const updateCount = () => { count.textContent = t("twitch.templateCount", { n: template.value.length }); };
    template.addEventListener("input", updateCount);
    updateCount();
    const syncRole = () => { roleField.classList.toggle("hidden", mention.value !== "role"); };
    mention.addEventListener("change", syncRole);
    syncRole();
    const body = h("div", { class: "form-stack" },
      h("div", { class: "form-grid two" },
        field(t("twitch.login"), login),
        field(t("twitch.channel"), channel)),
      h("div", { class: "form-grid two" },
        field(t("twitch.mention"), mention),
        roleField),
      field(t("twitch.template"), template, t("twitch.templateHint")),
      h("div", { class: "align-end" }, count));
    const modal = openModal({
      title: isEdit ? t("twitch.editStreamer") : t("twitch.addStreamer"),
      body,
      wide: true,
      actions: [
        button(t("common.cancel"), { onClick: () => modal.close() }),
        button(t("twitch.saveStreamer"), {
          variant: "primary",
          onClick: async () => {
            if (!login.value.trim()) { toast(t("twitch.loginInvalid"), "error"); return; }
            if (!channel.value) { toast(t("twitch.channelRequired"), "error"); return; }
            if (mention.value === "role" && !roleSelect.value) { toast(t("twitch.roleRequired"), "error"); return; }
            const payload = {
              login: login.value.trim(),
              channel_id: channel.value,
              mention_type: mention.value,
              mention_role_id: mention.value === "role" ? roleSelect.value : "",
              template: template.value,
            };
            try {
              if (isEdit) {
                const response = await api(`/api/twitch/streamers/${streamer.id}`, { method: "PUT", body: payload });
                streamers = streamers.map((item) => (item.id === response.item.id ? response.item : item));
              } else {
                const response = await api("/api/twitch/streamers", { method: "POST", body: payload });
                streamers = [...streamers, response.item];
              }
              renderStreamers();
              toast(isEdit ? t("twitch.streamerUpdated") : t("twitch.streamerAdded"), "success");
              modal.close();
            } catch (error) { toast(errorMessage(error), "error"); }
          },
        }),
      ],
    });
  }

  page.append(card(t("twitch.streamersTitle"),
    h("p", { class: "muted", text: t("twitch.streamersHint") }),
    data.config.has_client_secret ? null : h("div", { class: "inline-warn", text: t("twitch.noCredentials") }),
    streamerBody,
    h("div", { class: "page-actions" },
      button(t("twitch.addStreamer"), {
        variant: "primary",
        icon: "plus",
        disabled: !data.config.has_client_secret,
        onClick: () => streamerModal(),
      }))));

  // -- preview ---------------------------------------------------------
  const previewLogin = input({ value: streamers[0]?.login || "streamer", maxlength: 25 });
  const previewTemplate = textarea({ value: data.default_template, rows: 6, maxlength: 4096 });
  const previewMention = select({
    options: [
      { value: "none", label: t("twitch.mentionNone") },
      { value: "everyone", label: t("twitch.mentionEveryone") },
      { value: "role", label: t("twitch.mentionRole") },
    ],
    value: "none",
  });
  const previewRole = select({ options: roles, placeholder: t("common.selectRole") });
  const previewRoleField = field(t("twitch.mentionRoleSelect"), previewRole);
  const previewBox = h("div", { class: "preview-box" });
  const previewButton = button(t("twitch.preview"), {
    variant: "secondary",
    onClick: async () => {
      previewButton.disabled = true;
      try {
        const response = await api("/api/twitch/preview", {
          method: "POST",
          body: {
            login: previewLogin.value.trim(),
            template: previewTemplate.value,
            mention_type: previewMention.value,
            mention_role_id: previewRole.value,
          },
        });
        previewBox.replaceChildren(embedPreview(response.embed, response.content, t("twitch.previewTestFooter")));
      } catch (error) {
        previewBox.replaceChildren(h("div", { class: "inline-error", text: `${t("twitch.previewError")} ${errorMessage(error)}` }));
      } finally {
        previewButton.disabled = false;
      }
    },
  });
  previewMention.addEventListener("change", () => previewRoleField.classList.toggle("hidden", previewMention.value !== "role"));
  previewRoleField.classList.add("hidden");
  page.append(card(t("twitch.previewTitle"),
    h("p", { class: "muted", text: t("twitch.previewHint") }),
    h("div", { class: "form-grid two" },
      field(t("twitch.login"), previewLogin),
      field(t("twitch.mention"), previewMention)),
    previewRoleField,
    field(t("twitch.template"), previewTemplate, t("twitch.templateHint")),
    h("div", { class: "page-actions" }, previewButton),
    previewBox));

  renderStreamers();
  document.getElementById("page").replaceChildren(page);
  await previewButton.click();
  return () => {};
}
