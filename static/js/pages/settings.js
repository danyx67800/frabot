import { api, downloadJson, errorMessage } from "../api.js";
import { t } from "../i18n.js";
import {
  badge, button, card, confirmDialog, copyText, field, h, input, openModal,
  pageHeader, toast,
} from "../ui.js";

async function pickJsonFile() {
  return new Promise((resolve) => {
    const fileInput = h("input", { type: "file", accept: "application/json,.json", hidden: true });
    fileInput.addEventListener("change", () => resolve(fileInput.files?.[0] || null));
    document.body.append(fileInput);
    fileInput.click();
    setTimeout(() => fileInput.remove(), 60000);
  });
}

export async function render(ctx) {
  const response = await api("/api/settings");
  let config = response.config;
  const page = h("div", {});
  page.append(pageHeader(t("settings.title"), t("settings.subtitle"), []));

  // -- Discord token ---------------------------------------------------
  const appId = input({ value: config.discord.application_id || "", placeholder: "Application ID" });
  const tokenInput = input({
    type: "password",
    placeholder: config.discord.has_bot_token ? t("settings.botTokenPlaceholder") : t("settings.botToken"),
    autocomplete: "new-password",
  });
  const inviteLink = h("a", {
    class: "text-link",
    href: response.invite_url || "#",
    target: "_blank",
    rel: "noreferrer noopener",
    text: t("settings.inviteLink"),
  });
  const updateToken = button(t("settings.updateToken"), {
    variant: "primary",
    onClick: async (event) => {
      if (!appId.value.trim() || !tokenInput.value.trim()) {
        toast(!appId.value.trim() ? t("settings.needAppId") : t("settings.needToken"), "error");
        return;
      }
      event.currentTarget.disabled = true;
      try {
        const result = await api("/api/settings/discord-token", {
          method: "PUT",
          body: { application_id: appId.value.trim(), bot_token: tokenInput.value.trim() },
        });
        config = result.config;
        tokenInput.value = "";
        toast(t("settings.tokenSaved"), "success");
        await ctx.refreshStatus();
      } catch (error) {
        toast(errorMessage(error), "error");
      } finally {
        event.currentTarget.disabled = false;
      }
    },
  });
  page.append(card(t("settings.botTitle"),
    h("p", { class: "muted", text: t("settings.botHint") }),
    h("div", { class: "token-status" },
      badge(config.discord.has_bot_token ? t("common.enabled") : t("settings.noToken"), config.discord.has_bot_token ? "ok" : "warn"),
      h("span", { class: "muted small", text: config.discord.bot_name || "—" }),
      h("span", { class: "muted small mono", text: config.discord.application_id || "" })),
    h("div", { class: "form-grid two" },
      field(t("settings.applicationId"), appId),
      field(t("settings.botToken"), tokenInput)),
    h("div", { class: "page-actions" },
      updateToken,
      inviteLink,
      button(t("common.copyLink"), { variant: "ghost", onClick: () => copyText(response.invite_url || "") }))));

  // -- appearance ------------------------------------------------------
  const colorInput = h("input", { type: "color", class: "input color-input", value: config.ui.embed_color || "#D2E85C" });
  const colorText = input({ value: config.ui.embed_color || "#D2E85C", maxlength: 7 });
  colorInput.addEventListener("input", () => { colorText.value = colorInput.value.toUpperCase(); });
  colorText.addEventListener("input", () => {
    if (/^#[0-9a-fA-F]{6}$/.test(colorText.value)) colorInput.value = colorText.value;
  });
  const saveColor = button(t("common.save"), {
    variant: "primary",
    onClick: async () => {
      if (!/^#[0-9a-fA-F]{6}$/.test(colorText.value)) { toast(t("settings.needColor"), "error"); return; }
      try {
        const result = await api("/api/settings/ui", { method: "PUT", body: { embed_color: colorText.value } });
        config = result.config;
        toast(t("settings.colorSaved"), "success");
      } catch (error) { toast(errorMessage(error), "error"); }
    },
  });
  page.append(card(t("settings.appearanceTitle"),
    h("p", { class: "muted", text: t("settings.appearanceHint") }),
    h("div", { class: "color-row" }, colorInput, colorText, saveColor)));

  // -- wizard ----------------------------------------------------------
  const restartWizard = button(t("settings.wizardRestart"), {
    variant: "secondary",
    onClick: async () => {
      if (!(await confirmDialog({ title: t("settings.wizardTitle"), text: t("settings.wizardRestartText"), confirmLabel: t("settings.wizardRestart") }))) return;
      try {
        await api("/api/wizard/restart", { method: "POST" });
        ctx.showWizard();
      } catch (error) { toast(errorMessage(error), "error"); }
    },
  });
  const syncButton = button(t("settings.syncCommands"), {
    variant: "ghost",
    onClick: async () => {
      try {
        const result = await api("/api/wizard/sync-commands", { method: "POST" });
        toast(t("settings.syncDone", { count: result.count ?? 0 }), "success");
      } catch (error) { toast(errorMessage(error), "error"); }
    },
  });
  page.append(card(t("settings.wizardTitle"),
    h("p", { class: "muted", text: t("settings.wizardHint") }),
    h("div", { class: "page-actions" }, restartWizard, syncButton),
    h("p", { class: "field-hint", text: t("settings.syncHint") })));

  // -- backup ----------------------------------------------------------
  const importInput = h("input", { type: "file", accept: "application/json,.json", hidden: true });
  importInput.addEventListener("change", async () => {
    const file = importInput.files?.[0];
    if (!file) return;
    try {
      const parsed = JSON.parse(await file.text());
      if (!(await confirmDialog({ title: t("settings.importConfig"), text: t("settings.importConfirm"), danger: true, confirmLabel: t("common.import") }))) return;
      const result = await api("/api/settings/import", { method: "POST", body: parsed });
      toast(t("settings.importSuccess", {
        categories: result.categories,
        questions: result.questions,
        streamers: result.streamers,
      }), "success");
      await ctx.reload();
    } catch (error) {
      toast(`${t("settings.importError")}: ${errorMessage(error)}`, "error");
    } finally {
      importInput.value = "";
    }
  });
  page.append(card(t("settings.backupTitle"),
    h("p", { class: "muted", text: t("settings.backupHint") }),
    h("div", { class: "page-actions" },
      button(t("settings.exportConfig"), {
        variant: "secondary",
        onClick: () => downloadJson("/api/settings/export").catch((error) => toast(errorMessage(error), "error")),
      }),
      button(t("settings.importConfig"), { variant: "secondary", onClick: () => importInput.click() }),
      importInput),
    h("p", { class: "field-hint", text: t("settings.importWarning") })));

  // -- reset -----------------------------------------------------------
  const resetButton = button(t("settings.resetConfig"), {
    variant: "danger",
    onClick: () => {
      const confirmInput = input({ placeholder: t("settings.resetPlaceholder") });
      const modal = openModal({
        title: t("settings.resetConfirmTitle"),
        body: h("div", { class: "form-stack" },
          h("p", { class: "modal-text", text: t("settings.resetConfirmText") }),
          field(t("settings.resetPlaceholder"), confirmInput)),
        actions: [
          button(t("common.cancel"), { onClick: () => modal.close() }),
          button(t("settings.resetConfig"), {
            variant: "danger",
            onClick: async () => {
              if (confirmInput.value !== "RESET") { toast(t("settings.resetWrong"), "error"); return; }
              try {
                await api("/api/settings/reset", { method: "POST", body: { confirm: "RESET" } });
                toast(t("settings.resetDone"), "success");
                modal.close();
                await ctx.refreshStatus();
                ctx.showWizard();
              } catch (error) { toast(errorMessage(error), "error"); }
            },
          }),
        ],
      });
    },
  });
  page.append(card(t("settings.resetTitle"),
    h("p", { class: "muted", text: t("settings.resetHint") }),
    h("div", { class: "page-actions" }, resetButton),
    h("p", { class: "security-note", text: t("settings.securityHint") })));

  document.getElementById("page").replaceChildren(page);
  return () => {};
}
