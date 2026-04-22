/** @odoo-module **/

import { buildChargeFromSnapshot } from "./subscription_pricing_snapshot";

function renderPendingChargeForm({
    item,
    formMode,
    pendingChargeForm,
    formError,
    formNotice,
    escapeHtml,
    formatDateDisplay,
    formatMoney,
    getChargeDisplayAmount,
    _t,
}) {
    if (
        formMode !== "pending"
        || !pendingChargeForm
        || Number(pendingChargeForm.subscriptionId || 0) !== Number(item.subscription_id || 0)
    ) {
        return "";
    }
    const totalCharge = buildChargeFromSnapshot(pendingChargeForm, "amount_total");
    const pendingCharge = buildChargeFromSnapshot(pendingChargeForm, "charge_now");
    return `
        <div class="wgs-inline-form-card">
            <div class="wgs-inline-form-header">
                <strong>${escapeHtml(_t("Cobrar pendiente"))}</strong>
                <button type="button" class="wgs-inline-close-btn" data-action="cancel-pending">${escapeHtml(_t("Cancelar"))}</button>
            </div>
            ${formError ? `<div class="wgs-inline-error">${escapeHtml(formError)}</div>` : ""}
            ${formNotice ? `<div class="wgs-inline-notice">${escapeHtml(formNotice)}</div>` : ""}
            ${pendingChargeForm.loading ? `<div class="wgs-inline-loading">${escapeHtml(_t("Consultando factura pendiente..."))}</div>` : ""}
            <div class="wgs-inline-form-meta">
                <div><span>${escapeHtml(_t("Suscripción"))}</span><strong>${escapeHtml(pendingChargeForm.subscriptionName || "-")}</strong></div>
                <div><span>${escapeHtml(_t("Titular"))}</span><strong>${escapeHtml(pendingChargeForm.holderPartnerName || "-")}</strong></div>
                <div><span>${escapeHtml(_t("Documento"))}</span><strong>${escapeHtml(pendingChargeForm.pendingMoveName || "-")}</strong></div>
                <div><span>${escapeHtml(_t("Fecha factura"))}</span><strong>${escapeHtml(formatDateDisplay(pendingChargeForm.invoiceDate) || "-")}</strong></div>
                <div><span>${escapeHtml(_t("Vencimiento"))}</span><strong>${escapeHtml(formatDateDisplay(pendingChargeForm.invoiceDateDue) || "-")}</strong></div>
                <div><span>${escapeHtml(_t("Total documento"))}</span><strong>${escapeHtml(formatMoney(getChargeDisplayAmount(totalCharge)))}</strong></div>
                <div><span>${escapeHtml(_t("Saldo pendiente"))}</span><strong>${escapeHtml(formatMoney(getChargeDisplayAmount(pendingCharge)))}</strong></div>
            </div>
            <div class="wgs-inline-actions">
                <button type="button" class="wgs-primary-action-btn" data-action="save-pending" ${pendingChargeForm.loading ? "disabled" : ""}>${escapeHtml(_t("Agregar al ticket"))}</button>
                <button type="button" class="wgs-secondary-action-btn" data-action="cancel-pending">${escapeHtml(_t("Cancelar"))}</button>
            </div>
        </div>
    `;
}

export { renderPendingChargeForm };
