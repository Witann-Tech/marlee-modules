/** @odoo-module **/

function renderRenewalForm({
    item,
    formMode,
    renewalForm,
    formError,
    formNotice,
    escapeHtml,
    formatDateDisplay,
    formatMoney,
    getChargeDisplayAmount,
    _t,
}) {
    if (
        formMode !== "renewal"
        || !renewalForm
        || Number(renewalForm.subscriptionId || 0) !== Number(item.subscription_id || 0)
    ) {
        return "";
    }
    return `
        <div class="wgs-inline-form-card">
            <div class="wgs-inline-form-header">
                <strong>${escapeHtml(_t("Renovar suscripción"))}</strong>
                <button type="button" class="wgs-inline-close-btn" data-action="cancel-renewal">${escapeHtml(_t("Cancelar"))}</button>
            </div>
            ${formError ? `<div class="wgs-inline-error">${escapeHtml(formError)}</div>` : ""}
            ${formNotice ? `<div class="wgs-inline-notice">${escapeHtml(formNotice)}</div>` : ""}
            ${renewalForm.loading ? `<div class="wgs-inline-loading">${escapeHtml(_t("Calculando importe de renovación..."))}</div>` : ""}
            <div class="wgs-inline-form-meta">
                <div><span>${escapeHtml(_t("Suscripción"))}</span><strong>${escapeHtml(renewalForm.subscriptionName || "-")}</strong></div>
                <div><span>${escapeHtml(_t("Titular"))}</span><strong>${escapeHtml(renewalForm.holderPartnerName || "-")}</strong></div>
                <div><span>${escapeHtml(_t("Producto"))}</span><strong>${escapeHtml(renewalForm.productName || "-")}</strong></div>
                <div><span>${escapeHtml(_t("Próxima fecha"))}</span><strong>${escapeHtml(formatDateDisplay(renewalForm.nextInvoiceDate) || "-")}</strong></div>
                <div><span>${escapeHtml(_t("Importe a cobrar"))}</span><strong>${escapeHtml(formatMoney(getChargeDisplayAmount(renewalForm.charge)))}</strong></div>
            </div>
            <div class="wgs-inline-actions">
                <button type="button" class="wgs-primary-action-btn" data-action="save-renewal" ${renewalForm.loading ? "disabled" : ""}>${escapeHtml(_t("Agregar al ticket"))}</button>
                <button type="button" class="wgs-secondary-action-btn" data-action="cancel-renewal">${escapeHtml(_t("Cancelar"))}</button>
            </div>
        </div>
    `;
}

export { renderRenewalForm };
