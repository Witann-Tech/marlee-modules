/** @odoo-module **/

import {
    getDiscountedDisplayAmount,
    renderDiscountAuthorizationSection,
} from "./subscription_discount_render";
import { buildChargeFromSnapshot } from "./subscription_pricing_snapshot";

function renderRenewalForm({
    item,
    formMode,
    renewalForm,
    productCatalog = [],
    formError,
    formNotice,
    catalogLoading = false,
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
    const isReenroll = formMode === "reenroll";
    const productOptions = (productCatalog || []).map((product) => {
        const selected = Number(product.id) === Number(renewalForm.productId) ? "selected" : "";
        return `<option value="${escapeHtml(String(product.id))}" ${selected}>${escapeHtml(product.name || "-")}</option>`;
    }).join("");
    const planOptions = (renewalForm.plans || []).map((plan) => {
        const value = `${Number(plan.plan_id || 0)}:${Number(plan.pricing_id || 0)}`;
        const snapshot = renewalForm.pricingSnapshot || {};
        const selectedValue = `${Number(snapshot.plan_id || 0)}:${Number(snapshot.pricing_id || 0)}`;
        const selected = value === selectedValue ? "selected" : "";
        const planDisplayPrice = Number(plan.display_price !== undefined ? plan.display_price : (plan.price || 0)) || 0;
        const label = `${plan.plan_name || _t("Plan recurrente")} | ${formatMoney(planDisplayPrice)}${plan.interval_label ? ` | ${plan.interval_label}` : ""}`;
        return `<option value="${escapeHtml(value)}" ${selected}>${escapeHtml(label)}</option>`;
    }).join("");
    const chargeDisplayAmount = getDiscountedDisplayAmount(
        buildChargeFromSnapshot(renewalForm, "charge_now"),
        renewalForm
    );
    const pricingSnapshot = renewalForm.pricingSnapshot || {};
    const isDirectDebitRenewal = !isReenroll && Boolean(pricingSnapshot.direct_debit);
    const dueMonthCount = Number(pricingSnapshot.direct_debit_due_month_count || 0);
    const monthsToPay = Number(renewalForm.directDebitMonthsToPay || pricingSnapshot.direct_debit_months_to_pay || dueMonthCount || 0);
    const directDebitMonthOptions = Array.from({ length: Math.max(dueMonthCount, 0) }, (_value, index) => {
        const value = index + 1;
        const selected = value === monthsToPay ? "selected" : "";
        const label = value === dueMonthCount
            ? _t("%s meses (total)").replace("%s", String(value))
            : _t("%s mes(es)").replace("%s", String(value));
        return `<option value="${escapeHtml(String(value))}" ${selected}>${escapeHtml(label)}</option>`;
    }).join("");
    const directDebitNotice = isDirectDebitRenewal
        ? (
            dueMonthCount <= 0
                ? _t("Este domiciliado no tiene meses vencidos por cobrar.")
                : monthsToPay < dueMonthCount
                    ? _t("Pago parcial: el acceso no se restaurará hasta cubrir todos los meses vencidos y el vigente.")
                    : _t("Pago total: al pagar se restaurará acceso si cubre el mes vigente.")
        )
        : "";
    return `
        <div class="wgs-inline-form-card">
            <div class="wgs-inline-form-header">
                <strong>${escapeHtml(title)}</strong>
                <button type="button" class="wgs-inline-close-btn" data-action="${escapeHtml(cancelAction)}">${escapeHtml(_t("Cancelar"))}</button>
            </div>
            ${formError ? `<div class="wgs-inline-error">${escapeHtml(formError)}</div>` : ""}
            ${formNotice ? `<div class="wgs-inline-notice">${escapeHtml(formNotice)}</div>` : ""}
            ${isReenroll && catalogLoading ? `<div class="wgs-inline-loading">${escapeHtml(_t("Cargando paquetes de suscripción..."))}</div>` : ""}
            ${renewalForm.loading ? `<div class="wgs-inline-loading">${escapeHtml(_t("Calculando importe de renovación..."))}</div>` : ""}
            ${isReenroll ? `
                <div class="wgs-inline-form-grid">
                    <label>
                        <span>${escapeHtml(_t("Paquete"))}</span>
                        <select data-field="reenroll_product_id">
                            <option value="">${escapeHtml(_t("Selecciona un paquete"))}</option>
                            ${productOptions}
                        </select>
                    </label>
                    <label>
                        <span>${escapeHtml(_t("Plan recurrente"))}</span>
                        <select data-field="reenroll_plan_choice" ${(renewalForm.plans || []).length ? "" : "disabled"}>
                            <option value="">${escapeHtml(_t("Selecciona un plan"))}</option>
                            ${planOptions}
                        </select>
                    </label>
                    <label>
                        <span>${escapeHtml(_t("Fecha de inicio"))}</span>
                        <input type="date" data-field="reenroll_start_date" value="${escapeHtml(renewalForm.startDate || "")}" />
                    </label>
                    <div>
                        <span>${escapeHtml(_t("Importe a cobrar"))}</span>
                        <strong class="wgs-inline-static-value">${escapeHtml(formatMoney(chargeDisplayAmount))}</strong>
                    </div>
                </div>
            ` : `
                <div class="wgs-inline-form-meta">
                    <div><span>${escapeHtml(_t("Suscripción"))}</span><strong>${escapeHtml(renewalForm.subscriptionName || "-")}</strong></div>
                    <div><span>${escapeHtml(_t("Titular"))}</span><strong>${escapeHtml(renewalForm.holderPartnerName || "-")}</strong></div>
                    <div><span>${escapeHtml(_t("Producto"))}</span><strong>${escapeHtml(renewalForm.productName || "-")}</strong></div>
                    <div><span>${escapeHtml(dateLabel)}</span><strong>${escapeHtml(dateValue || "-")}</strong></div>
                    <div><span>${escapeHtml(_t("Importe a cobrar"))}</span><strong>${escapeHtml(formatMoney(chargeDisplayAmount))}</strong></div>
                </div>
                ${isDirectDebitRenewal ? `
                    <div class="wgs-inline-form-grid">
                        <label>
                            <span>${escapeHtml(_t("Meses a pagar"))}</span>
                            <select data-field="renewal_direct_debit_months_to_pay" ${dueMonthCount > 0 ? "" : "disabled"}>
                                ${directDebitMonthOptions || `<option value="0">${escapeHtml(_t("Sin adeudo"))}</option>`}
                            </select>
                        </label>
                        <div>
                            <span>${escapeHtml(_t("Pagado hasta"))}</span>
                            <strong class="wgs-inline-static-value">${escapeHtml(formatDateDisplay(pricingSnapshot.direct_debit_paid_until_date) || "-")}</strong>
                        </div>
                        <div>
                            <span>${escapeHtml(_t("Adeudo total"))}</span>
                            <strong class="wgs-inline-static-value">${escapeHtml(formatMoney(pricingSnapshot.direct_debit_amount_due_total || 0))}</strong>
                        </div>
                        <div>
                            <span>${escapeHtml(_t("Plazo forzoso"))}</span>
                            <strong class="wgs-inline-static-value">${escapeHtml(formatDateDisplay(pricingSnapshot.direct_debit_term_end_date) || "-")}</strong>
                        </div>
                    </div>
                    <div class="wgs-inline-notice">${escapeHtml(directDebitNotice)}</div>
                ` : ""}
            `}
            ${renderDiscountAuthorizationSection({
                form: renewalForm,
                formError,
                escapeHtml,
                formatMoney,
                authorizeAction: formMode === "reenroll" ? "authorize-reenroll-discount" : "authorize-renewal-discount",
                percentField: "renewal_discount_percent",
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
