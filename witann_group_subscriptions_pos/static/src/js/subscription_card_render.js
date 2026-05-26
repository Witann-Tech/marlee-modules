/** @odoo-module **/

function renderSubscriptionCard({
    item,
    stateClass,
    participantNames,
    accessSummary,
    accessSiteLabel,
    inlineFormsHtml,
    resyncAccessState = {},
    escapeHtml,
    formatDateDisplay,
    formatMoney,
    _t,
}) {
    const canEditParticipants = Number(item.max_participants_total || 1) > 1;
    const resyncRemaining = Math.max(0, Number(resyncAccessState.remainingSeconds || 0));
    const resyncLoading = Boolean(resyncAccessState.loading);
    const resyncDisabled = resyncLoading || resyncRemaining > 0;
    const resyncLabel = resyncLoading
        ? _t("Sincronizando...")
        : resyncRemaining > 0
        ? _t("Espera %ss").replace("%s", String(resyncRemaining))
        : _t("Resincronizar acceso");
    const resyncClass = resyncLoading ? " wgs-action-loading" : "";
    const participantActionHtml = canEditParticipants ? `
                <button
                    type="button"
                    class="wgs-action-btn"
                    data-action="open-participants"
                    data-subscription-id="${escapeHtml(String(item.subscription_id || 0))}"
                >${escapeHtml(_t("Editar participantes"))}</button>
    ` : "";
    return `
        <div class="wgs-subscription-card">
            <div class="wgs-subscription-card-header">
                <div>
                    <strong>${escapeHtml(item.subscription_name || "-")}</strong>
                    <div class="wgs-subscription-card-meta">${escapeHtml(item.partner_role_label || "-")}</div>
                </div>
                <span class="wgs-state-badge ${stateClass}">${escapeHtml(item.native_state_label || _t("Sin estado"))}</span>
            </div>
            <div class="wgs-subscription-grid">
                <div><span>${escapeHtml(_t("Paquete"))}</span><strong>${escapeHtml((item.package_names || []).join(", ") || "-")}</strong></div>
                <div><span>${escapeHtml(_t("Plan"))}</span><strong>${escapeHtml(item.plan_name || "-")}</strong></div>
                <div><span>${escapeHtml(_t("Inicio"))}</span><strong>${escapeHtml(formatDateDisplay(item.start_date) || "-")}</strong></div>
                <div><span>${escapeHtml(_t("Vencimiento"))}</span><strong>${escapeHtml(formatDateDisplay(item.valid_until) || "-")}</strong></div>
                <div><span>${escapeHtml(_t("Participantes"))}</span><strong>${escapeHtml(String(item.participant_count || 0))}</strong></div>
            </div>
            <div class="wgs-subscription-participants">
                <span>${escapeHtml(_t("Listado de participantes"))}</span>
                <p>${participantNames}</p>
            </div>
            <div class="wgs-subscription-participants">
                <span>${escapeHtml(_t("Control de acceso"))}</span>
                <p>${escapeHtml(_t("Personas"))}: ${escapeHtml(String(accessSummary.person_count || 0))} · ${escapeHtml(_t("Activas"))}: ${escapeHtml(String(accessSummary.active_count || 0))} · ${escapeHtml(_t("Sin person"))}: ${escapeHtml(String(accessSummary.missing_count || 0))}</p>
                <p>${escapeHtml(_t("Sitios"))}: ${accessSiteLabel}</p>
            </div>
            <div class="wgs-subscription-actions">
                <button
                    type="button"
                    class="wgs-action-btn"
                    data-action="${escapeHtml(item.can_reenroll ? "open-reenroll" : "open-renewal")}"
                    data-subscription-id="${escapeHtml(String(item.subscription_id || 0))}"
                    ${(item.can_renew || item.can_reenroll) ? "" : "disabled"}
                >${escapeHtml(item.can_reenroll ? _t("Reinscribir") : _t("Renovar"))}</button>
                <button
                    type="button"
                    class="wgs-action-btn"
                    data-action="open-upsale"
                    data-subscription-id="${escapeHtml(String(item.subscription_id || 0))}"
                    ${item.can_renew ? "" : "disabled"}
                >${escapeHtml(_t("Cambiar Plan"))}</button>
                ${participantActionHtml}
                <button
                    type="button"
                    class="wgs-action-btn${resyncClass}"
                    data-action="resync-access"
                    data-subscription-id="${escapeHtml(String(item.subscription_id || 0))}"
                    ${resyncDisabled ? "disabled" : ""}
                >${escapeHtml(resyncLabel)}</button>
            </div>
            ${inlineFormsHtml || ""}
        </div>
    `;
}

export {
    renderSubscriptionCard,
};
