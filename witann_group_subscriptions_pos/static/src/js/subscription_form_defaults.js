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
        requiresCurp: false,
        studentAgeLock: false,
        curp: "",
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
        curp: "",
        gender: "",
        birthday: "",
        imageDataUrl: "",
        imageBase64: "",
        cameraActive: false,
    };
}

export function getDefaultExistingPartnerForm(detail = null) {
    return {
        partnerId: Number(detail && detail.partner_id ? detail.partner_id : 0) || false,
        name: detail && detail.partner_name ? detail.partner_name : "",
        phone: detail && detail.phone ? detail.phone : "",
        email: detail && detail.email ? detail.email : "",
        curp: detail && detail.curp ? detail.curp : "",
        gender: detail && detail.gender ? detail.gender : "",
        birthday: detail && detail.birthday ? detail.birthday : "",
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
