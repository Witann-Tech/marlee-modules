/** @odoo-module **/

const WGS_POS_ACCESS_LOG_TIME_ZONE = "America/Mexico_City";

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

function getTodayAccessLogRange() {
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

function getAccessResultClass(result) {
    if (result === "allowed") {
        return "wgs-state-positive";
    }
    if (result === "error") {
        return "wgs-state-warning";
    }
    return "wgs-state-negative";
}

function renderAccessLogToolbar({
    filters,
    devices,
    escapeHtml,
    _t,
}) {
    const deviceOptions = (devices || []).map((device) => `
        <option value="${escapeHtml(String(device.id || ""))}" ${String(filters.deviceId || "") === String(device.id || "") ? "selected" : ""}>
            ${escapeHtml(device.name || device.serial || "-")}
        </option>
    `).join("");
    return `
        <div class="wgs-access-log-toolbar">
            <label>
                <span>${escapeHtml(_t("Desde"))}</span>
                <input type="datetime-local" class="wgs-access-log-from" value="${escapeHtml(filters.from || "")}" />
            </label>
            <label>
                <span>${escapeHtml(_t("Hasta"))}</span>
                <input type="datetime-local" class="wgs-access-log-to" value="${escapeHtml(filters.to || "")}" />
            </label>
            <label>
                <span>${escapeHtml(_t("Resultado"))}</span>
                <select class="wgs-access-log-result">
                    <option value="all" ${filters.result === "all" ? "selected" : ""}>${escapeHtml(_t("Todos"))}</option>
                    <option value="allowed" ${filters.result === "allowed" ? "selected" : ""}>${escapeHtml(_t("Exitoso"))}</option>
                    <option value="denied" ${filters.result === "denied" ? "selected" : ""}>${escapeHtml(_t("Fallido"))}</option>
                    <option value="error" ${filters.result === "error" ? "selected" : ""}>${escapeHtml(_t("Error"))}</option>
                </select>
            </label>
            <label>
                <span>${escapeHtml(_t("Puerta"))}</span>
                <select class="wgs-access-log-device">
                    <option value="">${escapeHtml(_t("Todas"))}</option>
                    ${deviceOptions}
                </select>
            </label>
            <button type="button" class="wgs-primary-action-btn wgs-access-log-refresh">${escapeHtml(_t("Buscar"))}</button>
        </div>
    `;
}

function renderAccessLogRows({
    rows,
    loading,
    escapeHtml,
    formatDateTimeDisplay,
    _t,
}) {
    if (loading && !(rows || []).length) {
        return `<tr><td colspan="5">${escapeHtml(_t("Cargando bitacora de accesos..."))}</td></tr>`;
    }
    if (!(rows || []).length) {
        return `<tr><td colspan="5">${escapeHtml(_t("No hay accesos para los filtros actuales."))}</td></tr>`;
    }
    return rows.map((row) => `
        <tr>
            <td>${escapeHtml(formatDateTimeDisplay(row.occurred_at) || "-")}</td>
            <td>${escapeHtml(row.device_name || row.device_serial || "-")}</td>
            <td>${escapeHtml(row.partner_name || "-")}</td>
            <td><span class="wgs-state-badge ${getAccessResultClass(row.result)}">${escapeHtml(row.result_label || "-")}</span></td>
            <td>${escapeHtml(row.site_name || "-")}</td>
        </tr>
    `).join("");
}

function renderAccessLogContent({
    rows,
    loading,
    error,
    notice,
    total,
    siteNames,
    escapeHtml,
    formatDateTimeDisplay,
    _t,
}) {
    const sitesLabel = (siteNames || []).length ? siteNames.join(", ") : _t("Sin sitio");
    const totalLabel = loading
        ? _t("Consultando accesos...")
        : _t("%s eventos").replace("%s", String(total || 0));
    return `
        <div class="wgs-access-log-summary">
            <span class="wgs-summary-pill">${escapeHtml(totalLabel)}</span>
            <span class="wgs-summary-pill">${escapeHtml(_t("Sitio"))}: ${escapeHtml(sitesLabel)}</span>
        </div>
        ${notice ? `<div class="wgs-access-log-notice">${escapeHtml(notice)}</div>` : ""}
        ${error ? `<div class="wgs-access-log-error">${escapeHtml(error)}</div>` : ""}
        <div class="wgs-access-log-table-wrap">
            <table class="wgs-status-table wgs-access-log-table">
                <thead>
                    <tr>
                        <th>${escapeHtml(_t("Timestamp"))}</th>
                        <th>${escapeHtml(_t("SF / puerta"))}</th>
                        <th>${escapeHtml(_t("Cliente"))}</th>
                        <th>${escapeHtml(_t("Resultado"))}</th>
                        <th>${escapeHtml(_t("Sitio"))}</th>
                    </tr>
                </thead>
                <tbody>
                    ${renderAccessLogRows({ rows, loading, escapeHtml, formatDateTimeDisplay, _t })}
                </tbody>
            </table>
        </div>
    `;
}

export {
    WGS_POS_ACCESS_LOG_TIME_ZONE,
    getTodayAccessLogRange,
    localDateTimeInputToUtcString,
    renderAccessLogContent,
    renderAccessLogToolbar,
};
