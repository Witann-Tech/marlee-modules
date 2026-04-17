/** @odoo-module **/

import {
    getDiscountedDisplayAmount,
    renderDiscountAuthorizationSection,
} from "./subscription_discount_render";

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
        !["renewal", "reenroll"].includes(formMode)
        || !renewalForm
        || Number(renewalForm.subscriptionId || 0) !== Number(item.subscription_id || 0)
    ) {
        return "";
    }
    const title = renewalForm.title || (formMode === "reenroll" ? _t("Reinscribir suscripción") : _t("Renovar suscripción"));
    const submitLabel = renewalForm.submitLabel || (formMode === "reenroll" ? _t("Agregar reinscripción al ticket") : _t("Agregar al ticket"));
    const cancelAction = formMode === "reenroll" ? "cancel-reenroll" : "cancel-renewal";
    const saveAction = formMode === "reenroll" ? "save-reenroll" : "save-renewal";
    const dateLabel = formMode === "reenroll" ? _t("Nueva vigencia desde") : _t("Próxima fecha");
    const dateValue = formMode === "reenroll" ? formatDateDisplay(renewalForm.startDate) : formatDateDisplay(renewalForm.nextInvoiceDate);
    const chargeDisplayAmount = getDiscountedDisplayAmount(renewalForm.charge, renewalForm);
    return `
        <div class="wgs-inline-form-card">
            <div class="wgs-inline-form-header">
                <strong>${escapeHtml(title)}</strong>
                <button type="button" class="wgs-inline-close-btn" data-action="${escapeHtml(cancelAction)}">${escapeHtml(_t("Cancelar"))}</button>
            </div>
            ${formError ? `<div class="wgs-inline-error">${escapeHtml(formError)}</div>` : ""}
            ${formNotice ? `<div class="wgs-inline-notice">${escapeHtml(formNotice)}</div>` : ""}
            ${renewalForm.loading ? `<div class="wgs-inline-loading">${escapeHtml(_t("Calculando importe de renovación..."))}</div>` : ""}
            <div class="wgs-inline-form-meta">
                <div><span>${escapeHtml(_t("Suscripción"))}</span><strong>${escapeHtml(renewalForm.subscriptionName || "-")}</strong></div>
                <div><span>${escapeHtml(_t("Titular"))}</span><strong>${escapeHtml(renewalForm.holderPartnerName || "-")}</strong></div>
                <div><span>${escapeHtml(_t("Producto"))}</span><strong>${escapeHtml(renewalForm.productName || "-")}</strong></div>
                <div><span>${escapeHtml(dateLabel)}</span><strong>${escapeHtml(dateValue || "-")}</strong></div>
                <div><span>${escapeHtml(_t("Importe a cobrar"))}</span><strong>${escapeHtml(formatMoney(chargeDisplayAmount))}</strong></div>
            </div>
            ${renderDiscountAuthorizationSection({
                form: renewalForm,
                formError,
                escapeHtml,
                formatMoney,
                authorizeAction: formMode === "reenroll" ? "authorize-reenroll-discount" : "authorize-renewal-discount",
                codeField: "renewal_discount_code",
                pinField: "renewal_supervisor_pin",
                _t,
            })}
            <div class="wgs-inline-actions">
                <button type="button" class="wgs-primary-action-btn" data-action="${escapeHtml(saveAction)}" ${renewalForm.loading ? "disabled" : ""}>${escapeHtml(submitLabel)}</button>
                <button type="button" class="wgs-secondary-action-btn" data-action="${escapeHtml(cancelAction)}">${escapeHtml(_t("Cancelar"))}</button>
            </div>
        </div>
    `;
}

export { renderRenewalForm };
