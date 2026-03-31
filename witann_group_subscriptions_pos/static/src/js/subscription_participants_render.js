/** @odoo-module **/

function renderParticipantEditForm({
    item,
    formMode,
    participantEditForm,
    filteredParticipants,
    formError,
    formNotice,
    escapeHtml,
    _t,
}) {
    if (
        formMode !== "participants"
        || !participantEditForm
        || Number(participantEditForm.subscriptionId || 0) !== Number(item.subscription_id || 0)
    ) {
        return "";
    }
    const holderPartnerId = Number(participantEditForm.holderPartnerId || 0);
    const participantOptions = Number(participantEditForm.maxParticipantsTotal || 1) > 1
        ? (filteredParticipants || [])
            .map((row) => {
                const rowId = Number(row.id || 0);
                const selected = (participantEditForm.participantIds || []).includes(rowId);
                const isOwner = rowId === holderPartnerId;
                return `
                    <label class="wgs-checkbox-option ${isOwner ? "wgs-checkbox-owner" : ""}">
                        <input type="checkbox" data-field="edit_participant_toggle" value="${escapeHtml(String(rowId))}" ${selected ? "checked" : ""} ${isOwner ? "disabled" : ""} />
                        <span>${escapeHtml(row.name || "-")}${isOwner ? ` ${escapeHtml(_t("(Titular)"))}` : ""}</span>
                    </label>
                `;
            }).join("")
        : "";
    return `
        <div class="wgs-inline-form-card">
            <div class="wgs-inline-form-header">
                <strong>${escapeHtml(_t("Editar participantes"))}</strong>
                <button type="button" class="wgs-inline-close-btn" data-action="cancel-participants">${escapeHtml(_t("Cancelar"))}</button>
            </div>
            ${formError ? `<div class="wgs-inline-error">${escapeHtml(formError)}</div>` : ""}
            ${formNotice ? `<div class="wgs-inline-notice">${escapeHtml(formNotice)}</div>` : ""}
            <div class="wgs-inline-form-meta">
                <div><span>${escapeHtml(_t("Suscripción"))}</span><strong>${escapeHtml(participantEditForm.subscriptionName || "-")}</strong></div>
                <div><span>${escapeHtml(_t("Titular"))}</span><strong>${escapeHtml(participantEditForm.holderPartnerName || "-")}</strong></div>
                <div><span>${escapeHtml(_t("Cupo total"))}</span><strong>${escapeHtml(String(participantEditForm.maxParticipantsTotal || 1))}</strong></div>
                <div><span>${escapeHtml(_t("Seleccionados"))}</span><strong>${escapeHtml(String((participantEditForm.participantIds || []).length || 0))}</strong></div>
            </div>
            ${Number(participantEditForm.maxParticipantsTotal || 1) > 1 ? `
                <div class="wgs-inline-participants">
                    <span class="wgs-inline-section-title">${escapeHtml(_t("Participantes permitidos"))}</span>
                    <input type="text" class="wgs-inline-search" data-field="edit_participant_search" placeholder="${escapeHtml(_t("Buscar participante"))}" value="${escapeHtml(participantEditForm.participantSearch || "")}" />
                    <div class="wgs-inline-participant-list">${participantOptions}</div>
                </div>
            ` : `
                <div class="wgs-inline-notice">${escapeHtml(_t("Este paquete solo permite al titular. No hay participantes adicionales configurables."))}</div>
            `}
            <div class="wgs-inline-actions">
                <button type="button" class="wgs-primary-action-btn" data-action="save-participants">${escapeHtml(_t("Guardar participantes"))}</button>
                <button type="button" class="wgs-secondary-action-btn" data-action="cancel-participants">${escapeHtml(_t("Cancelar"))}</button>
            </div>
        </div>
    `;
}

export { renderParticipantEditForm };
