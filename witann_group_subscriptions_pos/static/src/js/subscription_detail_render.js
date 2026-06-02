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
    isEditingPartnerInfo,
    partnerEditForm,
    detailAvatarHtml,
    formError,
    formNotice,
    accessActionState = {},
    escapeHtml,
    formatDateDisplay,
    formatDateTimeDisplay,
    _t,
}) {
    const accessEnabled = Boolean(detail.access_enabled);
    const accessBlocked = Boolean(detail.access_blocked);
    const accessLabel = detail.access_label || (accessEnabled ? _t("Acceso activo") : _t("Sin acceso"));
    const accessState = detail.access_state || "missing";
    const actionKey = accessActionState.loadingKey || "";
    const isAccessActionBusy = Boolean(actionKey);
    const accessStatusHtml = `
        <span class="wgs-access-status-chip ${accessEnabled ? "wgs-access-status-chip-on" : "wgs-access-status-chip-off"}${accessBlocked ? " wgs-access-status-chip-blocked" : ""}" title="${escapeHtml(accessLabel)}">
            <span
                class="wgs-access-status-dot ${accessEnabled ? "wgs-access-status-on" : "wgs-access-status-off"}"
                aria-label="${escapeHtml(accessLabel)}"
                data-access-state="${escapeHtml(accessState)}"
            ></span>
            <span>${escapeHtml(accessBlocked ? _t("Acceso bloqueado") : accessEnabled ? _t("Acceso activo") : _t("Sin acceso"))}</span>
        </span>
    `;
    const accessBlockNoticeHtml = accessBlocked ? `
        <div class="wgs-access-block-notice">
            <strong>${escapeHtml(_t("Acceso bloqueado aunque la membresia este vigente."))}</strong>
            <span>${escapeHtml(detail.access_block_reason || _t("Sin motivo capturado"))}</span>
            ${detail.access_blocked_by ? `<small>${escapeHtml(_t("Bloqueado por"))}: ${escapeHtml(detail.access_blocked_by)}</small>` : ""}
        </div>
    ` : "";
    const accessActionsHtml = !isEditingPartnerInfo && !isEditingPartnerPhoto ? `
        <div class="wgs-partner-access-actions">
            <button
                type="button"
                class="wgs-secondary-action-btn${actionKey === "wellhub" ? " wgs-action-loading" : ""}"
                data-action="grant-external-access"
                data-provider="wellhub"
                ${isAccessActionBusy ? "disabled" : ""}
            >${escapeHtml(actionKey === "wellhub" ? _t("Registrando...") : _t("Acceso WellHub"))}</button>
            <button
                type="button"
                class="wgs-secondary-action-btn${actionKey === "totalpass" ? " wgs-action-loading" : ""}"
                data-action="grant-external-access"
                data-provider="totalpass"
                ${isAccessActionBusy ? "disabled" : ""}
            >${escapeHtml(actionKey === "totalpass" ? _t("Registrando...") : _t("Acceso TotalPass"))}</button>
            ${accessBlocked ? `
                <button
                    type="button"
                    class="wgs-secondary-action-btn${actionKey === "unblock" ? " wgs-action-loading" : ""}"
                    data-action="unblock-access"
                    ${isAccessActionBusy ? "disabled" : ""}
                >${escapeHtml(actionKey === "unblock" ? _t("Desbloqueando...") : _t("Desbloquear acceso"))}</button>
            ` : `
                <button
                    type="button"
                    class="wgs-danger-action-btn${actionKey === "block" ? " wgs-action-loading" : ""}"
                    data-action="block-access"
                    ${isAccessActionBusy ? "disabled" : ""}
                >${escapeHtml(actionKey === "block" ? _t("Bloqueando...") : _t("Bloquear acceso"))}</button>
            `}
        </div>
    ` : "";
    const detailBodyHtml = isEditingPartnerInfo
        ? `
            ${formError ? `<div class="wgs-inline-error wgs-inline-error-compact">${escapeHtml(formError)}</div>` : ""}
            ${formNotice ? `<div class="wgs-inline-notice wgs-inline-notice-compact">${escapeHtml(formNotice)}</div>` : ""}
            <div class="wgs-inline-form-grid wgs-detail-inline-editor">
                <label>
                    <span>${escapeHtml(_t("Nombre"))}</span>
                    <input type="text" data-field="partner_name" value="${escapeHtml(partnerEditForm.name || "")}" />
                </label>
                <label>
                    <span>${escapeHtml(_t("Teléfono"))}</span>
                    <input type="text" data-field="partner_phone" value="${escapeHtml(partnerEditForm.phone || "")}" />
                </label>
                <label>
                    <span>${escapeHtml(_t("Email"))}</span>
                    <input type="email" data-field="partner_email" value="${escapeHtml(partnerEditForm.email || "")}" />
                </label>
                <label>
                    <span>${escapeHtml(_t("CURP"))}</span>
                    <input type="text" data-field="partner_curp" value="${escapeHtml(partnerEditForm.curp || "")}" />
                </label>
                <label>
                    <span>${escapeHtml(_t("Género"))}</span>
                    <select data-field="partner_gender">
                        <option value="">${escapeHtml(_t("Selecciona"))}</option>
                        <option value="male" ${partnerEditForm.gender === "male" ? "selected" : ""}>${escapeHtml(_t("Masculino"))}</option>
                        <option value="female" ${partnerEditForm.gender === "female" ? "selected" : ""}>${escapeHtml(_t("Femenino"))}</option>
                        <option value="other" ${partnerEditForm.gender === "other" ? "selected" : ""}>${escapeHtml(_t("Otro"))}</option>
                    </select>
                </label>
                <label>
                    <span>${escapeHtml(_t("Cumpleaños"))}</span>
                    <input type="date" data-field="partner_birthday" value="${escapeHtml(partnerEditForm.birthday || "")}" />
                </label>
            </div>
            <div class="wgs-inline-actions">
                <button type="button" class="wgs-primary-action-btn" data-action="save-partner-edit">${escapeHtml(_t("Guardar datos"))}</button>
                <button type="button" class="wgs-secondary-action-btn" data-action="cancel-partner-edit">${escapeHtml(_t("Cancelar"))}</button>
            </div>
        `
        : `
            <div class="wgs-detail-contact-grid">
                <div><span>${escapeHtml(_t("Telefono"))}</span><strong>${escapeHtml(detail.phone || "-")}</strong></div>
                <div><span>${escapeHtml(_t("Email"))}</span><strong>${escapeHtml(detail.email || "-")}</strong></div>
                <div><span>${escapeHtml(_t("CURP"))}</span><strong>${escapeHtml(detail.curp || "-")}</strong></div>
                <div><span>${escapeHtml(_t("Genero"))}</span><strong>${escapeHtml(detail.gender || "-")}</strong></div>
                <div><span>${escapeHtml(_t("Cumpleanos"))}</span><strong>${escapeHtml(formatDateDisplay(detail.birthday) || "-")}</strong></div>
                <div><span>${escapeHtml(_t("Ultimo acceso"))}</span><strong>${escapeHtml(formatDateTimeDisplay(detail.last_access) || "-")}</strong></div>
                <div><span>${escapeHtml(_t("Resumen"))}</span><strong>${escapeHtml(detail.package_label || _t("Sin suscripcion"))}</strong></div>
            </div>
            ${accessBlockNoticeHtml}
            ${accessActionsHtml}
        `;
    return `
        <div class="wgs-detail-header-card ${isEditingPartnerPhoto ? "wgs-detail-header-card-editing" : ""}">
            ${detailAvatarHtml}
            <div class="wgs-detail-header-text">
                <div class="wgs-detail-title-row">
                    <h4>${escapeHtml(detail.partner_name || "-")}</h4>
                    ${accessStatusHtml}
                </div>
                ${detailBodyHtml}
            </div>
        </div>
    `;
}

export {
    renderDetailEmpty,
    renderDetailHeader,
    renderDetailLoading,
};
