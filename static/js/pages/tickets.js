import { api, errorMessage } from "../api.js";
import { guildData } from "../data.js";
import { t } from "../i18n.js";
import {
  badge, button, card, channelOptions, clear, confirmDialog, emptyState, field, fmtDate,
  fmtDuration, h, input, openModal, pageHeader, roleOptions, select, spinner,
  textarea, toast,
} from "../ui.js";

export async function render(ctx) {
  const [settingsResponse, categoriesResponse, statsResponse, panelResponse, guild] = await Promise.all([
    api("/api/settings"),
    api("/api/tickets/categories"),
    api("/api/tickets/stats"),
    api("/api/tickets/panel"),
    guildData().catch(() => null),
  ]);
  let settings = settingsResponse.config;
  let categories = categoriesResponse.items;
  let stats = statsResponse;
  let panel = panelResponse;
  let needsRepublish = false;

  const textChannels = channelOptions(guild?.channels || [], ["text"]);
  const categoryChannels = channelOptions(guild?.channels || [], ["category"]);
  const roles = roleOptions(guild?.roles || []);

  const page = h("div", {});
  page.append(pageHeader(t("tickets.title"), t("tickets.subtitle"), [
    button(t("common.refresh"), { variant: "ghost", onClick: () => ctx.reload() }),
  ]));

  // -- stats -----------------------------------------------------------
  const statsGrid = h("div", { class: "stats-grid" });
  const byCategoryBox = h("div", { class: "category-breakdown" });
  function renderStats() {
    clear(statsGrid);
    const cards = [
      [t("tickets.statTotal"), stats.total],
      [t("tickets.statOpen"), stats.open],
      [t("tickets.statClosed"), stats.closed],
      [t("tickets.statToday"), stats.closed_today],
      [t("tickets.statAvg"), stats.avg_close_seconds === null ? "—" : fmtDuration(stats.avg_close_seconds)],
      [t("tickets.statTranscripts"), stats.with_transcript],
    ];
    for (const [label, value] of cards) {
      statsGrid.append(h("div", { class: "stat-card compact" },
        h("div", { class: "stat-label", text: label }),
        h("div", { class: "stat-strong", text: String(value) })));
    }
    clear(byCategoryBox);
    if (stats.by_category?.length) {
      byCategoryBox.append(h("span", { class: "muted small", text: `${t("tickets.byCategory")}: ` }));
      for (const row of stats.by_category) {
        byCategoryBox.append(h("span", { class: "chip", text: `${row.category_name} · ${row.open || 0}/${row.total}` }));
      }
    }
  }

  // -- config ----------------------------------------------------------
  const panelSelect = select({ options: textChannels, value: settings.tickets.panel_channel_id, placeholder: t("common.selectChannel") });
  const logSelect = select({ options: textChannels, value: settings.tickets.log_channel_id, placeholder: t("common.none") });
  const maxOpen = input({ type: "number", min: 1, max: 10, value: settings.tickets.max_open_per_user });
  const autoClose = input({ type: "number", min: 0, max: 720, value: settings.tickets.auto_close_hours });
  const askReason = h("input", { type: "checkbox" });
  askReason.checked = settings.tickets.ask_reason;
  const panelStatus = h("div", { class: "panel-status" });
  const republishHint = h("div", { class: "inline-warn hidden", text: t("tickets.republishNeeded") });

  function renderPanelStatus() {
    clear(panelStatus);
    panelStatus.append(
      badge(panel.published ? t("common.published") : t("common.notPublished"), panel.published ? "ok" : "warn"),
      panel.url ? h("a", { class: "text-link", href: panel.url, target: "_blank", rel: "noreferrer noopener", text: t("tickets.panelUrl") }) : null,
    );
    republishHint.classList.toggle("hidden", !needsRepublish);
  }

  async function saveConfig(silent = false) {
    if (!panelSelect.value) {
      toast(t("wizard.step5Required"), "error");
      return false;
    }
    try {
      const response = await api("/api/settings/tickets", {
        method: "PUT",
        body: {
          panel_channel_id: panelSelect.value,
          log_channel_id: logSelect.value,
          max_open_per_user: Number(maxOpen.value),
          auto_close_hours: Number(autoClose.value),
          ask_reason: askReason.checked,
        },
      });
      settings = response.config;
      if (!silent) toast(t("common.saved"), "success");
      if (panel.channel_id !== panelSelect.value) {
        panel = await api("/api/tickets/panel");
        renderPanelStatus();
      }
      return true;
    } catch (error) {
      toast(errorMessage(error), "error");
      return false;
    }
  }

  const saveConfigButton = button(t("common.save"), { variant: "primary", onClick: () => saveConfig() });
  const publishButton = button(t("tickets.publish"), {
    variant: "secondary",
    onClick: async (event) => {
      // `currentTarget` is only valid during the synchronous part of the
      // event. Capture it before awaiting, otherwise it becomes null and the
      // request below never starts.
      const trigger = event.currentTarget;
      if (!categories.length) {
        toast(t("tickets.publishNoCategories"), "error");
        return;
      }
      trigger.disabled = true;
      try {
        if (!(await saveConfig(true))) return;
        await api("/api/tickets/publish", { method: "POST" });
        panel = await api("/api/tickets/panel");
        needsRepublish = false;
        renderPanelStatus();
        toast(t("tickets.publishSuccess"), "success");
      } catch (error) {
        toast(errorMessage(error), "error");
      } finally {
        trigger.disabled = false;
      }
    },
  });

  page.append(h("div", { class: "stats-grid-wrap" }, statsGrid, byCategoryBox));
  page.append(card(t("tickets.configTitle"),
    h("p", { class: "muted", text: t("tickets.configHint") }),
    h("div", { class: "form-grid three" },
      field(t("tickets.panelChannel"), panelSelect),
      field(t("tickets.logChannel"), logSelect),
      field(t("tickets.maxOpen"), maxOpen)),
    h("div", { class: "form-grid two" },
      field(t("tickets.autoClose"), autoClose, t("tickets.autoCloseHint")),
      h("label", { class: "checkbox align-end" }, askReason, h("span", { text: t("tickets.askReason") }))),
    h("div", { class: "panel-publish" },
      h("div", {}, h("strong", { text: t("tickets.publishHint") }), panelStatus),
      h("div", { class: "page-actions" }, saveConfigButton, publishButton)),
    republishHint));

  // -- categories ------------------------------------------------------
  const categoryBody = h("div", {});
  function renderCategories() {
    clear(categoryBody);
    if (!categories.length) {
      categoryBody.append(emptyState(t("tickets.noCategories")));
      return;
    }
    categoryBody.append(h("div", { class: "category-grid" }, ...categories.map((category) => {
      const destination = categoryChannels.find((item) => item.value === category.discord_category_id)?.label.replace("▸ ", "");
      const staff = (category.staff_role_ids || []).map((id) => roles.find((role) => role.value === id)?.label || t("common.roleFallback", { id }));
      return h("div", { class: "category-card" },
        h("div", { class: "category-head" },
          h("span", { class: "category-emoji", text: category.emoji || "🎫" }),
          h("div", { class: "category-copy" }, h("strong", { text: category.name }), h("small", { text: category.description || "—" })),
          h("div", { class: "actions-cell" },
            button("", { variant: "ghost", icon: "edit", title: t("common.edit"), onClick: () => categoryModal(category) }),
            button("", { variant: "ghost", icon: "trash", title: t("common.delete"), onClick: () => deleteCategory(category) }))),
        h("div", { class: "category-meta" },
          h("div", {}, h("span", { class: "meta-label", text: t("tickets.categoryDiscord") }), h("span", { text: category.discord_category_id ? (destination || t("common.idFallback", { id: category.discord_category_id })) : t("common.none") })),
          h("div", {}, h("span", { class: "meta-label", text: t("tickets.staffRoles") }), h("span", { text: staff.length ? staff.join(", ") : t("common.none") }))),
      );
    })));
  }

  async function reloadCategories() {
    const response = await api("/api/tickets/categories");
    categories = response.items;
    renderCategories();
    rebuildCategoryFilter();
    needsRepublish = true;
    renderPanelStatus();
    refreshPanel();
  }

  async function refreshPanel() {
    try {
      panel = await api("/api/tickets/panel");
      renderPanelStatus();
    } catch { /* keep previous state */ }
  }

  async function deleteCategory(category) {
    if (!(await confirmDialog({ title: t("common.confirmDeleteTitle"), text: t("tickets.deleteCategory"), danger: true }))) return;
    try {
      await api(`/api/tickets/categories/${category.id}`, { method: "DELETE" });
      toast(t("tickets.categoryDeleted"), "success");
      await reloadCategories();
    } catch (error) { toast(errorMessage(error), "error"); }
  }

  function categoryModal(category = null) {
    const name = input({ value: category?.name || "", maxlength: 80 });
    const emoji = input({ value: category?.emoji || "🎫", maxlength: 32 });
    const description = textarea({ value: category?.description || "", rows: 2, maxlength: 500 });
    const discordCategory = select({
      options: categoryChannels,
      value: category?.discord_category_id || "",
      placeholder: t("common.none"),
    });
    const staffSelect = select({
      options: roles,
      value: category?.staff_role_ids || [],
      multiple: true,
      size: 6,
    });
    const welcome = textarea({
      value: category?.welcome_message || "",
      rows: 4,
      maxlength: 2000,
      placeholder: t("tickets.welcomePlaceholder"),
    });
    const body = h("div", { class: "form-stack" },
      h("div", { class: "form-grid emoji-grid" },
        field(t("tickets.categoryEmoji"), emoji),
        field(t("tickets.categoryName"), name)),
      field(t("tickets.categoryDescription"), description),
      field(t("tickets.categoryDiscord"), discordCategory, t("tickets.categoryDiscordHint")),
      field(t("tickets.staffRoles"), staffSelect, t("tickets.staffRolesHint")),
      field(t("tickets.welcomeMessage"), welcome, t("tickets.welcomeHint")));
    const modal = openModal({
      title: category ? t("tickets.editCategory") : t("tickets.addCategory"),
      body,
      wide: true,
      actions: [
        button(t("common.cancel"), { onClick: () => modal.close() }),
        button(t("common.save"), {
          variant: "primary",
          onClick: async () => {
            if (!name.value.trim()) { toast(t("tickets.nameRequired"), "error"); return; }
            const payload = {
              name: name.value.trim(),
              emoji: emoji.value.trim() || "🎫",
              description: description.value.trim(),
              discord_category_id: discordCategory.value,
              staff_role_ids: Array.from(staffSelect.selectedOptions).map((option) => option.value),
              welcome_message: welcome.value,
            };
            try {
              if (category) await api(`/api/tickets/categories/${category.id}`, { method: "PUT", body: payload });
              else await api("/api/tickets/categories", { method: "POST", body: payload });
              toast(category ? t("tickets.categoryUpdated") : t("tickets.categoryCreated"), "success");
              modal.close();
              await reloadCategories();
            } catch (error) { toast(errorMessage(error), "error"); }
          },
        }),
      ],
    });
  }

  page.append(card(t("tickets.categoriesTitle"),
    h("p", { class: "muted", text: t("tickets.categoriesHint") }),
    categoryBody,
    h("div", { class: "page-actions" }, button(t("tickets.addCategory"), { variant: "primary", icon: "plus", onClick: () => categoryModal() }))));

  // -- ticket list -----------------------------------------------------
  const statusFilter = select({
    options: [
      { value: "all", label: t("tickets.statusAll") },
      { value: "open", label: t("tickets.statusOpen") },
      { value: "closed", label: t("tickets.statusClosed") },
    ],
    value: "all",
    onChange: () => loadTickets(),
  });
  const categoryFilter = select({ options: [], value: "", placeholder: t("common.all"), onChange: () => loadTickets() });
  const searchInput = input({ placeholder: t("tickets.searchPlaceholder") });
  searchInput.addEventListener("keydown", (event) => { if (event.key === "Enter") loadTickets(); });
  const ticketTotal = h("span", { class: "muted small" });
  const ticketTbody = h("tbody", {});
  const listCard = h("section", { class: "card" },
    h("div", { class: "card-head" }, h("h2", { text: t("tickets.ticketsTitle") }), ticketTotal),
    h("div", { class: "card-body" },
      h("p", { class: "muted", text: t("tickets.ticketsHint") }),
      h("div", { class: "filters" },
        field(t("tickets.filterStatus"), statusFilter, "", "inline"),
        field(t("tickets.filterCategory"), categoryFilter, "", "inline"),
        field(t("common.search"), searchInput, "", "inline grow"),
        button(t("common.filter"), { variant: "secondary", onClick: () => loadTickets() })),
      h("div", { class: "table-wrap" },
        h("table", { class: "table" },
          h("thead", {}, h("tr", {},
            h("th", { text: t("tickets.number") }),
            h("th", { text: t("tickets.user") }),
            h("th", { text: t("common.category") }),
            h("th", { text: t("common.status") }),
            h("th", { text: t("tickets.created") }),
            h("th", { text: t("tickets.claimed") }),
            h("th", { text: t("common.actions") }))),
          ticketTbody))));
  page.append(listCard);

  function rebuildCategoryFilter() {
    const current = categoryFilter.value;
    categoryFilter.replaceChildren(h("option", { value: "", text: t("common.all") }));
    for (const category of categories) {
      categoryFilter.append(h("option", { value: category.id, text: category.name }));
    }
    categoryFilter.value = categories.some((category) => String(category.id) === current) ? current : "";
  }

  async function loadTickets() {
    clear(ticketTbody);
    ticketTbody.append(h("tr", {}, h("td", { colspan: 7 }, spinner(t("common.loading")))));
    try {
      const params = new URLSearchParams({ status: statusFilter.value, limit: "50" });
      if (categoryFilter.value) params.set("category_id", categoryFilter.value);
      if (searchInput.value.trim()) params.set("q", searchInput.value.trim());
      const response = await api(`/api/tickets?${params}`);
      ticketTotal.textContent = `${response.items.length} / ${response.total}`;
      clear(ticketTbody);
      if (!response.items.length) {
        ticketTbody.append(h("tr", {}, h("td", { colspan: 7 }, emptyState(t("tickets.noTickets")))));
        return;
      }
      for (const ticket of response.items) {
        ticketTbody.append(h("tr", {},
          h("td", { class: "mono" }, h("strong", { text: `#${ticket.number}` })),
          h("td", { text: ticket.user_name }),
          h("td", { text: ticket.category_name }),
          h("td", {}, badge(ticket.status === "open" ? t("tickets.statusOpen") : t("tickets.statusClosed"), ticket.status === "open" ? "ok" : "neutral")),
          h("td", { class: "small muted", text: fmtDate(ticket.created_at) }),
          h("td", { class: "small muted", text: ticket.claimed_by ? t("tickets.claimedBy", { user: ticket.claimed_by_name || t("common.userFallback", { id: ticket.claimed_by }) }) : t("tickets.unassigned") }),
          h("td", { class: "actions-cell" },
            button(t("tickets.view"), { variant: "ghost", onClick: () => openTicket(ticket) }))));
      }
    } catch (error) {
      clear(ticketTbody);
      ticketTbody.append(h("tr", {}, h("td", { colspan: 7, text: errorMessage(error) })));
    }
  }

  async function refreshStats() {
    try {
      stats = await api("/api/tickets/stats");
      renderStats();
    } catch { /* keep old stats */ }
  }

  function forceCloseModal(ticket) {
    const reason = textarea({ rows: 3, maxlength: 400, placeholder: t("tickets.forceCloseReasonPlaceholder") });
    const modal = openModal({
      title: t("tickets.forceCloseTitle"),
      body: h("div", { class: "form-stack" },
        h("p", { class: "modal-text", text: t("tickets.forceCloseText") }),
        field(t("tickets.forceCloseReason"), reason)),
      actions: [
        button(t("common.cancel"), { onClick: () => modal.close() }),
        button(t("tickets.forceCloseConfirm"), {
          variant: "danger",
          onClick: async () => {
            try {
              await api(`/api/tickets/${ticket.id}/close`, { method: "POST", body: { reason: reason.value } });
              toast(t("tickets.closeSuccess"), "success");
              modal.close();
              await Promise.all([loadTickets(), refreshStats()]);
            } catch (error) { toast(errorMessage(error), "error"); }
          },
        }),
      ],
    });
  }

  async function openTicket(ticket) {
    const info = h("div", { class: "summary" },
      h("div", { class: "summary-row" }, h("span", { text: t("tickets.number") }), h("strong", { text: `#${ticket.number}` })),
      h("div", { class: "summary-row" }, h("span", { text: t("tickets.user") }), h("strong", { text: ticket.user_name })),
      h("div", { class: "summary-row" }, h("span", { text: t("common.category") }), h("strong", { text: ticket.category_name })),
      h("div", { class: "summary-row" }, h("span", { text: t("common.status") }), h("strong", { text: ticket.status === "open" ? t("tickets.statusOpen") : t("tickets.statusClosed") })),
      h("div", { class: "summary-row" }, h("span", { text: t("tickets.created") }), h("strong", { text: fmtDate(ticket.created_at) })),
      ticket.closed_at ? h("div", { class: "summary-row" }, h("span", { text: t("tickets.closedAt") }), h("strong", { text: fmtDate(ticket.closed_at) })) : null,
      ticket.closed_by ? h("div", { class: "summary-row" }, h("span", { text: t("tickets.closedBy") }), h("strong", { text: ticket.closed_by })) : null,
      ticket.close_reason ? h("div", { class: "summary-row" }, h("span", { text: t("tickets.closeReason") }), h("strong", { text: ticket.close_reason })) : null,
      ticket.reason ? h("div", { class: "summary-row" }, h("span", { text: t("tickets.reason") }), h("strong", { text: ticket.reason })) : null,
      ticket.claimed_by ? h("div", { class: "summary-row" }, h("span", { text: t("tickets.claimed") }), h("strong", { text: ticket.claimed_by_name || t("common.userFallback", { id: ticket.claimed_by }) })) : null);
    const transcriptBox = h("div", { class: "transcript-box" }, spinner(t("common.loading")));
    const actions = [];
    if (ticket.channel_url) actions.push(h("a", { class: "btn secondary", href: ticket.channel_url, target: "_blank", rel: "noreferrer noopener", text: t("tickets.openTicket") }));
    if (ticket.status === "open") actions.push(button(t("tickets.forceClose"), { variant: "danger", onClick: () => forceCloseModal(ticket) }));
    actions.push(button(t("common.close"), { onClick: () => modal.close() }));
    const modal = openModal({
      title: t("tickets.detailTitle", { number: ticket.number }),
      body: h("div", { class: "form-stack" }, info, h("h3", { class: "subhead", text: t("tickets.transcript") }), transcriptBox),
      actions,
      wide: true,
    });
    if (!ticket.transcript_available) {
      transcriptBox.replaceChildren(emptyState(t("tickets.noTranscript")));
      return;
    }
    try {
      const response = await api(`/api/tickets/${ticket.id}/transcript`);
      const frame = h("iframe", { class: "transcript-frame", title: t("tickets.transcript"), sandbox: "" });
      frame.srcdoc = response.html;
      transcriptBox.replaceChildren(frame);
    } catch (error) {
      transcriptBox.replaceChildren(h("div", { class: "inline-error", text: `${t("tickets.transcriptLoadError")} ${errorMessage(error)}` }));
    }
  }

  // initial rendering
  renderStats();
  renderCategories();
  rebuildCategoryFilter();
  renderPanelStatus();
  document.getElementById("page").replaceChildren(page);
  await loadTickets();
  return () => {};
}
