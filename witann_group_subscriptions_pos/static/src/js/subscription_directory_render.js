/** @odoo-module **/

function renderDirectorySummary({
    counts,
    activeStateFilter = "actionable",
    directoryLoading,
    directoryLoadError,
    _t,
    escapeHtml,
}) {
    const activeClass = (stateFilter) => stateFilter === activeStateFilter ? " wgs-summary-active" : "";
    return `
        <button type="button" class="wgs-summary-pill wgs-summary-action${activeClass("all")}" data-state-filter="all">${_t("Total")}: ${counts.total || 0}</button>
        <button type="button" class="wgs-summary-pill wgs-summary-action wgs-summary-positive${activeClass("progress")}" data-state-filter="progress">${_t("En progreso")}: ${counts.progress || 0}</button>
        <button type="button" class="wgs-summary-pill wgs-summary-action wgs-summary-warning${activeClass("renew")}" data-state-filter="renew">${_t("Por renovar")}: ${counts.renew || 0}</button>
        ${counts.paused ? `<span class="wgs-summary-pill wgs-summary-warning">${_t("Pausadas")}: ${counts.paused || 0}</span>` : ""}
        <button type="button" class="wgs-summary-pill wgs-summary-action wgs-summary-negative${activeClass("cancel")}" data-state-filter="cancel">${_t("Canceladas")}: ${counts.cancel || 0}</button>
        <button type="button" class="wgs-summary-pill wgs-summary-action wgs-summary-none${activeClass("none")}" data-state-filter="none">${_t("Sin suscripcion")}: ${counts.none || 0}</button>
        <span class="wgs-summary-pill">${_t("Con cumpleanos")}: ${counts.birthday || 0}</span>
        ${directoryLoading ? `<span class="wgs-summary-pill">${_t("Cargando directorio...")}</span>` : ""}
        ${directoryLoadError ? `<span class="wgs-summary-pill wgs-summary-negative">${escapeHtml(directoryLoadError)}</span>` : ""}
    `;
}

function renderDirectoryRows({
    rows,
    selectedPartnerId,
    getStateClass,
    escapeHtml,
    formatDateDisplay,
    formatDateTimeDisplay,
    _t,
}) {
    const renderAccessStatusIcon = (row) => {
        const enabled = Boolean(row.access_enabled);
        const label = row.access_label || (enabled ? _t("Acceso activo") : _t("Sin acceso"));
        const state = row.access_state || "missing";
        return `
            <span
                class="wgs-access-status-dot ${enabled ? "wgs-access-status-on" : "wgs-access-status-off"}"
                title="${escapeHtml(label)}"
                aria-label="${escapeHtml(label)}"
                data-access-state="${escapeHtml(state)}"
            ></span>
        `;
    };
    return rows.map((row) => {
        const rowClass = row.id === selectedPartnerId ? "wgs-selected-row" : "";
        const stateClass = getStateClass(row.state);
        return `
            <tr class="${rowClass}" data-partner-id="${escapeHtml(String(row.id))}">
                <td><img class="wgs-partner-avatar" src="${escapeHtml(row.image_url || "")}" alt="${escapeHtml(row.name || "")}" loading="lazy" decoding="async" /></td>
                <td class="wgs-cell-name">${escapeHtml(row.name || "-")}</td>
                <td><span class="wgs-state-badge ${stateClass}">${escapeHtml(row.state_label || _t("Sin suscripcion"))}</span></td>
                <td class="wgs-access-status-cell">${renderAccessStatusIcon(row)}</td>
                <td>${escapeHtml(row.package_label || "-")}</td>
                <td>${escapeHtml(row.plan_name || "-")}</td>
                <td>${escapeHtml(formatDateDisplay(row.valid_until) || "-")}</td>
                <td>${escapeHtml(formatDateTimeDisplay(row.last_access) || "-")}</td>
            </tr>
        `;
    }).join("");
}

function downloadDirectoryAsXls({
    rows,
    escapeHtml,
    formatDateDisplay,
    formatDateTimeDisplay,
    _t,
}) {
    const dataRows = Array.isArray(rows) ? rows : [];
    const filenameDate = new Date().toISOString().slice(0, 10);
    const filename = `suscripciones_pos_${filenameDate}.xls`;

    const tableRows = dataRows.map((row) => `
        <tr>
            <td>${escapeHtml(row.name || "-")}</td>
            <td>${escapeHtml(row.state_label || _t("Sin suscripcion"))}</td>
            <td>${escapeHtml(row.access_label || _t("Sin acceso"))}</td>
            <td>${escapeHtml(row.package_label || "-")}</td>
            <td>${escapeHtml(row.plan_name || "-")}</td>
            <td>${escapeHtml(formatDateDisplay(row.start_date) || "-")}</td>
            <td>${escapeHtml(formatDateDisplay(row.valid_until) || "-")}</td>
            <td>${escapeHtml(row.gender || "-")}</td>
            <td>${escapeHtml(formatDateDisplay(row.birthday) || "-")}</td>
            <td>${escapeHtml(formatDateTimeDisplay(row.last_access) || "-")}</td>
            <td>${escapeHtml(row.phone || "-")}</td>
            <td>${escapeHtml(row.email || "-")}</td>
        </tr>
    `).join("");

    const html = `
        <html>
            <head>
                <meta charset="UTF-8" />
                <style>
                    table { border-collapse: collapse; font-family: Arial, sans-serif; font-size: 12px; }
                    th, td { border: 1px solid #999; padding: 6px; text-align: left; }
                    th { background: #e9eef5; }
                </style>
            </head>
            <body>
                <table>
                    <thead>
                        <tr>
                            <th>${escapeHtml(_t("Cliente"))}</th>
                            <th>${escapeHtml(_t("Estado"))}</th>
                            <th>${escapeHtml(_t("Acceso"))}</th>
                            <th>${escapeHtml(_t("Paquete"))}</th>
                            <th>${escapeHtml(_t("Plan"))}</th>
                            <th>${escapeHtml(_t("Inicio"))}</th>
                            <th>${escapeHtml(_t("Vencimiento"))}</th>
                            <th>${escapeHtml(_t("Genero"))}</th>
                            <th>${escapeHtml(_t("Cumpleanos"))}</th>
                            <th>${escapeHtml(_t("Ultimo acceso"))}</th>
                            <th>${escapeHtml(_t("Telefono"))}</th>
                            <th>${escapeHtml(_t("Email"))}</th>
                        </tr>
                    </thead>
                    <tbody>${tableRows}</tbody>
                </table>
            </body>
        </html>
    `;

    const blob = new Blob([`\uFEFF${html}`], { type: "application/vnd.ms-excel;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 500);
}

export {
    downloadDirectoryAsXls,
    renderDirectoryRows,
    renderDirectorySummary,
};
