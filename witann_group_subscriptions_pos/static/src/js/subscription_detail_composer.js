/** @odoo-module **/

import { canOpenNewSubscription } from "./subscription_view_utils";

function renderSubscriptionCards(detail, {
    renderSubscriptionCard,
    renderParticipantEditForm,
    renderRenewalForm,
    renderUpsaleForm,
    renderNewSubscriptionForm,
    getStateClass,
    allowNewSubscription,
    escapeHtml,
    formatDateDisplay,
    formatMoney,
    _t,
}) {
    const subscriptions = Array.isArray(detail.items) ? detail.items : [];
    if (!subscriptions.length) {
        const hasAccessOrigin = Boolean(detail.access_origin_message);
        const accessOriginNoticeHtml = detail.access_origin_message ? `
                <div class="wgs-access-origin-notice">
                    <strong>${escapeHtml(detail.access_origin_label || _t("Acceso multisede"))}</strong>
                    <span>${escapeHtml(detail.access_origin_message)}</span>
                </div>
        ` : "";
        return `
            <div class="wgs-subscription-card wgs-subscription-card-empty">
                <div class="wgs-subscription-card-header">
                    <div>
                        <strong>${escapeHtml(hasAccessOrigin ? _t("Acceso por otra sede") : _t("Sin suscripciones relacionadas"))}</strong>
                        <div class="wgs-subscription-card-meta">${escapeHtml(hasAccessOrigin ? _t("Membresia administrada en la sede de origen") : _t("Sin historial visible para POS"))}</div>
                    </div>
                </div>
                <div class="wgs-detail-empty wgs-detail-empty-inline">
                    <p>${escapeHtml(hasAccessOrigin
                        ? _t("Este POS solo muestra el origen del acceso; renovaciones y cambios se operan en la sede que vendio la membresia.")
                        : _t("Este cliente no tiene suscripciones nativas vigentes o historicas visibles para POS.")
                    )}</p>
                </div>
                ${accessOriginNoticeHtml}
                <div class="wgs-subscription-actions">
                    ${allowNewSubscription
                        ? `<button type="button" class="wgs-action-btn wgs-primary-action-btn" data-action="open-new">${escapeHtml(_t("Nueva suscripcion"))}</button>`
                        : ""
                    }
                </div>
                ${renderNewSubscriptionForm()}
            </div>
        `;
    }

    return subscriptions.map((item) => {
        const stateClass = getStateClass(item.native_state_key);
        const participantNames = (item.participant_names || []).length
            ? item.participant_names.map((name) => escapeHtml(name)).join(", ")
            : escapeHtml(_t("Sin participantes"));
        const accessSummary = item.access_people_summary || {};
        const accessSiteLabel = (accessSummary.site_names || []).length
            ? escapeHtml((accessSummary.site_names || []).join(", "))
            : escapeHtml(_t("Sin sitios"));
        const inlineFormsHtml = [
            renderParticipantEditForm(item),
            renderRenewalForm(item),
            renderUpsaleForm(item),
        ].join("");
        return renderSubscriptionCard({
            item,
            stateClass,
            participantNames,
            accessSummary,
            accessSiteLabel,
            inlineFormsHtml,
            escapeHtml,
            formatDateDisplay,
            formatMoney,
            _t,
        });
    }).join("");
}

function renderDetailContent(detail, {
    renderDetailHeader,
    renderPartnerDetailAvatar,
    renderSubscriptionCard,
    renderParticipantEditForm,
    renderRenewalForm,
    renderUpsaleForm,
    renderNewSubscriptionForm,
    getStateClass,
    formMode,
    partnerPhotoForm,
    partnerEditForm,
    formError,
    formNotice,
    escapeHtml,
    formatDateDisplay,
    formatDateTimeDisplay,
    formatMoney,
    _t,
}) {
    const isEditingPartnerPhoto = formMode === "partner_photo"
        && partnerPhotoForm
        && Number(partnerPhotoForm.partnerId || 0) === Number(detail.partner_id || 0);
    const isEditingPartnerInfo = formMode === "partner_edit"
        && partnerEditForm
        && Number(partnerEditForm.partnerId || 0) === Number(detail.partner_id || 0);
    const detailAvatarHtml = renderPartnerDetailAvatar({
        detail,
        partnerPhotoForm,
        isEditingPartnerPhoto,
        formError,
        formNotice,
        escapeHtml,
        _t,
    });
    const allowNewSubscription = canOpenNewSubscription(detail);
    const subscriptionsHtml = renderSubscriptionCards(detail, {
        renderSubscriptionCard,
        renderParticipantEditForm,
        renderRenewalForm,
        renderUpsaleForm,
        renderNewSubscriptionForm,
        getStateClass,
        allowNewSubscription,
        escapeHtml,
        formatDateDisplay,
        formatMoney,
        _t,
    });
    const feedbackHtml = `
        ${formError ? `<div class="wgs-inline-error wgs-inline-error-compact">${escapeHtml(formError)}</div>` : ""}
        ${formNotice ? `<div class="wgs-inline-notice wgs-inline-notice-compact">${escapeHtml(formNotice)}</div>` : ""}
    `;

    return `
        ${renderDetailHeader({
            detail,
            isEditingPartnerPhoto,
            isEditingPartnerInfo,
            partnerEditForm,
            detailAvatarHtml,
            formError,
            formNotice,
            escapeHtml,
            formatDateDisplay,
            formatDateTimeDisplay,
            _t,
        })}
        ${feedbackHtml}
        <div class="wgs-detail-note">${escapeHtml(_t("Renovación, upsale, cobro pendiente y participantes se operan desde cada tarjeta de suscripción."))}</div>
        <div class="wgs-detail-section">
            <div class="wgs-detail-section-title">${escapeHtml(_t("Suscripciones del cliente"))}</div>
            <div class="wgs-subscription-cards">${subscriptionsHtml}</div>
        </div>
    `;
}

export {
    renderDetailContent,
};
