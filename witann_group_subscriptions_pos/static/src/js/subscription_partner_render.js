/** @odoo-module **/

function renderPartnerDetailAvatar({
    detail,
    partnerPhotoForm,
    isEditingPartnerPhoto,
    formError,
    formNotice,
    escapeHtml,
    _t,
}) {
    if (isEditingPartnerPhoto) {
        return `
            <div class="wgs-detail-avatar-stack wgs-detail-avatar-stack-editing">
                <div class="wgs-detail-avatar-editor">
                    ${partnerPhotoForm.cameraActive
                        ? `<video class="wgs-camera-preview" data-role="partner-camera-preview" autoplay playsinline muted></video>`
                        : partnerPhotoForm.imageDataUrl
                        ? `<img class="wgs-detail-avatar" src="${escapeHtml(partnerPhotoForm.imageDataUrl)}" alt="${escapeHtml(_t("Foto del cliente"))}" loading="lazy" />`
                        : `<div class="wgs-new-partner-empty-photo">${escapeHtml(_t("Sin foto"))}</div>`
                    }
                </div>
                ${formError ? `<div class="wgs-inline-error wgs-inline-error-compact">${escapeHtml(formError)}</div>` : ""}
                ${formNotice ? `<div class="wgs-inline-notice wgs-inline-notice-compact">${escapeHtml(formNotice)}</div>` : ""}
                <div class="wgs-inline-actions wgs-photo-actions-grid wgs-detail-photo-actions">
                    <label class="wgs-secondary-action-btn wgs-file-action-btn">
                        <span>${escapeHtml(_t("Subir foto"))}</span>
                        <input type="file" accept="image/*" data-field="existing_partner_image_file" hidden />
                    </label>
                    ${!partnerPhotoForm.cameraActive
                        ? `<button type="button" class="wgs-secondary-action-btn" data-action="start-existing-partner-camera">${escapeHtml(_t("Usar cámara"))}</button>`
                        : `
                            <button type="button" class="wgs-primary-action-btn" data-action="capture-existing-partner-camera">${escapeHtml(_t("Capturar"))}</button>
                            <button type="button" class="wgs-secondary-action-btn" data-action="stop-existing-partner-camera">${escapeHtml(_t("Apagar cámara"))}</button>
                        `
                    }
                    <button type="button" class="wgs-primary-action-btn" data-action="save-partner-photo">${escapeHtml(_t("Guardar foto"))}</button>
                    <button type="button" class="wgs-secondary-action-btn" data-action="cancel-partner-photo">${escapeHtml(_t("Cancelar"))}</button>
                </div>
            </div>
        `;
    }

    return `
        <div class="wgs-detail-avatar-stack">
            <img class="wgs-detail-avatar" src="${escapeHtml(detail.image_url || "")}" alt="${escapeHtml(detail.partner_name || "")}" loading="lazy" />
            <button type="button" class="wgs-secondary-action-btn wgs-avatar-edit-btn" data-action="open-partner-photo">${escapeHtml(_t("Editar foto"))}</button>
        </div>
    `;
}

export { renderPartnerDetailAvatar };
