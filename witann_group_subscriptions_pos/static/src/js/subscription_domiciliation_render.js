/** @odoo-module **/

import { getDomiciliationInstallmentRows } from "./subscription_domiciliation_selection";

function getInstallmentKindLabel(installment, _t) {
    if (installment.kind === "initial_proration") {
        return _t("Proporcional inicial");
    }
    if (installment.kind === "terminal_prepayment") {
        return _t("Último mes del plazo");
    }
    return _t("Mensualidad");
}

function renderDomiciliationInstallmentSelector({
    domiciliation,
    escapeHtml,
    formatDateDisplay,
    formatMoney,
    _t,
}) {
    const rows = getDomiciliationInstallmentRows(domiciliation);
    if (!domiciliation || !domiciliation.is_domiciliation || !rows.length) {
        return "";
    }
    const isRenewal = domiciliation.selection_mode === "renewal";
    const helperText = isRenewal
        ? _t("Los meses pagados no se modifican. Al marcar un mes se incluyen los pendientes consecutivos anteriores.")
        : _t("El proporcional inicial está incluido. Al marcar un mes se incluyen los anteriores; el último puede cobrarse solo por anticipado.");
    const choices = rows.map((installment) => {
        const stateClass = installment.isFixed
            ? "wgs-domiciliation-installment-fixed"
            : (installment.isToggleable ? "" : "wgs-domiciliation-installment-locked");
        const stateLabel = installment.state === "paid" ? ` · ${_t("Pagada")}` : "";
        return `
            <label class="wgs-domiciliation-installment ${stateClass}">
                <input
                    type="checkbox"
                    data-field="domiciliation_installment_toggle"
                    value="${escapeHtml(String(installment.sequence))}"
                    ${installment.isSelected ? "checked" : ""}
                    ${installment.isToggleable ? "" : "disabled"}
                />
                <span class="wgs-domiciliation-installment-copy">
                    <strong>${escapeHtml(`${_t("Mes")} ${installment.sequence}: ${getInstallmentKindLabel(installment, _t)}${stateLabel}`)}</strong>
                    <small>${escapeHtml(`${formatDateDisplay(installment.period_start_date) || "-"} - ${formatDateDisplay(installment.period_end_date) || "-"} · ${formatMoney(installment.amount || 0)}`)}</small>
                </span>
            </label>
        `;
    }).join("");
    return `
        <section class="wgs-domiciliation-installments">
            <span class="wgs-inline-section-title">${escapeHtml(_t("Mensualidades del plazo forzoso"))}</span>
            <div class="wgs-domiciliation-installment-help">${escapeHtml(helperText)}</div>
            <div class="wgs-domiciliation-installment-list">${choices}</div>
        </section>
    `;
}

export { renderDomiciliationInstallmentSelector };
