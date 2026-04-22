/** @odoo-module **/

function clampParticipantIds(participantIds, ownerId, maxTotal) {
    const numericOwnerId = Number(ownerId || 0) || false;
    const limit = Math.max(1, Number(maxTotal || 1));
    const cleaned = [...new Set((participantIds || []).map((value) => Number(value || 0)).filter((value) => value > 0))];
    const withoutOwner = cleaned.filter((value) => value !== numericOwnerId);
    const result = [];
    if (numericOwnerId) {
        result.push(numericOwnerId);
    }
    for (const partnerId of withoutOwner) {
        if (result.length >= limit) {
            break;
        }
        result.push(partnerId);
    }
    return result;
}

function filterParticipantRows(rows, searchTerm = "") {
    const query = String(searchTerm || "").trim().toLowerCase();
    const sourceRows = rows
        .slice()
        .sort((a, b) => (a.name || "").localeCompare(b.name || "", "es"));
    if (!query) {
        return sourceRows;
    }
    return sourceRows.filter((row) => {
        const haystack = `${row.name || ""} ${row.phone || ""} ${row.email || ""}`.toLowerCase();
        return haystack.includes(query);
    });
}

async function openNewSubscriptionForm(state, {
    stopPartnerCamera,
    createNewSubscriptionForm,
    renderDetail,
    loadDetail,
    fetchSubscriptionProductCatalog,
    _t,
}) {
    if (!state.selectedPartnerId) {
        return;
    }
    state.formMode = "new";
    state.formError = "";
    state.formNotice = "";
    stopPartnerCamera();
    state.renewalForm = null;
    state.upsaleForm = null;
    state.pendingChargeForm = null;
    state.cancellationRefundForm = null;
    state.participantEditForm = null;
    state.newPartnerForm = null;
    state.partnerPhotoForm = null;
    state.newSubscriptionForm = createNewSubscriptionForm(state.selectedPartnerId);
    renderDetail(state.currentDetail);
    if (loadDetail) {
        await loadDetail(state.selectedPartnerId, { force: true });
    }
    if (state.productCatalog.length || state.catalogLoading) {
        return;
    }
    state.catalogLoading = true;
    renderDetail(state.currentDetail);
    try {
        state.productCatalog = await fetchSubscriptionProductCatalog("");
        if (!Array.isArray(state.productCatalog)) {
            state.productCatalog = [];
        }
        if (!state.productCatalog.length) {
            state.formError = _t("No hay productos de suscripción cargados en esta sesión del POS.");
        }
    } catch (error) {
        console.error("Error al consultar catalogo de suscripciones en POS", error);
        state.formError = _t("No se pudo cargar el catalogo de productos de suscripcion.");
    } finally {
        state.catalogLoading = false;
        renderDetail(state.currentDetail);
    }
}

async function openRenewalForm(state, item, {
    stopPartnerCamera,
    renderDetail,
    buildChargeBreakdown,
    fetchSubscriptionPricing,
    fetchSubscriptionDiscountOffers,
    mode = "renewal",
    title = false,
    submitLabel = false,
    _t,
}) {
    if (!item || !item.subscription_id) {
        return;
    }
    state.formMode = mode;
    state.formError = "";
    state.formNotice = "";
    stopPartnerCamera();
    state.newPartnerForm = null;
    state.pendingChargeForm = null;
    state.cancellationRefundForm = null;
    state.participantEditForm = null;
    state.renewalForm = {
        subscriptionId: Number(item.subscription_id || 0) || false,
        subscriptionName: item.subscription_name || "",
        holderPartnerId: Number(item.holder_partner_id || 0) || false,
        holderPartnerName: item.holder_partner_name || "",
        productId: Number(item.renewal_product_id || 0) || false,
        productName: item.renewal_product_name || "",
        planId: Number(item.renewal_plan_id || 0) || false,
        pricingId: Number(item.renewal_pricing_id || 0) || false,
        participantIds: Array.isArray(item.participant_ids) ? [...item.participant_ids] : [],
        title: title || (mode === "reenroll" ? _t("Reinscribir suscripción") : _t("Renovar suscripción")),
        submitLabel: submitLabel || (mode === "reenroll" ? _t("Agregar reinscripción al ticket") : _t("Agregar al ticket")),
        isReenroll: mode === "reenroll",
        startDate: mode === "reenroll" ? new Date().toISOString().slice(0, 10) : false,
        charge: buildChargeBreakdown(null, null, { baseAmount: 0, displayAmount: 0 }),
        pricingSnapshot: null,
        discountOffers: [],
        selectedDiscountCode: "",
        supervisorPin: "",
        authorizedDiscount: null,
        nextInvoiceDate: item.next_invoice_date || false,
        loading: true,
    };
    renderDetail(state.currentDetail);
    try {
        const flow = mode === "reenroll" ? "reenroll" : "renewal";
        const charge = await fetchSubscriptionPricing(
            state.renewalForm.holderPartnerId || false,
            state.renewalForm.productId || false,
            flow,
            state.renewalForm.subscriptionId,
            false,
            0,
            state.renewalForm.planId,
            state.renewalForm.pricingId
        );
        state.renewalForm = {
            ...state.renewalForm,
            loading: false,
            pricingSnapshot: buildPricingSnapshotFromCharge(charge, {
                flow,
                fallbackPlanId: state.renewalForm.planId,
                fallbackPricingId: state.renewalForm.pricingId,
                sourceSubscriptionId: state.renewalForm.subscriptionId,
                sourceSubscriptionName: state.renewalForm.subscriptionName,
            }),
            charge: buildChargeBreakdown(null, null, {
                baseAmount: Number(charge && charge.charge_now ? charge.charge_now : 0),
                ticketUnitPrice: Number(
                    charge && charge.ticket_charge_now !== undefined
                        ? charge.ticket_charge_now
                        : (charge && charge.charge_now ? charge.charge_now : 0)
                ),
                displayAmount: Number(
                    charge && charge.display_charge_now !== undefined
                        ? charge.display_charge_now
                        : (charge && charge.charge_now ? charge.charge_now : 0)
                ),
            }),
            planId: Number(charge && charge.plan_id ? charge.plan_id : state.renewalForm.planId) || false,
            pricingId: Number(charge && charge.pricing_id ? charge.pricing_id : state.renewalForm.pricingId) || false,
        };
        if (fetchSubscriptionDiscountOffers) {
            state.renewalForm.discountOffers = await fetchSubscriptionDiscountOffers(
                state.renewalForm.holderPartnerId,
                state.renewalForm.productId,
                mode === "reenroll" ? "reenroll" : "renewal",
                state.renewalForm.subscriptionId
            );
            if (state.renewalForm.discountOffers.length === 1) {
                const [onlyOffer] = state.renewalForm.discountOffers;
                if (!Number(onlyOffer.discount_percent || 0) && !Number(onlyOffer.discount_fixed_amount || 0)) {
                    state.renewalForm.selectedDiscountCode = String(onlyOffer.code || "");
                }
            }
        }
    } catch (error) {
        console.error("Error al consultar cobro de renovación POS", error);
        state.formError = _t("No se pudo consultar el cobro de renovación para esta suscripción.");
        state.renewalForm = {
            ...state.renewalForm,
            loading: false,
        };
    }
    renderDetail(state.currentDetail);
}

async function openReenrollForm(state, item, deps) {
    await openRenewalForm(state, item, {
        ...deps,
        mode: "reenroll",
    });
}

async function openPendingChargeForm(state, item, {
    stopPartnerCamera,
    renderDetail,
    buildChargeBreakdown,
    getChargeDisplayAmount,
    fetchSubscriptionPricing,
    _t,
}) {
    if (!item || !item.subscription_id) {
        return;
    }
    const pendingDocuments = Array.isArray(item.pending_documents) ? item.pending_documents : [];
    if (!pendingDocuments.length) {
        state.formError = _t("Esta suscripción no tiene documentos pendientes por cobrar.");
        renderDetail(state.currentDetail);
        return;
    }
    const firstPending = pendingDocuments[0];
    state.formMode = "pending";
    state.formError = "";
    state.formNotice = "";
    stopPartnerCamera();
    state.newPartnerForm = null;
    state.renewalForm = null;
    state.upsaleForm = null;
    state.pendingChargeForm = {
        subscriptionId: Number(item.subscription_id || 0) || false,
        subscriptionName: item.subscription_name || "",
        holderPartnerId: Number(item.holder_partner_id || 0) || false,
        holderPartnerName: item.holder_partner_name || "",
        productId: Number(item.renewal_product_id || 0) || false,
        productName: item.renewal_product_name || "",
        pendingMoveId: Number(firstPending.document_id || 0) || false,
        pendingMoveName: firstPending.name || "",
        invoiceDate: firstPending.invoice_date || false,
        invoiceDateDue: firstPending.invoice_date_due || false,
        pricingSnapshot: null,
        charge: buildChargeBreakdown(null, null, { baseAmount: 0, displayAmount: 0 }),
        totalCharge: buildChargeBreakdown(null, null, {
            baseAmount: Number(firstPending.amount_total || 0),
            displayAmount: Number(firstPending.amount_total || 0),
        }),
        loading: true,
    };
    renderDetail(state.currentDetail);
    try {
        const charge = await fetchSubscriptionPricing(
            state.pendingChargeForm.holderPartnerId || false,
            state.pendingChargeForm.productId || false,
            "pending_charge",
            state.pendingChargeForm.subscriptionId,
            state.pendingChargeForm.pendingMoveId,
            0,
            false,
            false
        );
        state.pendingChargeForm = {
            ...state.pendingChargeForm,
            loading: false,
            pricingSnapshot: buildPricingSnapshotFromCharge(charge, {
                flow: "pending_charge",
                sourceSubscriptionId: state.pendingChargeForm.subscriptionId,
                sourceSubscriptionName: state.pendingChargeForm.subscriptionName,
            }),
            pendingMoveId: Number(charge && charge.pending_move_id ? charge.pending_move_id : state.pendingChargeForm.pendingMoveId) || false,
            pendingMoveName: charge && charge.pending_move_name ? charge.pending_move_name : state.pendingChargeForm.pendingMoveName,
            invoiceDate: charge && charge.invoice_date ? charge.invoice_date : state.pendingChargeForm.invoiceDate,
            invoiceDateDue: charge && charge.invoice_date_due ? charge.invoice_date_due : state.pendingChargeForm.invoiceDateDue,
            charge: buildChargeBreakdown(null, null, {
                baseAmount: Number(charge && charge.charge_now ? charge.charge_now : 0),
                ticketUnitPrice: Number(
                    charge && charge.ticket_charge_now !== undefined
                        ? charge.ticket_charge_now
                        : (charge && charge.charge_now ? charge.charge_now : 0)
                ),
                displayAmount: Number(
                    charge && charge.display_charge_now !== undefined
                        ? charge.display_charge_now
                        : (charge && charge.charge_now ? charge.charge_now : 0)
                ),
            }),
            totalCharge: buildChargeBreakdown(null, null, {
                baseAmount: Number(charge && charge.amount_total ? charge.amount_total : getChargeDisplayAmount(state.pendingChargeForm.totalCharge) || 0),
                ticketUnitPrice: Number(
                    charge && charge.ticket_amount_total !== undefined
                        ? charge.ticket_amount_total
                        : (charge && charge.amount_total ? charge.amount_total : getChargeDisplayAmount(state.pendingChargeForm.totalCharge) || 0)
                ),
                displayAmount: Number(
                    charge && charge.display_amount_total !== undefined
                        ? charge.display_amount_total
                        : (charge && charge.amount_total ? charge.amount_total : getChargeDisplayAmount(state.pendingChargeForm.totalCharge) || 0)
                ),
            }),
        };
    } catch (error) {
        console.error("Error al consultar cobro pendiente POS", error);
        state.formError = _t("No se pudo consultar el documento pendiente para esta suscripción.");
        state.pendingChargeForm = {
            ...state.pendingChargeForm,
            loading: false,
        };
    }
    renderDetail(state.currentDetail);
}

async function openUpsaleForm(state, item, {
    stopPartnerCamera,
    renderDetail,
    createDefaultUpsaleForm,
    fetchSubscriptionProductCatalog,
    _t,
}) {
    if (!item || !item.subscription_id) {
        return;
    }
    state.formMode = "upsale";
    state.formError = "";
    state.formNotice = "";
    stopPartnerCamera();
    state.newPartnerForm = null;
    state.renewalForm = null;
    state.upsaleForm = createDefaultUpsaleForm(item);
    state.pendingChargeForm = null;
    state.cancellationRefundForm = null;
    state.participantEditForm = null;
    renderDetail(state.currentDetail);
    if (!state.productCatalog.length && !state.catalogLoading) {
        state.catalogLoading = true;
        renderDetail(state.currentDetail);
        try {
            state.productCatalog = await fetchSubscriptionProductCatalog("");
            if (!Array.isArray(state.productCatalog)) {
                state.productCatalog = [];
            }
            if (!state.productCatalog.length) {
                state.formError = _t("No hay productos de suscripción cargados en esta sesión del POS.");
            }
        } catch (error) {
            console.error("Error al consultar catalogo de upsale en POS", error);
            state.formError = _t("No se pudo cargar el catalogo de productos para upsale.");
        } finally {
            state.catalogLoading = false;
        }
    }
    renderDetail(state.currentDetail);
}

async function openParticipantEditForm(state, item, {
    stopPartnerCamera,
    renderDetail,
    createDefaultParticipantEditForm,
}) {
    if (!item || !item.subscription_id) {
        return;
    }
    state.formMode = "participants";
    state.formError = "";
    state.formNotice = "";
    stopPartnerCamera();
    state.newPartnerForm = null;
    state.renewalForm = null;
    state.upsaleForm = null;
    state.pendingChargeForm = null;
    state.participantEditForm = createDefaultParticipantEditForm(item);
    renderDetail(state.currentDetail);
}

function buildPricingSnapshotFromCharge(charge, {
    flow = "new",
    fallbackPlanId = false,
    fallbackPricingId = false,
    fallbackIntervalValue = 1,
    fallbackIntervalUnit = "month",
    fallbackIntervalLabel = "",
    sourceSubscriptionId = false,
    sourceSubscriptionName = false,
} = {}) {
    const resolvedPlanId = Number(
        charge && charge.plan_id !== undefined
            ? charge.plan_id
            : fallbackPlanId
    ) || false;
    const resolvedPricingId = Number(
        charge && charge.pricing_id !== undefined
            ? charge.pricing_id
            : fallbackPricingId
    ) || false;
    return {
        flow,
        plan_id: resolvedPlanId,
        plan_name: charge && charge.plan_name ? charge.plan_name : "",
        pricing_id: resolvedPricingId,
        interval_value: Number(
            charge && charge.interval_value !== undefined
                ? charge.interval_value
                : fallbackIntervalValue
        ) || 1,
        interval_unit: charge && charge.interval_unit
            ? charge.interval_unit
            : (fallbackIntervalUnit || "month"),
        interval_label: charge && charge.interval_label !== undefined
            ? charge.interval_label
            : (fallbackIntervalLabel || ""),
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

function mergeResolvedPlanChoice(plans, snapshot, fallbackPlan, fallbackLabel) {
    const resolvedPlanId = Number(snapshot && snapshot.plan_id ? snapshot.plan_id : 0);
    const resolvedPricingId = Number(snapshot && snapshot.pricing_id ? snapshot.pricing_id : 0);
    const currentPlans = Array.isArray(plans) ? plans : [];
    if (!resolvedPlanId && !resolvedPricingId) {
        return currentPlans;
    }
    let resolvedPlanFound = false;
    const updatedPlans = currentPlans.map((item) => {
        const samePlan = Number(item.plan_id || 0) === resolvedPlanId;
        const samePricing = Number(item.pricing_id || 0) === resolvedPricingId;
        const match = resolvedPricingId ? samePricing : samePlan;
        if (!match) {
            return item;
        }
        resolvedPlanFound = true;
        return {
            ...item,
            plan_name: snapshot && snapshot.plan_name
                ? snapshot.plan_name
                : (item.plan_name || item.name || fallbackLabel),
            price: Number(snapshot && snapshot.recurring_price ? snapshot.recurring_price : item.price || 0),
            display_price: Number(
                snapshot && snapshot.display_recurring_price !== undefined
                    ? snapshot.display_recurring_price
                    : (item.display_price || item.price || 0)
            ),
            interval_label: snapshot && snapshot.interval_label !== undefined
                ? snapshot.interval_label
                : (item.interval_label || ""),
            interval_value: Number(
                snapshot && snapshot.interval_value !== undefined
                    ? snapshot.interval_value
                    : (item.interval_value || 1)
            ),
            interval_unit: snapshot && snapshot.interval_unit
                ? snapshot.interval_unit
                : (item.interval_unit || "month"),
        };
    });
    if (resolvedPlanFound) {
        return updatedPlans;
    }
    return [
        ...updatedPlans,
        {
            plan_id: resolvedPlanId || false,
            plan_name: snapshot && snapshot.plan_name
                ? snapshot.plan_name
                : ((fallbackPlan && (fallbackPlan.plan_name || fallbackPlan.name)) || fallbackLabel),
            pricing_id: resolvedPricingId || false,
            price: Number(snapshot && snapshot.recurring_price ? snapshot.recurring_price : 0),
            display_price: Number(
                snapshot && snapshot.display_recurring_price !== undefined
                    ? snapshot.display_recurring_price
                    : 0
            ),
            interval_label: snapshot && snapshot.interval_label !== undefined
                ? snapshot.interval_label
                : ((fallbackPlan && fallbackPlan.interval_label) || ""),
            interval_value: Number(
                snapshot && snapshot.interval_value !== undefined
                    ? snapshot.interval_value
                    : ((fallbackPlan && fallbackPlan.interval_value) || 1)
            ),
            interval_unit: snapshot && snapshot.interval_unit
                ? snapshot.interval_unit
                : ((fallbackPlan && fallbackPlan.interval_unit) || "month"),
        },
    ];
}

function applyPricingPayloadToNewSubscriptionForm(state, payload, preferredPlan, {
    buildChargeBreakdown,
    _t,
}) {
    const snapshot = buildPricingSnapshotFromCharge(payload, {
        flow: "new",
        fallbackPlanId: preferredPlan ? preferredPlan.plan_id : false,
        fallbackPricingId: preferredPlan ? preferredPlan.pricing_id : false,
        fallbackIntervalValue: preferredPlan ? preferredPlan.interval_value : 1,
        fallbackIntervalUnit: preferredPlan ? preferredPlan.interval_unit : "month",
        fallbackIntervalLabel: preferredPlan ? preferredPlan.interval_label : "",
        sourceSubscriptionId: payload && payload.source_subscription_id ? payload.source_subscription_id : false,
        sourceSubscriptionName: payload && payload.source_subscription_name ? payload.source_subscription_name : false,
    });
    state.newSubscriptionForm.requiresCurp = Boolean(payload && (payload.requires_curp || payload.student_age_lock));
    state.newSubscriptionForm.studentAgeLock = Boolean(payload && payload.student_age_lock);
    state.newSubscriptionForm.maxParticipantsTotal = Number(payload && payload.max_participants_total ? payload.max_participants_total : 1) || 1;
    state.newSubscriptionForm.plans = mergeResolvedPlanChoice(
        payload && Array.isArray(payload.plans) ? payload.plans : [],
        snapshot,
        preferredPlan,
        _t("Plan recurrente")
    );
    state.newSubscriptionForm.pricingSnapshot = snapshot;
    state.newSubscriptionForm.charge = buildChargeBreakdown(null, null, {
        baseAmount: Number(snapshot.recurring_price || 0),
        ticketUnitPrice: Number(snapshot.ticket_recurring_price || 0),
        displayAmount: Number(snapshot.display_recurring_price || 0),
    });
    if (snapshot.plan_id || snapshot.pricing_id) {
        state.newSubscriptionForm.planChoice = `${Number(snapshot.plan_id || 0)}:${Number(snapshot.pricing_id || 0)}`;
    }
}

function applyPricingPayloadToUpsaleForm(state, payload, preferredPlan, {
    buildChargeBreakdown,
    _t,
}) {
    const snapshot = buildPricingSnapshotFromCharge(payload, {
        flow: "upsale",
        fallbackPlanId: preferredPlan ? preferredPlan.plan_id : false,
        fallbackPricingId: preferredPlan ? preferredPlan.pricing_id : false,
        fallbackIntervalValue: preferredPlan ? preferredPlan.interval_value : 1,
        fallbackIntervalUnit: preferredPlan ? preferredPlan.interval_unit : "month",
        fallbackIntervalLabel: preferredPlan ? preferredPlan.interval_label : "",
        sourceSubscriptionId: state.upsaleForm.subscriptionId,
        sourceSubscriptionName: state.upsaleForm.subscriptionName,
    });
    state.upsaleForm.maxParticipantsTotal = Number(payload && payload.max_participants_total ? payload.max_participants_total : 1) || 1;
    state.upsaleForm.plans = mergeResolvedPlanChoice(
        payload && Array.isArray(payload.plans) ? payload.plans : [],
        snapshot,
        preferredPlan,
        _t("Plan recurrente")
    );
    state.upsaleForm.pricingSnapshot = snapshot;
    state.upsaleForm.recurringCharge = buildChargeBreakdown(null, null, {
        baseAmount: Number(snapshot.recurring_price || 0),
        ticketUnitPrice: Number(snapshot.ticket_recurring_price || 0),
        displayAmount: Number(snapshot.display_recurring_price || 0),
    });
    state.upsaleForm.creditCharge = buildChargeBreakdown(null, null, {
        baseAmount: Number(snapshot.credit_amount || 0),
        ticketUnitPrice: Number(snapshot.ticket_credit_amount || 0),
        displayAmount: Number(snapshot.display_credit_amount || 0),
    });
    state.upsaleForm.charge = buildChargeBreakdown(null, null, {
        baseAmount: Number(snapshot.charge_now || 0),
        ticketUnitPrice: Number(snapshot.ticket_charge_now || 0),
        displayAmount: Number(snapshot.display_charge_now || 0),
    });
    state.upsaleForm.planChoice = `${Number(snapshot.plan_id || 0)}:${Number(snapshot.pricing_id || 0)}`;
}

async function recalculateNewSubscriptionCharge(state, product, preferredPlan, {
    renderDetail,
    fetchSubscriptionPricing,
    buildChargeBreakdown,
    _t,
}) {
    if (!state.newSubscriptionForm || !product || !state.selectedPartnerId) {
        return;
    }
    state.newSubscriptionForm.loading = true;
    renderDetail(state.currentDetail);
    try {
        const payload = await fetchSubscriptionPricing(
            state.selectedPartnerId,
            Number(product.id || 0),
            "new",
            false,
            false,
            Number(preferredPlan && preferredPlan.price ? preferredPlan.price : product.default_price || 0),
            preferredPlan ? Number(preferredPlan.plan_id || 0) || false : false,
            preferredPlan ? Number(preferredPlan.pricing_id || 0) || false : false
        );
        applyPricingPayloadToNewSubscriptionForm(state, payload, preferredPlan, {
            buildChargeBreakdown,
            _t,
        });
    } catch (error) {
        console.error("Error al recalcular cobro de suscripción POS", error);
        state.formError = _t("No se pudo recalcular el precio de la suscripción.");
    } finally {
        state.newSubscriptionForm.loading = false;
        renderDetail(state.currentDetail);
    }
}

async function applySelectedProduct(state, productId, {
    renderDetail,
    recalculateNewSubscriptionCharge,
    fetchSubscriptionDiscountOffers,
}) {
    const numericProductId = Number(productId || 0);
    const product = state.productCatalog.find((item) => Number(item.id) === numericProductId) || null;
    state.newSubscriptionForm.productId = numericProductId;
    state.newSubscriptionForm.productName = product ? product.name || "" : "";
    state.newSubscriptionForm.requiresCurp = Boolean(product && (product.requires_curp || product.student_age_lock));
    state.newSubscriptionForm.studentAgeLock = Boolean(product && product.student_age_lock);
    state.newSubscriptionForm.maxParticipantsTotal = product ? Number(product.max_participants_total || 1) : 1;
    state.newSubscriptionForm.plans = [];
    state.newSubscriptionForm.pricingSnapshot = null;
    state.newSubscriptionForm.planChoice = "";
    state.newSubscriptionForm.charge = {
        baseAmount: 0,
        displayAmount: 0,
        ticketUnitPrice: 0,
    };
    state.newSubscriptionForm.discountOffers = [];
    state.newSubscriptionForm.selectedDiscountCode = "";
    state.newSubscriptionForm.supervisorPin = "";
    state.newSubscriptionForm.authorizedDiscount = null;
    if (product && fetchSubscriptionDiscountOffers && state.selectedPartnerId) {
        try {
            state.newSubscriptionForm.discountOffers = await fetchSubscriptionDiscountOffers(
                state.selectedPartnerId,
                numericProductId,
                "new",
                false
            );
        } catch (error) {
            console.error("Error al consultar descuentos de suscripción POS", error);
        }
    }
    if (state.newSubscriptionForm.discountOffers.length === 1) {
        const [onlyOffer] = state.newSubscriptionForm.discountOffers;
        if (!Number(onlyOffer.discount_percent || 0) && !Number(onlyOffer.discount_fixed_amount || 0)) {
            state.newSubscriptionForm.selectedDiscountCode = String(onlyOffer.code || "");
        }
    }
    state.newSubscriptionForm.participantIds = clampParticipantIds(
        state.newSubscriptionForm.participantIds,
        state.selectedPartnerId,
        state.newSubscriptionForm.maxParticipantsTotal
    );
    if (product) {
        await recalculateNewSubscriptionCharge(product, null);
        return;
    }
    renderDetail(state.currentDetail);
}

async function updateSelectedPlan(state, planChoice, {
    getSelectedPlan,
    renderDetail,
    recalculateNewSubscriptionCharge,
}) {
    state.newSubscriptionForm.planChoice = String(planChoice || "");
    const plan = getSelectedPlan();
    const product = state.productCatalog.find((item) => Number(item.id) === Number(state.newSubscriptionForm.productId || 0)) || null;
    if (product && plan) {
        await recalculateNewSubscriptionCharge(product, plan);
        return;
    }
    renderDetail(state.currentDetail);
}

function toggleParticipant(state, partnerId, checked) {
    const numericPartnerId = Number(partnerId || 0);
    let values = [...(state.newSubscriptionForm.participantIds || [])].map((item) => Number(item));
    values = values.filter((item) => item > 0 && item !== state.selectedPartnerId && item !== numericPartnerId);
    if (checked && numericPartnerId > 0 && numericPartnerId !== state.selectedPartnerId) {
        values.push(numericPartnerId);
    }
    state.newSubscriptionForm.participantIds = clampParticipantIds(
        [state.selectedPartnerId, ...new Set(values)],
        state.selectedPartnerId,
        state.newSubscriptionForm.maxParticipantsTotal
    );
}

async function applySelectedUpsaleProduct(state, productId, {
    renderDetail,
    fetchSubscriptionPricing,
    buildChargeBreakdown,
    _t,
}) {
    if (!state.upsaleForm) {
        return;
    }
    const numericProductId = Number(productId || 0);
    const product = state.productCatalog.find((item) => Number(item.id) === numericProductId) || null;
    state.upsaleForm.productId = numericProductId;
    state.upsaleForm.productName = product ? product.name || "" : "";
    state.upsaleForm.maxParticipantsTotal = product ? Number(product.max_participants_total || 1) : 1;
    state.upsaleForm.plans = [];
    state.upsaleForm.pricingSnapshot = null;
    state.upsaleForm.planChoice = "";
    state.upsaleForm.recurringCharge = buildChargeBreakdown(null, null, { baseAmount: 0, displayAmount: 0 });
    state.upsaleForm.creditCharge = buildChargeBreakdown(null, null, { baseAmount: 0, displayAmount: 0 });
    state.upsaleForm.charge = buildChargeBreakdown(null, null, { baseAmount: 0, displayAmount: 0 });
    state.upsaleForm.participantIds = clampParticipantIds(
        state.upsaleForm.participantIds,
        state.upsaleForm.holderPartnerId,
        state.upsaleForm.maxParticipantsTotal
    );
    if (!product) {
        renderDetail(state.currentDetail);
        return;
    }
    state.upsaleForm.loading = true;
    renderDetail(state.currentDetail);
    try {
        const payload = await fetchSubscriptionPricing(
            state.upsaleForm.holderPartnerId || false,
            state.upsaleForm.productId,
            "upsale",
            state.upsaleForm.subscriptionId,
            false,
            Number(product.default_price || 0),
            false,
            false
        );
        state.upsaleForm = {
            ...state.upsaleForm,
            loading: false,
        };
        applyPricingPayloadToUpsaleForm(state, payload, null, {
            buildChargeBreakdown,
            _t,
        });
    } catch (error) {
        console.error("Error al consultar cobro de upsale POS", error);
        state.formError = _t("No se pudo calcular el cobro del upsale para esta suscripción.");
        state.upsaleForm = {
            ...state.upsaleForm,
            loading: false,
            recurringCharge: buildChargeBreakdown(null, null, { baseAmount: 0, displayAmount: 0 }),
            creditCharge: buildChargeBreakdown(null, null, { baseAmount: 0, displayAmount: 0 }),
            charge: buildChargeBreakdown(null, null, { baseAmount: 0, displayAmount: 0 }),
        };
    }
    renderDetail(state.currentDetail);
}

async function updateSelectedUpsalePlan(state, planChoice, {
    getSelectedUpsalePlan,
    renderDetail,
    fetchSubscriptionPricing,
    buildChargeBreakdown,
    _t,
}) {
    if (!state.upsaleForm) {
        return;
    }
    state.upsaleForm.planChoice = String(planChoice || "");
    const selectedPlan = getSelectedUpsalePlan();
    if (!selectedPlan || !state.upsaleForm.productId || !state.upsaleForm.subscriptionId) {
        renderDetail(state.currentDetail);
        return;
    }
    state.upsaleForm.loading = true;
    renderDetail(state.currentDetail);
    try {
        const payload = await fetchSubscriptionPricing(
            state.upsaleForm.holderPartnerId || false,
            state.upsaleForm.productId,
            "upsale",
            state.upsaleForm.subscriptionId,
            false,
            Number(selectedPlan.price || 0),
            Number(selectedPlan.plan_id || 0) || false,
            Number(selectedPlan.pricing_id || 0) || false
        );
        state.upsaleForm = {
            ...state.upsaleForm,
            loading: false,
        };
        applyPricingPayloadToUpsaleForm(state, payload, selectedPlan, {
            buildChargeBreakdown,
            _t,
        });
    } catch (error) {
        console.error("Error al actualizar cobro de upsale POS", error);
        state.formError = _t("No se pudo recalcular el cobro del upsale.");
        state.upsaleForm = {
            ...state.upsaleForm,
            loading: false,
        };
    }
    renderDetail(state.currentDetail);
}

function toggleUpsaleParticipant(state, partnerId, checked) {
    if (!state.upsaleForm) {
        return;
    }
    const numericPartnerId = Number(partnerId || 0);
    const holderPartnerId = Number(state.upsaleForm.holderPartnerId || 0);
    let values = [...(state.upsaleForm.participantIds || [])].map((item) => Number(item));
    values = values.filter((item) => item > 0 && item !== holderPartnerId && item !== numericPartnerId);
    if (checked && numericPartnerId > 0 && numericPartnerId !== holderPartnerId) {
        values.push(numericPartnerId);
    }
    state.upsaleForm.participantIds = clampParticipantIds(
        holderPartnerId ? [holderPartnerId, ...new Set(values)] : [...new Set(values)],
        holderPartnerId,
        state.upsaleForm.maxParticipantsTotal
    );
}

function toggleEditedParticipant(state, partnerId, checked) {
    if (!state.participantEditForm) {
        return;
    }
    const numericPartnerId = Number(partnerId || 0);
    const holderPartnerId = Number(state.participantEditForm.holderPartnerId || 0);
    let values = [...(state.participantEditForm.participantIds || [])].map((item) => Number(item));
    values = values.filter((item) => item > 0 && item !== holderPartnerId && item !== numericPartnerId);
    if (checked && numericPartnerId > 0 && numericPartnerId !== holderPartnerId) {
        values.push(numericPartnerId);
    }
    state.participantEditForm.participantIds = clampParticipantIds(
        holderPartnerId ? [holderPartnerId, ...new Set(values)] : [...new Set(values)],
        holderPartnerId,
        state.participantEditForm.maxParticipantsTotal
    );
}

export {
    applySelectedProduct,
    applySelectedUpsaleProduct,
    clampParticipantIds,
    filterParticipantRows,
    openNewSubscriptionForm,
    openParticipantEditForm,
    openPendingChargeForm,
    openReenrollForm,
    openRenewalForm,
    openUpsaleForm,
    recalculateNewSubscriptionCharge,
    toggleEditedParticipant,
    toggleParticipant,
    toggleUpsaleParticipant,
    updateSelectedPlan,
    updateSelectedUpsalePlan,
};
