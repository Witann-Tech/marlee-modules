/** @odoo-module **/

function pad2(value) {
    return String(value).padStart(2, "0");
}

function toLocalDateTimeInputValue(date) {
    return [
        date.getFullYear(),
        pad2(date.getMonth() + 1),
        pad2(date.getDate()),
    ].join("-") + "T" + [pad2(date.getHours()), pad2(date.getMinutes())].join(":");
}

function getTodaySalesHistoryRange() {
    const start = new Date();
    start.setHours(0, 0, 0, 0);
    const end = new Date();
    end.setHours(23, 59, 0, 0);
    return {
        from: toLocalDateTimeInputValue(start),
        to: toLocalDateTimeInputValue(end),
    };
}

function localDateTimeInputToUtcString(value) {
    if (!value) {
        return false;
    }
    const text = String(value || "").trim().replace("T", " ");
    if (!text) {
        return false;
    }
    return text.length === 16 ? `${text}:00` : text;
}

function renderSalesHistoryToolbar({
    filters,
    sellers,
    sessions,
    escapeHtml,
    _t,
}) {
    const sellerOptions = (sellers || []).map((seller) => `
        <option value="${escapeHtml(seller.key || "")}" ${String(filters.seller || "") === String(seller.key || "") ? "selected" : ""}>
            ${escapeHtml(seller.name || "-")}
        </option>
    `).join("");
    const sessionOptions = (sessions || []).map((session) => `
        <option value="${escapeHtml(String(session.id || ""))}" ${String(filters.sessionId || "") === String(session.id || "") ? "selected" : ""}>
            ${escapeHtml(session.name || "-")}
        </option>
    `).join("");
    return `
        <div class="wgs-sales-history-toolbar">
            <label>
                <span>${escapeHtml(_t("Desde"))}</span>
                <input type="datetime-local" class="wgs-sales-history-from" value="${escapeHtml(filters.from || "")}" />
            </label>
            <label>
                <span>${escapeHtml(_t("Hasta"))}</span>
                <input type="datetime-local" class="wgs-sales-history-to" value="${escapeHtml(filters.to || "")}" />
            </label>
            <label>
                <span>${escapeHtml(_t("Vendedor"))}</span>
                <select class="wgs-sales-history-seller">
                    <option value="">${escapeHtml(_t("Todos"))}</option>
                    ${sellerOptions}
                </select>
            </label>
            <label>
                <span>${escapeHtml(_t("Sesion"))}</span>
                <select class="wgs-sales-history-session">
                    <option value="">${escapeHtml(_t("Todas"))}</option>
                    ${sessionOptions}
                </select>
            </label>
            <button type="button" class="wgs-primary-action-btn wgs-sales-history-refresh">${escapeHtml(_t("Buscar"))}</button>
        </div>
    `;
}

function renderSalesHistoryRows({
    rows,
    loading,
    escapeHtml,
    formatDateTimeDisplay,
    formatMoney,
    _t,
}) {
    if (loading && !(rows || []).length) {
        return `<tr><td colspan="8">${escapeHtml(_t("Cargando ventas POS..."))}</td></tr>`;
    }
    if (!(rows || []).length) {
        return `<tr><td colspan="8">${escapeHtml(_t("No hay ventas para los filtros actuales."))}</td></tr>`;
    }
    return rows.map((row) => `
        <tr>
            <td>${escapeHtml(formatDateTimeDisplay(row.date_order) || "-")}</td>
            <td>${escapeHtml(row.pos_reference || row.name || "-")}</td>
            <td>${escapeHtml(row.seller_name || "-")}</td>
            <td>${escapeHtml(row.session_name || "-")}</td>
            <td>${escapeHtml(row.partner_name || "-")}</td>
            <td>${escapeHtml(row.line_summary || "-")}</td>
            <td>${escapeHtml(formatMoney(row.amount_total || 0))}</td>
            <td>${escapeHtml(row.state_label || row.state || "-")}</td>
        </tr>
    `).join("");
}

function renderSalesHistoryContent({
    rows,
    loading,
    error,
    totalCount,
    totalAmount,
    limited,
    escapeHtml,
    formatDateTimeDisplay,
    formatMoney,
    _t,
}) {
    const countLabel = loading
        ? _t("Consultando ventas...")
        : _t("%s ventas").replace("%s", String(totalCount || 0));
    return `
        <div class="wgs-sales-history-summary">
            <span class="wgs-summary-pill">${escapeHtml(countLabel)}</span>
            <span class="wgs-summary-pill">${escapeHtml(_t("Total"))}: ${escapeHtml(formatMoney(totalAmount || 0))}</span>
            ${limited ? `<span class="wgs-summary-pill wgs-summary-warning">${escapeHtml(_t("Resultado limitado"))}</span>` : ""}
        </div>
        ${error ? `<div class="wgs-access-log-error">${escapeHtml(error)}</div>` : ""}
        <div class="wgs-sales-history-table-wrap">
            <table class="wgs-status-table wgs-sales-history-table">
                <thead>
                    <tr>
                        <th>${escapeHtml(_t("Fecha"))}</th>
                        <th>${escapeHtml(_t("Ticket"))}</th>
                        <th>${escapeHtml(_t("Vendedor"))}</th>
                        <th>${escapeHtml(_t("Sesion"))}</th>
                        <th>${escapeHtml(_t("Cliente"))}</th>
                        <th>${escapeHtml(_t("Productos"))}</th>
                        <th>${escapeHtml(_t("Total"))}</th>
                        <th>${escapeHtml(_t("Estado"))}</th>
                    </tr>
                </thead>
                <tbody>
                    ${renderSalesHistoryRows({ rows, loading, escapeHtml, formatDateTimeDisplay, formatMoney, _t })}
                </tbody>
            </table>
        </div>
    `;
}

export {
    getTodaySalesHistoryRange,
    localDateTimeInputToUtcString,
    renderSalesHistoryContent,
    renderSalesHistoryToolbar,
};
