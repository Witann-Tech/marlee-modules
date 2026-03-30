/** @odoo-module **/

function getEmptyCharge(buildChargeBreakdown) {
    return buildChargeBreakdown(null, null, { baseAmount: 0, displayAmount: 0 });
}

function getNormalizedParticipantIds(item, holderPartnerId = false) {
    const participantIds = Array.isArray(item && item.participant_ids)
        ? [...new Set(item.participant_ids.map((value) => Number(value || 0)).filter((value) => value > 0))]
        : [];
    if (holderPartnerId && !participantIds.includes(holderPartnerId)) {
        participantIds.unshift(holderPartnerId);
    }
    return participantIds;
}

export function getDefaultNewSubscriptionForm(partnerId, { buildChargeBreakdown, formatTodayISO }) {
    const participantIds = [];
    if (partnerId) {
        participantIds.push(Number(partnerId));
    }
    return {
        productId: 0,
        productName: "",
        planChoice: "",
        plans: [],
        charge: getEmptyCharge(buildChargeBreakdown),
        startDate: formatTodayISO(),
        maxParticipantsTotal: 1,
        participantIds,
        participantSearch: "",
        loading: false,
    };
}

export function getDefaultNewPartnerForm() {
    return {
        name: "",
        phone: "",
        email: "",
        gender: "",
        birthday: "",
        imageDataUrl: "",
        imageBase64: "",
        cameraActive: false,
    };
}

export function getDefaultUpsaleForm(item = null, { buildChargeBreakdown }) {
    const subscriptionId = Number(item && item.subscription_id ? item.subscription_id : 0) || false;
    const holderPartnerId = Number(item && item.holder_partner_id ? item.holder_partner_id : 0) || false;
    return {
        subscriptionId,
        subscriptionName: item && item.subscription_name ? item.subscription_name : "",
        holderPartnerId,
        holderPartnerName: item && item.holder_partner_name ? item.holder_partner_name : "",
        sourceProductId: Number(item && item.renewal_product_id ? item.renewal_product_id : 0) || false,
        sourceProductName: item && item.renewal_product_name ? item.renewal_product_name : "",
        sourcePlanName: item && item.plan_name ? item.plan_name : "",
        productId: 0,
        productName: "",
        planChoice: "",
        plans: [],
        recurringCharge: getEmptyCharge(buildChargeBreakdown),
        creditCharge: getEmptyCharge(buildChargeBreakdown),
        charge: getEmptyCharge(buildChargeBreakdown),
        maxParticipantsTotal: 1,
        participantIds: getNormalizedParticipantIds(item, holderPartnerId),
        participantSearch: "",
        loading: false,
    };
}

export function getDefaultParticipantEditForm(item = null) {
    const subscriptionId = Number(item && item.subscription_id ? item.subscription_id : 0) || false;
    const holderPartnerId = Number(item && item.holder_partner_id ? item.holder_partner_id : 0) || false;
    return {
        subscriptionId,
        subscriptionName: item && item.subscription_name ? item.subscription_name : "",
        holderPartnerId,
        holderPartnerName: item && item.holder_partner_name ? item.holder_partner_name : "",
        participantIds: getNormalizedParticipantIds(item, holderPartnerId),
        maxParticipantsTotal: Number(item && item.max_participants_total ? item.max_participants_total : 1),
        participantSearch: "",
    };
}
