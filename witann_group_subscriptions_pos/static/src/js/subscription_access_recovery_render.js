/** @odoo-module **/

export function renderAccessRecovery(recovery, escapeHtml, _t) {
    if (!recovery) {
        return "";
    }
    const labels = {
        queued: _t("Preparada en Odoo"),
        sent: _t("Enviada al gateway; pendiente de confirmacion"),
        delivered: _t("Entregada al equipo; pendiente de confirmacion"),
        confirmed: _t("Confirmada por el equipo"),
        failed: _t("No completada"),
        expired: _t("Sin confirmacion dentro del plazo"),
        superseded: _t("Sustituida por un cambio posterior"),
    };
    const rows = Array.isArray(recovery.targets) ? recovery.targets : [];
    const hasFailure = !rows.length || rows.some((row) => ["failed", "expired", "superseded"].includes(row.state));
    const feedbackClass = hasFailure ? "wgs-inline-error" : "wgs-inline-notice";
    return `<div class="${feedbackClass}" data-role="access-recovery-status">
        <strong>${escapeHtml(_t("Recuperacion de acceso"))}</strong>
        ${rows.map((row) => `<p>${escapeHtml(row.name || "")} · ${escapeHtml(row.device_name || "")}: ${escapeHtml(labels[row.state] || _t("Pendiente"))}${row.error ? ` · ${escapeHtml(row.error)}` : ""}</p>`).join("")}
        ${!rows.length ? `<p>${escapeHtml(_t("Sin destinos preparados. Verifica el acceso autorizado y los equipos."))}</p>` : ""}
        ${rows.some((row) => row.state === "confirmed") ? `<p>${escapeHtml(_t("Confirmacion de comandos; el reconocimiento facial se verifica al pasar por el equipo."))}</p>` : ""}
    </div>`;
}
