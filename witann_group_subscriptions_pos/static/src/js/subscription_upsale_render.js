/** @odoo-module **/

import { buildChargeFromSnapshot, getCurrentPlanChoice } from "./subscription_pricing_snapshot";
import {
    getDiscountedDisplayAmount,
    renderDiscountAuthorizationSection,
} from "./subscription_discount_render";

function renderUpsaleForm({
    item,
    formMode,
    upsaleForm,
    productCatalog,
    filteredParticipants,
    formError,
    formNotice,
    catalogLoading,
    escapeHtml,
    formatMoney,
    getChargeDisplayAmount,
    _t,
}) {
    if (
        formMode !== "upsale"
        || !upsaleForm
        || Number(upsaleForm.subscriptionId || 0) !== Number(item.subscription_id || 0)
    ) {
        return "";
    }
    const holderPartnerId = Number(upsaleForm.holderPartnerId || 0);
    const productOptions = (productCatalog || []).map((product) => {
        const selected = Number(product.id) === Number(upsaleForm.productId || 0) ? "selected" : "";
        return `<option value="${escapeHtml(String(product.id))}" ${selected}>${escapeHtml(product.name || "-")}</option>`;
    }).join("");
    const planOptions = (upsaleForm.plans || []).map((itemPlan) => {
        const value = `${Number(itemPlan.plan_id || 0)}:${Number(itemPlan.pricing_id || 0)}`;
        const selected = value === String(getCurrentPlanChoice(upsaleForm) || "") ? "selected" : "";
        const label = `${itemPlan.plan_name || _t("Plan recurrente")} | ${formatMoney(itemPlan.display_price !== undefined ? itemPlan.display_price : (itemPlan.price || 0))}${itemPlan.interval_label ? ` | ${itemPlan.interval_label}` : ""}`;
        return `<option value="${escapeHtml(value)}" ${selected}>${escapeHtml(label)}</option>`;
    }).join("");
    const participantOptions = Number(upsaleForm.maxParticipantsTotal || 1) > 1
        ? (filteredParticipants || [])
            .map((row) => {
                const rowId = Number(row.id || 0);
                const selected = (upsaleForm.participantIds || []).includes(rowId);
                const isOwner = rowId === holderPartnerId;
                return `
                    <label class="wgs-checkbox-option ${isOwner ? "wgs-checkbox-owner" : ""}">
                        <input type="checkbox" data-field="upsale_participant_toggle" value="${escapeHtml(String(rowId))}" ${selected ? "checked" : ""} ${isOwner ? "disabled" : ""} />
                        <span>${escapeHtml(row.name || "-")}${isOwner ? ` ${escapeHtml(_t("(Titular)"))}` : ""}</span>
                    </label>
                `;
            }).join("")
        : "";
    const recurringCharge = buildChargeFromSnapshot(upsaleForm, "recurring");
    const creditCharge = buildChargeFromSnapshot(upsaleForm, "credit");
    const chargeNow = buildChargeFromSnapshot(upsaleForm, "charge_now");
    const chargeNowDisplayAmount = getDiscountedDisplayAmount(chargeNow, upsaleForm);
    return `
        <div class="wgs-inline-form-card">
            <div class="wgs-inline-form-header">
                <strong>${escapeHtml(_t("Upsale de suscripción"))}</strong>
                <button type="button" class="wgs-inline-close-btn" data-action="cancel-upsale">${escapeHtml(_t("Cancelar"))}</button>
            </div>
            ${formError ? `<div class="wgs-inline-error">${escapeHtml(formError)}</div>` : ""}
            ${formNotice ? `<div class="wgs-inline-notice">${escapeHtml(formNotice)}</div>` : ""}
            ${catalogLoading ? `<div class="wgs-inline-loading">${escapeHtml(_t("Cargando productos de suscripción..."))}</div>` : ""}
            ${upsaleForm.loading ? `<div class="wgs-inline-loading">${escapeHtml(_t("Calculando bonificación e importe del upsale..."))}</div>` : ""}
            <div class="wgs-inline-form-grid">
                <label>
                    <span>${escapeHtml(_t("Producto destino"))}</span>
                    <select data-field="upsale_product_id">
                        <option value="">${escapeHtml(_t("Selecciona un producto"))}</option>
                        ${productOptions}
                    </select>
                </label>
                <label>
                    <span>${escapeHtml(_t("Plan destino"))}</span>
                    <select data-field="upsale_plan_choice" ${(upsaleForm.plans || []).length ? "" : "disabled"}>
                        <option value="">${escapeHtml(_t("Selecciona un plan"))}</option>
                        ${planOptions}
                    </select>
                </label>
            </div>
            <div class="wgs-inline-form-meta">
                <div><span>${escapeHtml(_t("Suscripción"))}</span><strong>${escapeHtml(upsaleForm.subscriptionName || "-")}</strong></div>
                <div><span>${escapeHtml(_t("Titular"))}</span><strong>${escapeHtml(upsaleForm.holderPartnerName || "-")}</strong></div>
                <div><span>${escapeHtml(_t("Paquete actual"))}</span><strong>${escapeHtml((item.package_names || []).join(", ") || "-")}</strong></div>
                <div><span>${escapeHtml(_t("Plan actual"))}</span><strong>${escapeHtml(upsaleForm.sourcePlanName || item.plan_name || "-")}</strong></div>
                <div><span>${escapeHtml(_t("Nuevo recurrente"))}</span><strong>${escapeHtml(formatMoney(getChargeDisplayAmount(recurringCharge)))}</strong></div>
                <div><span>${escapeHtml(_t("Bonificación"))}</span><strong>${escapeHtml(formatMoney(getChargeDisplayAmount(creditCharge)))}</strong></div>
                <div><span>${escapeHtml(_t("Cobro ahora"))}</span><strong>${escapeHtml(formatMoney(chargeNowDisplayAmount))}</strong></div>
                <div><span>${escapeHtml(_t("Cupo destino"))}</span><strong>${escapeHtml(String(upsaleForm.maxParticipantsTotal || 1))}</strong></div>
            </div>
            ${renderDiscountAuthorizationSection({
                form: upsaleForm,
                formError,
                escapeHtml,
                formatMoney,
                authorizeAction: "authorize-upsale-discount",
                percentField: "upsale_discount_percent",
                pinField: "upsale_supervisor_pin",
                _t,
            })}
            ${Number(upsaleForm.maxParticipantsTotal || 1) > 1 ? `
                <div class="wgs-inline-participants">
                    <span class="wgs-inline-section-title">${escapeHtml(_t("Participantes resultantes"))}</span>
                    <input type="text" class="wgs-inline-search" data-field="upsale_participant_search" placeholder="${escapeHtml(_t("Buscar participante"))}" value="${escapeHtml(upsaleForm.participantSearch || "")}" />
                    <div class="wgs-inline-participant-list">${participantOptions}</div>
                </div>
            ` : ""}
            <div class="wgs-inline-actions">
                <button type="button" class="wgs-primary-action-btn" data-action="save-upsale" ${upsaleForm.loading ? "disabled" : ""}>${escapeHtml(_t("Agregar al ticket"))}</button>
                <button type="button" class="wgs-secondary-action-btn" data-action="cancel-upsale">${escapeHtml(_t("Cancelar"))}</button>
            </div>
        </div>
    `;
}

export { renderUpsaleForm };
