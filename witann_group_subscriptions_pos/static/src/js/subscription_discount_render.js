/** @odoo-module **/

import { buildChargeFromSnapshot } from "./subscription_pricing_snapshot";

function getAuthorizedDiscountPercent(form) {
    return Number(
        form
        && form.authorizedDiscount
        && form.authorizedDiscount.discountPercent !== undefined
            ? form.authorizedDiscount.discountPercent
            : 0
    ) || 0;
}

function getDiscountedDisplayAmount(charge, form) {
    const snapshotFlow = String(form && form.pricingSnapshot && form.pricingSnapshot.flow ? form.pricingSnapshot.flow : "new");
    const derivedChargeType = ["renewal", "reenroll", "upsale"].includes(snapshotFlow)
        ? "charge_now"
        : "recurring";
    const effectiveCharge = charge && charge.displayAmount !== undefined
        ? charge
        : buildChargeFromSnapshot(form, derivedChargeType);
    const displayAmount = Number(effectiveCharge && effectiveCharge.displayAmount !== undefined ? effectiveCharge.displayAmount : 0) || 0;
    const percent = getAuthorizedDiscountPercent(form);
    if (!percent) {
        return displayAmount;
    }
    return displayAmount * (1 - (percent / 100));
}

function getRequestedDiscountPercent(form) {
    return Number(form && form.discountPercent !== undefined ? form.discountPercent : 0) || 0;
}

function renderDiscountAuthorizationSection({
    form,
    escapeHtml,
    formatMoney,
    authorizeAction,
    percentField,
    pinField,
    _t,
}) {
    if (!form) {
        return "";
    }
    const requestedPercent = getRequestedDiscountPercent(form);
    const authorized = Boolean(
        requestedPercent > 0
        && form.authorizedDiscount
        && Number(form.authorizedDiscount.discountPercent || 0) === requestedPercent
    );
    const authorizedLabel = authorized && form.authorizedDiscount
        ? `${form.authorizedDiscount.label || _t("Descuento autorizado")} | ${formatMoney(getDiscountedDisplayAmount(form.charge, form))}`
        : "";
    const authMessage = authorized && form.authorizedDiscount
        ? _t("Autorizado por %s").replace("%s", form.authorizedDiscount.authorizedBy || "-")
        : "";

    return `
        <div class="wgs-inline-discount-card">
            <div class="wgs-inline-section-title">${escapeHtml(_t("Descuento autorizado"))}</div>
            <div class="wgs-inline-form-grid">
                <label>
                    <span>${escapeHtml(_t("Descuento %"))}</span>
                    <input type="number" min="0" max="100" step="0.01" data-field="${escapeHtml(percentField)}" value="${escapeHtml(form.discountPercent || "")}" placeholder="0" />
                </label>
                <label>
                    <span>${escapeHtml(_t("PIN WGS"))}</span>
                    <input type="password" data-field="${escapeHtml(pinField)}" value="${escapeHtml(form.supervisorPin || "")}" />
                </label>
            </div>
            ${authorized ? `
                <div class="wgs-inline-notice wgs-inline-notice-compact">
                    ${escapeHtml(authMessage)}
                    <br/>
                    ${escapeHtml(authorizedLabel)}
                </div>
            ` : ""}
            <div class="wgs-inline-actions">
                <button type="button" class="wgs-secondary-action-btn" data-action="${escapeHtml(authorizeAction)}">${escapeHtml(_t("Aplicar descuento"))}</button>
            </div>
            ${requestedPercent > 0 && !authorized ? `
                <div class="wgs-inline-note">${escapeHtml(_t("Autoriza el porcentaje capturado antes de agregarlo al ticket."))}</div>
            ` : ""}
        </div>
    `;
}

export {
    getAuthorizedDiscountPercent,
    getDiscountedDisplayAmount,
    getRequestedDiscountPercent,
    renderDiscountAuthorizationSection,
};
