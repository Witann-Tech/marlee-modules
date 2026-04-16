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
    fetchSubscriptionRenewalCharge,
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
        nextInvoiceDate: item.next_invoice_date || false,
        loading: true,
    };
    renderDetail(state.currentDetail);
    try {
        const charge = await fetchSubscriptionRenewalCharge(
            state.renewalForm.subscriptionId,
            state.renewalForm.productId,
            state.renewalForm.planId,
            state.renewalForm.pricingId
        );
        state.renewalForm = {
            ...state.renewalForm,
            loading: false,
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
        fetchSubscriptionRenewalCharge: deps.fetchSubscriptionReenrollCharge,
    });
}

async function openPendingChargeForm(state, item, {
    stopPartnerCamera,
    renderDetail,
    buildChargeBreakdown,
    getChargeDisplayAmount,
    fetchSubscriptionPendingCharge,
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
        charge: buildChargeBreakdown(null, null, { baseAmount: 0, displayAmount: 0 }),
        totalCharge: buildChargeBreakdown(null, null, {
            baseAmount: Number(firstPending.amount_total || 0),
            displayAmount: Number(firstPending.amount_total || 0),
        }),
        loading: true,
    };
    renderDetail(state.currentDetail);
    try {
        const charge = await fetchSubscriptionPendingCharge(
            state.pendingChargeForm.subscriptionId,
            state.pendingChargeForm.pendingMoveId
        );
        state.pendingChargeForm = {
            ...state.pendingChargeForm,
            loading: false,
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

async function recalculateNewSubscriptionCharge(state, product, preferredPlan, {
    renderDetail,
    fetchSubscriptionCharge,
    buildChargeBreakdown,
    _t,
}) {
    if (!state.newSubscriptionForm || !product || !state.selectedPartnerId) {
        return;
    }
    state.newSubscriptionForm.loading = true;
    renderDetail(state.currentDetail);
    try {
        const charge = await fetchSubscriptionCharge(
            state.selectedPartnerId,
            Number(product.id || 0),
            Number(preferredPlan && preferredPlan.price ? preferredPlan.price : product.default_price || 0),
            preferredPlan ? Number(preferredPlan.plan_id || 0) || false : false,
            preferredPlan ? Number(preferredPlan.pricing_id || 0) || false : false
        );
        const displayRecurringPrice = Number(
            charge && charge.display_recurring_price !== undefined
                ? charge.display_recurring_price
                : (charge && charge.recurring_price ? charge.recurring_price : 0)
        );
        state.newSubscriptionForm.charge = buildChargeBreakdown(null, null, {
            baseAmount: Number(charge && charge.recurring_price ? charge.recurring_price : 0),
            ticketUnitPrice: Number(
                charge && charge.ticket_recurring_price !== undefined
                    ? charge.ticket_recurring_price
                    : (charge && charge.recurring_price ? charge.recurring_price : 0)
            ),
            displayAmount: displayRecurringPrice,
        });
        if (charge && (charge.plan_id || charge.pricing_id)) {
            state.newSubscriptionForm.planChoice = `${Number(charge.plan_id || 0)}:${Number(charge.pricing_id || 0)}`;
        }
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
}) {
    const numericProductId = Number(productId || 0);
    const product = state.productCatalog.find((item) => Number(item.id) === numericProductId) || null;
    state.newSubscriptionForm.productId = numericProductId;
    state.newSubscriptionForm.productName = product ? product.name || "" : "";
    state.newSubscriptionForm.maxParticipantsTotal = product ? Number(product.max_participants_total || 1) : 1;
    state.newSubscriptionForm.plans = product ? [...(product.plans || [])] : [];
    const defaultPlanId = product ? Number(product.default_plan_id || 0) : 0;
    const defaultPricingId = product ? Number(product.default_pricing_id || 0) : 0;
    const defaultChoice = state.newSubscriptionForm.plans.find((item) => {
        return Number(item.plan_id || 0) === defaultPlanId && Number(item.pricing_id || 0) === defaultPricingId;
    }) || state.newSubscriptionForm.plans[0] || null;
    if (defaultChoice) {
        state.newSubscriptionForm.planChoice = `${Number(defaultChoice.plan_id || 0)}:${Number(defaultChoice.pricing_id || 0)}`;
    } else {
        state.newSubscriptionForm.planChoice = "";
        state.newSubscriptionForm.charge = {
            baseAmount: Number(product ? (product.default_price || 0) : 0),
            displayAmount: Number(product ? (product.default_display_price !== undefined ? product.default_display_price : (product.default_price || 0)) : 0),
            ticketUnitPrice: Number(product ? (product.default_price || 0) : 0),
        };
    }
    state.newSubscriptionForm.participantIds = clampParticipantIds(
        state.newSubscriptionForm.participantIds,
        state.selectedPartnerId,
        state.newSubscriptionForm.maxParticipantsTotal
    );
    if (product) {
        await recalculateNewSubscriptionCharge(product, defaultChoice);
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
    if (plan) {
        state.newSubscriptionForm.charge = {
            baseAmount: Number(plan.price || 0),
            displayAmount: Number(plan.display_price !== undefined ? plan.display_price : (plan.price || 0)),
            ticketUnitPrice: Number(plan.price || 0),
        };
    }
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
    getSelectedUpsalePlan,
    fetchSubscriptionUpsaleCharge,
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
    state.upsaleForm.plans = product ? [...(product.plans || [])] : [];
    state.upsaleForm.planChoice = "";
    state.upsaleForm.recurringCharge = buildChargeBreakdown(null, null, { baseAmount: 0, displayAmount: 0 });
    state.upsaleForm.creditCharge = buildChargeBreakdown(null, null, { baseAmount: 0, displayAmount: 0 });
    state.upsaleForm.charge = buildChargeBreakdown(null, null, { baseAmount: 0, displayAmount: 0 });
    state.upsaleForm.participantIds = clampParticipantIds(
        state.upsaleForm.participantIds,
        state.upsaleForm.holderPartnerId,
        state.upsaleForm.maxParticipantsTotal
    );
    if (!product || !state.upsaleForm.plans.length) {
        renderDetail(state.currentDetail);
        return;
    }
    const defaultPlanId = Number(product.default_plan_id || 0);
    const defaultPricingId = Number(product.default_pricing_id || 0);
    const defaultChoice = state.upsaleForm.plans.find((item) => {
        return Number(item.plan_id || 0) === defaultPlanId && Number(item.pricing_id || 0) === defaultPricingId;
    }) || state.upsaleForm.plans[0] || null;
    if (defaultChoice) {
        state.upsaleForm.planChoice = `${Number(defaultChoice.plan_id || 0)}:${Number(defaultChoice.pricing_id || 0)}`;
    }
    state.upsaleForm.loading = true;
    renderDetail(state.currentDetail);
    try {
        const selectedPlan = getSelectedUpsalePlan();
        const charge = await fetchSubscriptionUpsaleCharge(
            state.upsaleForm.subscriptionId,
            state.upsaleForm.productId,
            Number(defaultChoice && defaultChoice.price ? defaultChoice.price : 0),
            selectedPlan ? Number(selectedPlan.plan_id || 0) || false : false,
            selectedPlan ? Number(selectedPlan.pricing_id || 0) || false : false
        );
        state.upsaleForm = {
            ...state.upsaleForm,
            loading: false,
            recurringCharge: buildChargeBreakdown(null, null, {
                baseAmount: Number(charge && charge.recurring_price ? charge.recurring_price : 0),
                ticketUnitPrice: Number(
                    charge && charge.ticket_recurring_price !== undefined
                        ? charge.ticket_recurring_price
                        : (charge && charge.recurring_price ? charge.recurring_price : 0)
                ),
                displayAmount: Number(
                    charge && charge.display_recurring_price !== undefined
                        ? charge.display_recurring_price
                        : (charge && charge.recurring_price ? charge.recurring_price : 0)
                ),
            }),
            creditCharge: buildChargeBreakdown(null, null, {
                baseAmount: Number(charge && charge.credit_amount ? charge.credit_amount : 0),
                ticketUnitPrice: Number(
                    charge && charge.ticket_credit_amount !== undefined
                        ? charge.ticket_credit_amount
                        : (charge && charge.credit_amount ? charge.credit_amount : 0)
                ),
                displayAmount: Number(
                    charge && charge.display_credit_amount !== undefined
                        ? charge.display_credit_amount
                        : (charge && charge.credit_amount ? charge.credit_amount : 0)
                ),
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
            planChoice: `${Number(charge && charge.plan_id ? charge.plan_id : (selectedPlan && selectedPlan.plan_id) || 0)}:${Number(charge && charge.pricing_id ? charge.pricing_id : (selectedPlan && selectedPlan.pricing_id) || 0)}`,
        };
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
    fetchSubscriptionUpsaleCharge,
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
        const charge = await fetchSubscriptionUpsaleCharge(
            state.upsaleForm.subscriptionId,
            state.upsaleForm.productId,
            Number(selectedPlan.price || 0),
            Number(selectedPlan.plan_id || 0) || false,
            Number(selectedPlan.pricing_id || 0) || false
        );
        state.upsaleForm = {
            ...state.upsaleForm,
            loading: false,
            recurringCharge: buildChargeBreakdown(null, null, {
                baseAmount: Number(charge && charge.recurring_price ? charge.recurring_price : 0),
                ticketUnitPrice: Number(
                    charge && charge.ticket_recurring_price !== undefined
                        ? charge.ticket_recurring_price
                        : (charge && charge.recurring_price ? charge.recurring_price : 0)
                ),
                displayAmount: Number(
                    charge && charge.display_recurring_price !== undefined
                        ? charge.display_recurring_price
                        : (charge && charge.recurring_price ? charge.recurring_price : 0)
                ),
            }),
            creditCharge: buildChargeBreakdown(null, null, {
                baseAmount: Number(charge && charge.credit_amount ? charge.credit_amount : 0),
                ticketUnitPrice: Number(
                    charge && charge.ticket_credit_amount !== undefined
                        ? charge.ticket_credit_amount
                        : (charge && charge.credit_amount ? charge.credit_amount : 0)
                ),
                displayAmount: Number(
                    charge && charge.display_credit_amount !== undefined
                        ? charge.display_credit_amount
                        : (charge && charge.credit_amount ? charge.credit_amount : 0)
                ),
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
            planChoice: `${Number(charge && charge.plan_id ? charge.plan_id : selectedPlan.plan_id || 0)}:${Number(charge && charge.pricing_id ? charge.pricing_id : selectedPlan.pricing_id || 0)}`,
        };
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
