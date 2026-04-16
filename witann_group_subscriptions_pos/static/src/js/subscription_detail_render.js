/** @odoo-module **/

function renderDetailEmpty({ title, message, escapeHtml }) {
    return `
        <div class="wgs-detail-empty">
            <strong>${escapeHtml(title)}</strong>
            <p>${escapeHtml(message)}</p>
        </div>
    `;
}

function renderDetailLoading({ title, message, escapeHtml }) {
    return `
        <div class="wgs-detail-empty">
            <strong>${escapeHtml(title)}</strong>
            <p>${escapeHtml(message)}</p>
        </div>
    `;
}

function renderDetailHeader({
    detail,
    isEditingPartnerPhoto,
    detailAvatarHtml,
    summaryStateClass,
    escapeHtml,
    formatDateDisplay,
    formatDateTimeDisplay,
    _t,
}) {
    return `
        <div class="wgs-detail-header-card ${isEditingPartnerPhoto ? "wgs-detail-header-card-editing" : ""}">
            ${detailAvatarHtml}
            <div class="wgs-detail-header-text">
                <div class="wgs-detail-title-row">
                    <h4>${escapeHtml(detail.partner_name || "-")}</h4>
                    <span class="wgs-state-badge ${summaryStateClass}">${escapeHtml(detail.state_label || _t("Sin suscripcion"))}</span>
                </div>
                <div class="wgs-detail-contact-grid">
                    <div><span>${escapeHtml(_t("Telefono"))}</span><strong>${escapeHtml(detail.phone || "-")}</strong></div>
                    <div><span>${escapeHtml(_t("Email"))}</span><strong>${escapeHtml(detail.email || "-")}</strong></div>
                    <div><span>${escapeHtml(_t("CURP"))}</span><strong>${escapeHtml(detail.curp || "-")}</strong></div>
                    <div><span>${escapeHtml(_t("Genero"))}</span><strong>${escapeHtml(detail.gender || "-")}</strong></div>
                    <div><span>${escapeHtml(_t("Cumpleanos"))}</span><strong>${escapeHtml(formatDateDisplay(detail.birthday) || "-")}</strong></div>
                    <div><span>${escapeHtml(_t("Ultimo acceso"))}</span><strong>${escapeHtml(formatDateTimeDisplay(detail.last_access) || "-")}</strong></div>
                    <div><span>${escapeHtml(_t("Resumen"))}</span><strong>${escapeHtml(detail.package_label || _t("Sin suscripcion"))}</strong></div>
                </div>
            </div>
        </div>
    `;
}

export {
    renderDetailEmpty,
    renderDetailHeader,
    renderDetailLoading,
};
