/** @odoo-module **/

function renderSubscriptionCards(detail, {
    renderSubscriptionCard,
    renderPendingDocumentSummary,
    renderParticipantEditForm,
    renderPendingChargeForm,
    renderCancellationRefundForm,
    renderRenewalForm,
    renderUpsaleForm,
    getStateClass,
    escapeHtml,
    formatDateDisplay,
    formatMoney,
    _t,
}) {
    const subscriptions = Array.isArray(detail.items) ? detail.items : [];
    if (!subscriptions.length) {
        return `
            <div class="wgs-detail-empty wgs-detail-empty-inline">
                <strong>${escapeHtml(_t("Sin suscripciones relacionadas"))}</strong>
                <p>${escapeHtml(_t("Este cliente no tiene suscripciones nativas vigentes o historicas visibles para POS."))}</p>
            </div>
        `;
    }

    return subscriptions.map((item) => {
        const stateClass = getStateClass(item.native_state_key);
        const nativeStateKey = String(item.native_state_key || "").toLowerCase();
        const canOperateSubscription = Boolean(
            item.subscription_id
            && (item.access_state === "enabled" || ["progress", "renew"].includes(nativeStateKey))
        );
        const participantNames = (item.participant_names || []).length
            ? item.participant_names.map((name) => escapeHtml(name)).join(", ")
            : escapeHtml(_t("Sin participantes"));
        const accessSummary = item.access_people_summary || {};
        const accessSiteLabel = (accessSummary.site_names || []).length
            ? escapeHtml((accessSummary.site_names || []).join(", "))
            : escapeHtml(_t("Sin sitios"));
        const pendingDocumentHtml = renderPendingDocumentSummary({
            item,
            escapeHtml,
            formatMoney,
            _t,
        });
        const inlineFormsHtml = [
            renderParticipantEditForm(item),
            renderPendingChargeForm(item),
            renderCancellationRefundForm(item),
            renderRenewalForm(item),
            renderUpsaleForm(item),
        ].join("");
        return renderSubscriptionCard({
            item,
            canOperateSubscription,
            stateClass,
            participantNames,
            accessSummary,
            accessSiteLabel,
            pendingDocumentHtml,
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
    renderPendingDocumentSummary,
    renderParticipantEditForm,
    renderPendingChargeForm,
    renderCancellationRefundForm,
    renderRenewalForm,
    renderUpsaleForm,
    renderNewSubscriptionForm,
    getStateClass,
    formMode,
    partnerPhotoForm,
    formError,
    formNotice,
    escapeHtml,
    formatDateDisplay,
    formatDateTimeDisplay,
    formatMoney,
    _t,
}) {
    const summaryStateClass = getStateClass(detail.state);
    const isEditingPartnerPhoto = formMode === "partner_photo"
        && partnerPhotoForm
        && Number(partnerPhotoForm.partnerId || 0) === Number(detail.partner_id || 0);
    const detailAvatarHtml = renderPartnerDetailAvatar({
        detail,
        partnerPhotoForm,
        isEditingPartnerPhoto,
        formError,
        formNotice,
        escapeHtml,
        _t,
    });
    const subscriptionsHtml = renderSubscriptionCards(detail, {
        renderSubscriptionCard,
        renderPendingDocumentSummary,
        renderParticipantEditForm,
        renderPendingChargeForm,
        renderCancellationRefundForm,
        renderRenewalForm,
        renderUpsaleForm,
        getStateClass,
        escapeHtml,
        formatDateDisplay,
        formatMoney,
        _t,
    });

    return `
        ${renderDetailHeader({
            detail,
            isEditingPartnerPhoto,
            detailAvatarHtml,
            summaryStateClass,
            escapeHtml,
            formatDateDisplay,
            formatDateTimeDisplay,
            _t,
        })}
        <div class="wgs-detail-actions-bar">
            <button type="button" class="wgs-primary-action-btn" data-action="open-new">${escapeHtml(_t("Nueva suscripcion"))}</button>
        </div>
        ${renderNewSubscriptionForm()}
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
