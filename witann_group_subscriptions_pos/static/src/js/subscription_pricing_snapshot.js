/** @odoo-module **/

function buildPricingSnapshotFromCharge(charge, {
    flow = "new",
    sourceSubscriptionId = false,
    sourceSubscriptionName = false,
} = {}) {
    return {
        flow,
        plan_id: Number(charge && charge.plan_id !== undefined ? charge.plan_id : 0) || false,
        plan_name: charge && charge.plan_name ? charge.plan_name : "",
        pricing_id: Number(charge && charge.pricing_id !== undefined ? charge.pricing_id : 0) || false,
        interval_value: Number(
            charge && charge.interval_value !== undefined
                ? charge.interval_value
                : 1
        ) || 1,
        interval_unit: charge && charge.interval_unit
            ? charge.interval_unit
            : "month",
        interval_label: charge && charge.interval_label !== undefined
            ? charge.interval_label
            : "",
        recurring_price: Number(charge && charge.recurring_price ? charge.recurring_price : 0) || 0,
        ticket_recurring_price: Number(
            charge && charge.ticket_recurring_price !== undefined
                ? charge.ticket_recurring_price
                : (charge && charge.recurring_price ? charge.recurring_price : 0)
        ) || 0,
        display_recurring_price: Number(
            charge && charge.display_recurring_price !== undefined
                ? charge.display_recurring_price
                : (charge && charge.recurring_price ? charge.recurring_price : 0)
        ) || 0,
        charge_now: Number(charge && charge.charge_now ? charge.charge_now : 0) || 0,
        ticket_charge_now: Number(
            charge && charge.ticket_charge_now !== undefined
                ? charge.ticket_charge_now
                : (charge && charge.charge_now ? charge.charge_now : 0)
        ) || 0,
        display_charge_now: Number(
            charge && charge.display_charge_now !== undefined
                ? charge.display_charge_now
                : (charge && charge.charge_now ? charge.charge_now : 0)
        ) || 0,
        credit_amount: Number(charge && charge.credit_amount ? charge.credit_amount : 0) || 0,
        ticket_credit_amount: Number(
            charge && charge.ticket_credit_amount !== undefined
                ? charge.ticket_credit_amount
                : (charge && charge.credit_amount ? charge.credit_amount : 0)
        ) || 0,
        display_credit_amount: Number(
            charge && charge.display_credit_amount !== undefined
                ? charge.display_credit_amount
                : (charge && charge.credit_amount ? charge.credit_amount : 0)
        ) || 0,
        amount_total: Number(charge && charge.amount_total ? charge.amount_total : 0) || 0,
        ticket_amount_total: Number(
            charge && charge.ticket_amount_total !== undefined
                ? charge.ticket_amount_total
                : (charge && charge.amount_total ? charge.amount_total : 0)
        ) || 0,
        display_amount_total: Number(
            charge && charge.display_amount_total !== undefined
                ? charge.display_amount_total
                : (charge && charge.amount_total ? charge.amount_total : 0)
        ) || 0,
        source_subscription_id: Number(
            charge && charge.source_subscription_id !== undefined
                ? charge.source_subscription_id
                : sourceSubscriptionId
        ) || false,
        source_subscription_name: charge && charge.source_subscription_name
            ? charge.source_subscription_name
            : (sourceSubscriptionName || false),
    };
}

function getPricingSnapshot(form) {
    return form && form.pricingSnapshot && typeof form.pricingSnapshot === "object"
        ? form.pricingSnapshot
        : {};
}

function buildChargeFromSnapshot(formOrSnapshot, chargeType = "recurring") {
    const snapshot = formOrSnapshot && formOrSnapshot.pricingSnapshot !== undefined
        ? getPricingSnapshot(formOrSnapshot)
        : (formOrSnapshot || {});
    const fieldsByType = {
        recurring: {
            base: "recurring_price",
            ticket: "ticket_recurring_price",
            display: "display_recurring_price",
        },
        charge_now: {
            base: "charge_now",
            ticket: "ticket_charge_now",
            display: "display_charge_now",
        },
        credit: {
            base: "credit_amount",
            ticket: "ticket_credit_amount",
            display: "display_credit_amount",
        },
        amount_total: {
            base: "amount_total",
            ticket: "ticket_amount_total",
            display: "display_amount_total",
        },
    };
    const fields = fieldsByType[chargeType] || fieldsByType.recurring;
    return {
        baseAmount: Number(snapshot[fields.base] || 0) || 0,
        ticketUnitPrice: Number(snapshot[fields.ticket] || 0) || 0,
        displayAmount: Number(snapshot[fields.display] || 0) || 0,
    };
}

function getPlanChoiceFromSnapshot(snapshot) {
    const planId = Number(snapshot && snapshot.plan_id ? snapshot.plan_id : 0);
    const pricingId = Number(snapshot && snapshot.pricing_id ? snapshot.pricing_id : 0);
    if (!planId && !pricingId) {
        return "";
    }
    return `${planId}:${pricingId}`;
}

function getCurrentPlanChoice(form) {
    return getPlanChoiceFromSnapshot(getPricingSnapshot(form));
}

export {
    buildChargeFromSnapshot,
    buildPricingSnapshotFromCharge,
    getCurrentPlanChoice,
    getPricingSnapshot,
};
