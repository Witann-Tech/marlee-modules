/** @odoo-module **/

function renderSubscriptionCard({
    item,
    canOperateSubscription,
    stateClass,
    participantNames,
    accessSummary,
    accessSiteLabel,
    pendingDocumentHtml,
    inlineFormsHtml,
    escapeHtml,
    formatDateDisplay,
    formatMoney,
    _t,
}) {
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
                <div><span>${escapeHtml(_t("Proxima fecha"))}</span><strong>${escapeHtml(formatDateDisplay(item.next_invoice_date) || "-")}</strong></div>
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
                    data-action="open-renewal"
                    data-subscription-id="${escapeHtml(String(item.subscription_id || 0))}"
                    ${canOperateSubscription ? "" : "disabled"}
                >${escapeHtml(_t("Renovar"))}</button>
                <button
                    type="button"
                    class="wgs-action-btn"
                    data-action="open-upsale"
                    data-subscription-id="${escapeHtml(String(item.subscription_id || 0))}"
                    ${canOperateSubscription ? "" : "disabled"}
                >${escapeHtml(_t("Upsale"))}</button>
                <button
                    type="button"
                    class="wgs-action-btn"
                    data-action="open-pending"
                    data-subscription-id="${escapeHtml(String(item.subscription_id || 0))}"
                    ${item.has_pending_document ? "" : "disabled"}
                >${escapeHtml(_t("Cobrar pendiente"))}</button>
                <button
                    type="button"
                    class="wgs-action-btn"
                    data-action="open-participants"
                    data-subscription-id="${escapeHtml(String(item.subscription_id || 0))}"
                >${escapeHtml(_t("Editar participantes"))}</button>
                <button
                    type="button"
                    class="wgs-action-btn"
                    data-action="resync-access"
                    data-subscription-id="${escapeHtml(String(item.subscription_id || 0))}"
                >${escapeHtml(_t("Resincronizar acceso"))}</button>
                <button
                    type="button"
                    class="wgs-action-btn"
                    data-action="open-cancellation-refund"
                    data-subscription-id="${escapeHtml(String(item.subscription_id || 0))}"
                >${escapeHtml(_t("Cancelar suscripción"))}</button>
            </div>
            ${pendingDocumentHtml || ""}
            ${inlineFormsHtml || ""}
        </div>
    `;
}

function renderPendingDocumentSummary({
    item,
    escapeHtml,
    formatMoney,
    _t,
}) {
    if (!item || !item.has_pending_document) {
        return "";
    }
    return `
        <div class="wgs-subscription-participants">
            <span>${escapeHtml(_t("Documento pendiente"))}</span>
            <p>${escapeHtml(item.pending_document_name || "-")} · ${escapeHtml(formatMoney(item.pending_amount_total || 0))}</p>
        </div>
    `;
}

export {
    renderPendingDocumentSummary,
    renderSubscriptionCard,
};
