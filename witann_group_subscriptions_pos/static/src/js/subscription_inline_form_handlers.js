/** @odoo-module **/

import { getAuthorizationOnlyOffer } from "./subscription_discount_render";
import { buildChargeFromSnapshot, getPricingSnapshot } from "./subscription_pricing_snapshot";

async function ensureEligibleProductForPartner(state, partnerId, productId, {
    flow = "new",
    sourceSubscriptionId = false,
    validateSubscriptionProductEligibility,
    renderDetail,
    _t,
}) {
    try {
        const result = await validateSubscriptionProductEligibility(
            partnerId,
            productId,
            flow,
            sourceSubscriptionId || false
        );
        if (!result || result.ok === false) {
            state.formError = result && result.error_message
                ? result.error_message
                : _t("El cliente no cumple las reglas de elegibilidad para este paquete.");
            renderDetail(state.currentDetail);
            return false;
        }
        return true;
    } catch (error) {
        console.error("Error al validar elegibilidad de producto POS", error);
        state.formError = (error && error.message)
            ? error.message
            : _t("No se pudo validar la elegibilidad del cliente para este paquete.");
        renderDetail(state.currentDetail);
        return false;
    }
}

function getAuthorizedDiscountPercent(form) {
    return Number(
        form
        && form.authorizedDiscount
        && form.authorizedDiscount.discountPercent !== undefined
            ? form.authorizedDiscount.discountPercent
            : 0
    ) || 0;
}

function buildAuthorizedDiscountMetadata(form) {
    if (!form || !form.authorizedDiscount) {
        return {};
    }
    return {
        discount_code: form.authorizedDiscount.code || false,
        discount_label: form.authorizedDiscount.label || false,
        discount_percent: Number(form.authorizedDiscount.discountPercent || 0) || 0,
        discount_fixed_amount: Number(form.authorizedDiscount.discountFixedAmount || 0) || 0,
        discount_authorized_employee_id: Number(form.authorizedDiscount.authorizedEmployeeId || 0) || false,
        discount_authorized_by: form.authorizedDiscount.authorizedBy || false,
        discount_authorized_at: form.authorizedDiscount.authorizedAt || false,
        discount_birthday_year: Number(form.authorizedDiscount.birthdayYear || 0) || false,
    };
}

function hasPendingDiscountAuthorization(form) {
    const selectedCode = String(form && form.selectedDiscountCode ? form.selectedDiscountCode : "");
    if (!selectedCode) {
        return false;
    }
    return !form.authorizedDiscount || String(form.authorizedDiscount.code || "") !== selectedCode;
}

function getPendingAuthorizationMessage(form, _t) {
    return getAuthorizationOnlyOffer(form)
        ? _t("Debes autorizar esta venta antes de agregarla al ticket.")
        : _t("Debes autorizar el descuento seleccionado antes de agregarla al ticket.");
}

async function authorizeDiscountForForm(state, form, { partnerId, productId, flow, sourceSubscriptionId = false }, {
    authorizeSubscriptionDiscount,
    renderDetail,
    _t,
}) {
    const authorizationOnlyOffer = getAuthorizationOnlyOffer(form);
    if (authorizationOnlyOffer && !String(form.selectedDiscountCode || "").trim()) {
        form.selectedDiscountCode = String(authorizationOnlyOffer.code || "");
    }
    if (!form || !String(form.selectedDiscountCode || "").trim()) {
        state.formError = authorizationOnlyOffer
            ? _t("No se encontró la autorización requerida para esta venta.")
            : _t("Selecciona un beneficio antes de autorizar el descuento.");
        renderDetail(state.currentDetail);
        return false;
    }
    if (!String(form.supervisorPin || "").trim()) {
        state.formError = authorizationOnlyOffer
            ? _t("Captura el PIN supervisor para autorizar esta venta.")
            : _t("Captura el PIN supervisor para autorizar el descuento.");
        renderDetail(state.currentDetail);
        return false;
    }
    try {
        const result = await authorizeSubscriptionDiscount(
            partnerId,
            productId,
            flow,
            form.selectedDiscountCode,
            form.supervisorPin,
            sourceSubscriptionId || false
        );
        if (!result || result.ok === false) {
            state.formError = result && result.error_message
                ? result.error_message
                : (
                    authorizationOnlyOffer
                        ? _t("No se pudo autorizar la venta solicitada.")
                        : _t("No se pudo autorizar el descuento solicitado.")
                );
            renderDetail(state.currentDetail);
            return false;
        }
        form.authorizedDiscount = {
            code: result.code || form.selectedDiscountCode,
            label: result.label || form.selectedDiscountCode,
            discountPercent: Number(result.discount_percent || 0) || 0,
            discountFixedAmount: Number(result.discount_fixed_amount || 0) || 0,
            authorizedEmployeeId: Number(result.authorized_employee_id || 0) || false,
            authorizedBy: result.authorized_by || "",
            authorizedAt: result.authorized_at || false,
            birthdayYear: Number(result.birthday_year || 0) || false,
        };
        state.formNotice = authorizationOnlyOffer
            ? _t("Venta autorizada correctamente.")
            : _t("Descuento autorizado correctamente.");
        renderDetail(state.currentDetail);
        return true;
    } catch (error) {
        console.error("Error al autorizar descuento POS", error);
        state.formError = (error && error.message)
            ? error.message
            : (
                authorizationOnlyOffer
                    ? _t("No se pudo autorizar la venta solicitada.")
                    : _t("No se pudo autorizar el descuento solicitado.")
            );
        renderDetail(state.currentDetail);
        return false;
    }
}

function buildSubscriptionInlineActionHandlers({
    state,
    clearFeedback,
    renderDetail,
    resetInlineForms,
    openRenewalForm,
    openReenrollForm,
    openUpsaleForm,
    openParticipantEditForm,
    openPendingChargeForm,
    openCancellationRefundForm,
    fetchResyncAccess,
    loadDetail,
    detailCache,
    getCurrentSubscriptionItem,
    getSelectedPlan,
    getSelectedUpsalePlan,
    getPlanPeriodEndDate,
    buildChargeBreakdown,
    addConfiguredProductLineToOrder,
    getCurrentOrder,
    getPartnerIdFromOrder,
    updatePartnerCurp,
    findPartnerInPos,
    setPartnerOnCurrentOrder,
    findProductInPos,
    getSubscriptionPartnerIdsFromOrder,
    saveSubscriptionParticipants,
    validateSubscriptionProductEligibility,
    authorizeSubscriptionDiscount,
    formatTodayISO,
    _t,
}) {
    return {
        "open-renewal": async ({ actionButton }) => {
            await openRenewalForm(getCurrentSubscriptionItem(actionButton));
        },
        "open-reenroll": async ({ actionButton }) => {
            await openReenrollForm(getCurrentSubscriptionItem(actionButton));
        },
        "open-upsale": async ({ actionButton }) => {
            await openUpsaleForm(getCurrentSubscriptionItem(actionButton));
        },
        "open-participants": async ({ actionButton }) => {
            await openParticipantEditForm(getCurrentSubscriptionItem(actionButton));
        },
        "resync-access": async ({ actionButton }) => {
            const subscriptionId = Number(actionButton.dataset.subscriptionId || 0);
            if (!subscriptionId) {
                return;
            }
            clearFeedback();
            try {
                const result = await fetchResyncAccess(subscriptionId);
                const summary = result && result.access_summary ? result.access_summary : {};
                state.formNotice = _t("Acceso resincronizado. Personas activas: %s. Personas sin registro: %s.")
                    .replace("%s", String(summary.active_count || 0))
                    .replace("%s", String(summary.missing_count || 0));
                if (state.currentDetail && state.currentDetail.partner_id) {
                    detailCache.delete(Number(state.currentDetail.partner_id || 0));
                }
                await loadDetail(state.selectedPartnerId, { force: true });
            } catch (error) {
                console.error("Error al resincronizar acceso desde POS", error);
                state.formError = (error && error.message) ? error.message : _t("No se pudo resincronizar el acceso de esta suscripción.");
                renderDetail(state.currentDetail);
            }
        },
        "open-pending": async ({ actionButton }) => {
            await openPendingChargeForm(getCurrentSubscriptionItem(actionButton));
        },
        "open-cancellation-refund": async ({ actionButton }) => {
            await openCancellationRefundForm(getCurrentSubscriptionItem(actionButton));
        },
        "cancel-renewal": async () => {
            resetInlineForms();
            renderDetail(state.currentDetail);
        },
        "cancel-reenroll": async () => {
            resetInlineForms();
            renderDetail(state.currentDetail);
        },
        "cancel-upsale": async () => {
            resetInlineForms();
            renderDetail(state.currentDetail);
        },
        "cancel-pending": async () => {
            resetInlineForms();
            renderDetail(state.currentDetail);
        },
        "cancel-cancellation-refund": async () => {
            resetInlineForms();
            renderDetail(state.currentDetail);
        },
        "cancel-participants": async () => {
            resetInlineForms();
            renderDetail(state.currentDetail);
        },
        "authorize-new-discount": async () => {
            state.formError = "";
            state.formNotice = "";
            if (!state.newSubscriptionForm || !state.selectedPartnerId || !state.newSubscriptionForm.productId) {
                state.formError = _t("No hay un producto de suscripción listo para autorizar descuento.");
                renderDetail(state.currentDetail);
                return;
            }
            await authorizeDiscountForForm(
                state,
                state.newSubscriptionForm,
                {
                    partnerId: state.selectedPartnerId,
                    productId: state.newSubscriptionForm.productId,
                    flow: "new",
                },
                {
                    authorizeSubscriptionDiscount,
                    renderDetail,
                    _t,
                }
            );
        },
        "authorize-renewal-discount": async () => {
            state.formError = "";
            state.formNotice = "";
            if (!state.renewalForm || !state.renewalForm.holderPartnerId || !state.renewalForm.productId) {
                state.formError = _t("No hay una renovación lista para autorizar descuento.");
                renderDetail(state.currentDetail);
                return;
            }
            await authorizeDiscountForForm(
                state,
                state.renewalForm,
                {
                    partnerId: state.renewalForm.holderPartnerId,
                    productId: state.renewalForm.productId,
                    flow: "renewal",
                    sourceSubscriptionId: state.renewalForm.subscriptionId,
                },
                {
                    authorizeSubscriptionDiscount,
                    renderDetail,
                    _t,
                }
            );
        },
        "authorize-reenroll-discount": async () => {
            state.formError = "";
            state.formNotice = "";
            if (!state.renewalForm || !state.renewalForm.holderPartnerId || !state.renewalForm.productId) {
                state.formError = _t("No hay una reinscripción lista para autorizar descuento.");
                renderDetail(state.currentDetail);
                return;
            }
            await authorizeDiscountForForm(
                state,
                state.renewalForm,
                {
                    partnerId: state.renewalForm.holderPartnerId,
                    productId: state.renewalForm.productId,
                    flow: "reenroll",
                    sourceSubscriptionId: state.renewalForm.subscriptionId,
                },
                {
                    authorizeSubscriptionDiscount,
                    renderDetail,
                    _t,
                }
            );
        },
        "save-new": async () => {
            state.formError = "";
            state.formNotice = "";
            const pricingSnapshot = getPricingSnapshot(state.newSubscriptionForm);
            if (!state.selectedPartnerId) {
                state.formError = _t("Selecciona un cliente para agregar la suscripcion al ticket.");
                renderDetail(state.currentDetail);
                return;
            }
            if (!state.newSubscriptionForm.productId) {
                state.formError = _t("Selecciona un producto de suscripcion.");
                renderDetail(state.currentDetail);
                return;
            }
            const order = getCurrentOrder();
            const existingSubscriptionPartnerIds = getSubscriptionPartnerIdsFromOrder(order);
            if (existingSubscriptionPartnerIds.length && !existingSubscriptionPartnerIds.includes(state.selectedPartnerId)) {
                state.formError = _t("La orden actual ya contiene suscripciones configuradas para otro cliente. Usa un solo titular por ticket.");
                renderDetail(state.currentDetail);
                return;
            }
            const participantIds = [...new Set((state.newSubscriptionForm.participantIds || []).map((value) => Number(value || 0)).filter((value) => value > 0))];
            if (!participantIds.includes(state.selectedPartnerId)) {
                participantIds.unshift(state.selectedPartnerId);
            }
            const currentPartnerCurp = state.currentDetail
                && Number(state.currentDetail.partner_id || 0) === Number(state.selectedPartnerId || 0)
                ? String(state.currentDetail.curp || "").trim()
                : "";
            const enteredCurp = String(state.newSubscriptionForm.curp || "").trim();
            if (state.newSubscriptionForm.requiresCurp && !currentPartnerCurp && !enteredCurp) {
                state.formError = _t("Este producto requiere CURP. Captúrala antes de agregar la suscripción al ticket.");
                renderDetail(state.currentDetail);
                return;
            }
            if (!state.newSubscriptionForm.pricingSnapshot) {
                state.formError = _t("No se pudo resolver el pricing de la suscripción. Reintenta seleccionar el plan.");
                renderDetail(state.currentDetail);
                return;
            }
            if (!Number(pricingSnapshot.plan_id || 0) && !Number(pricingSnapshot.pricing_id || 0)) {
                state.formError = _t("No se pudo resolver el plan recurrente de la suscripción.");
                renderDetail(state.currentDetail);
                return;
            }
            const posCharge = buildChargeBreakdown(
                null,
                null,
                buildChargeFromSnapshot(state.newSubscriptionForm, "recurring")
            );
            if (participantIds.length > Number(state.newSubscriptionForm.maxParticipantsTotal || 1)) {
                state.formError = _t("Estas excediendo el cupo maximo de participantes para este paquete.");
                renderDetail(state.currentDetail);
                return;
            }
            const automaticEndDate = getPlanPeriodEndDate(
                state.newSubscriptionForm.startDate,
                Number(pricingSnapshot.interval_value || 1) || 1,
                pricingSnapshot.interval_unit || "month"
            );
            if (!automaticEndDate) {
                state.formError = _t("No se pudo calcular la fecha de fin automática para el plan seleccionado.");
                renderDetail(state.currentDetail);
                return;
            }
            if (!order) {
                state.formError = _t("No hay una orden POS activa para agregar la suscripcion.");
                renderDetail(state.currentDetail);
                return;
            }
            const partnerOnOrderId = getPartnerIdFromOrder(order);
            if (partnerOnOrderId !== state.selectedPartnerId) {
                const partnerRecord = findPartnerInPos(state.selectedPartnerId);
                if (partnerRecord && setPartnerOnCurrentOrder(partnerRecord)) {
                    // Partner aligned locally in POS.
                } else if (partnerOnOrderId) {
                    state.formError = _t("La orden actual ya tiene otro cliente y no se pudo reemplazar desde esta sesion. Usa un solo cliente por ticket.");
                    renderDetail(state.currentDetail);
                    return;
                } else {
                    state.formNotice = _t("El cliente no esta cargado en la sesion local del POS. La suscripcion se vinculara al titular al confirmar el pago.");
                }
            }
            const productRecord = findProductInPos(state.newSubscriptionForm.productId);
            if (!productRecord) {
                state.formError = _t("El producto seleccionado no está cargado en la sesión actual del POS.");
                renderDetail(state.currentDetail);
                return;
            }
            if (state.newSubscriptionForm.requiresCurp && !currentPartnerCurp && enteredCurp) {
                try {
                    const curpResult = await updatePartnerCurp(state.selectedPartnerId, enteredCurp);
                    if (!curpResult || curpResult.ok === false) {
                        state.formError = curpResult && curpResult.error_message
                            ? curpResult.error_message
                            : _t("No se pudo guardar la CURP del cliente.");
                        renderDetail(state.currentDetail);
                        return;
                    }
                    state.newSubscriptionForm.curp = curpResult && curpResult.curp ? curpResult.curp : enteredCurp;
                    if (state.currentDetail && Number(state.currentDetail.partner_id || 0) === Number(state.selectedPartnerId || 0)) {
                        state.currentDetail = {
                            ...state.currentDetail,
                            curp: curpResult && curpResult.curp ? curpResult.curp : enteredCurp,
                        };
                    }
                    detailCache.delete(Number(state.selectedPartnerId || 0));
                    await loadDetail(state.selectedPartnerId, { force: true });
                } catch (error) {
                    console.error("Error al actualizar CURP de cliente desde POS", error);
                    state.formError = (error && error.message)
                        ? error.message
                        : _t("No se pudo guardar la CURP del cliente.");
                    renderDetail(state.currentDetail);
                    return;
                }
            }
            if (!(await ensureEligibleProductForPartner(state, state.selectedPartnerId, state.newSubscriptionForm.productId, {
                flow: "new",
                validateSubscriptionProductEligibility,
                renderDetail,
                _t,
            }))) {
                return;
            }
            if (hasPendingDiscountAuthorization(state.newSubscriptionForm)) {
                state.formError = getPendingAuthorizationMessage(state.newSubscriptionForm, _t);
                renderDetail(state.currentDetail);
                return;
            }
            let targetLine = null;
            try {
                const lineResult = await addConfiguredProductLineToOrder(order, productRecord, {
                    quantity: 1,
                    merge: false,
                    charge: posCharge,
                    discount: getAuthorizedDiscountPercent(state.newSubscriptionForm),
                    metadata: {
                        flow: "new",
                        partner_id: state.selectedPartnerId,
                        participant_ids: participantIds,
                        plan_id: Number(pricingSnapshot.plan_id || 0) || false,
                        pricing_id: Number(pricingSnapshot.pricing_id || 0) || false,
                        start_date: state.newSubscriptionForm.startDate,
                        end_date: automaticEndDate || false,
                        product_id: Number(state.newSubscriptionForm.productId || 0) || false,
                        product_name: state.newSubscriptionForm.productName || false,
                        pricing_snapshot: state.newSubscriptionForm.pricingSnapshot || false,
                        ...buildAuthorizedDiscountMetadata(state.newSubscriptionForm),
                    },
                });
                targetLine = lineResult && lineResult.line ? lineResult.line : null;
                if (!targetLine && lineResult && lineResult.reason === "not_added") {
                    state.formError = _t("No se pudo agregar el producto al ticket actual.");
                    renderDetail(state.currentDetail);
                    return;
                }
            } catch (error) {
                console.error("Error al agregar producto de suscripcion al ticket POS", error);
                state.formError = _t("No se pudo agregar el producto al ticket actual.");
                renderDetail(state.currentDetail);
                return;
            }
            if (!targetLine) {
                state.formError = _t("No se pudo identificar la linea agregada al ticket.");
                renderDetail(state.currentDetail);
                return;
            }
            state.formMode = null;
            state.formError = "";
            state.formNotice = _t("Suscripcion agregada al ticket. Puedes continuar al cobro normal del POS.");
            renderDetail(state.currentDetail);
        },
        "save-pending": async () => {
            state.formError = "";
            state.formNotice = "";
            if (!state.pendingChargeForm || !state.pendingChargeForm.subscriptionId || !state.pendingChargeForm.pendingMoveId || !state.pendingChargeForm.productId) {
                state.formError = _t("El documento pendiente seleccionado no tiene datos suficientes para agregarse al ticket.");
                renderDetail(state.currentDetail);
                return;
            }
            const order = getCurrentOrder();
            if (!order) {
                state.formError = _t("No hay una orden POS activa para agregar el cobro pendiente.");
                renderDetail(state.currentDetail);
                return;
            }
            const holderPartnerId = Number(state.pendingChargeForm.holderPartnerId || 0) || false;
            const partnerOnOrderId = getPartnerIdFromOrder(order);
            if (partnerOnOrderId !== holderPartnerId) {
                const partnerRecord = findPartnerInPos(holderPartnerId);
                if (partnerRecord && setPartnerOnCurrentOrder(partnerRecord)) {
                    // Partner aligned locally in POS.
                } else if (partnerOnOrderId) {
                    state.formError = _t("La orden actual ya tiene otro cliente y no se pudo reemplazar desde esta sesión. Usa un solo cliente por ticket.");
                    renderDetail(state.currentDetail);
                    return;
                } else {
                    state.formNotice = _t("El titular no está cargado en la sesión local del POS. El cobro pendiente se vinculará al confirmar el pago.");
                }
            }
            const productRecord = findProductInPos(state.pendingChargeForm.productId);
            if (!productRecord) {
                state.formError = _t("El producto recurrente de esta suscripción no está cargado en la sesión actual del POS.");
                renderDetail(state.currentDetail);
                return;
            }
            if (!state.pendingChargeForm.pricingSnapshot) {
                state.formError = _t("No se pudo resolver el pricing del cobro pendiente.");
                renderDetail(state.currentDetail);
                return;
            }
            let targetLine = null;
            try {
                const lineResult = await addConfiguredProductLineToOrder(order, productRecord, {
                    quantity: 1,
                    merge: false,
                    charge: buildChargeFromSnapshot(state.pendingChargeForm, "charge_now"),
                    metadata: {
                        flow: "pending_charge",
                        partner_id: holderPartnerId || false,
                        participant_ids: [],
                        plan_id: false,
                        pricing_id: false,
                        start_date: false,
                        end_date: false,
                        product_id: Number(state.pendingChargeForm.productId || 0) || false,
                        product_name: state.pendingChargeForm.productName || false,
                        source_subscription_id: Number(state.pendingChargeForm.subscriptionId || 0) || false,
                        pending_move_id: Number(state.pendingChargeForm.pendingMoveId || 0) || false,
                    },
                });
                targetLine = lineResult && lineResult.line ? lineResult.line : null;
                if (!targetLine && lineResult && lineResult.reason === "not_added") {
                    state.formError = _t("No se pudo agregar el cobro pendiente al ticket actual.");
                    renderDetail(state.currentDetail);
                    return;
                }
            } catch (error) {
                console.error("Error al agregar cobro pendiente al ticket POS", error);
                state.formError = _t("No se pudo agregar el cobro pendiente al ticket actual.");
                renderDetail(state.currentDetail);
                return;
            }
            if (!targetLine) {
                state.formError = _t("No se pudo identificar la línea de cobro pendiente agregada al ticket.");
                renderDetail(state.currentDetail);
                return;
            }
            state.formMode = null;
            state.formError = "";
            state.formNotice = _t("Cobro pendiente agregado al ticket. Puedes continuar al cobro normal del POS.");
            state.renewalForm = null;
            state.upsaleForm = null;
            state.pendingChargeForm = null;
            state.participantEditForm = null;
            renderDetail(state.currentDetail);
        },
        "save-cancellation-refund": async () => {
            state.formError = "";
            state.formNotice = "";
            if (!state.cancellationRefundForm || !state.cancellationRefundForm.subscriptionId || !state.cancellationRefundForm.originPosLineId || !state.cancellationRefundForm.productId) {
                state.formError = _t("No se encontró un cobro POS exacto para devolver esta suscripción.");
                renderDetail(state.currentDetail);
                return;
            }
            const order = getCurrentOrder();
            if (!order) {
                state.formError = _t("No hay una orden POS activa para agregar la devolución.");
                renderDetail(state.currentDetail);
                return;
            }
            const holderPartnerId = Number(state.cancellationRefundForm.holderPartnerId || 0) || false;
            const partnerOnOrderId = getPartnerIdFromOrder(order);
            if (partnerOnOrderId !== holderPartnerId) {
                const partnerRecord = findPartnerInPos(holderPartnerId);
                if (partnerRecord && setPartnerOnCurrentOrder(partnerRecord)) {
                    // Partner aligned locally in POS.
                } else if (partnerOnOrderId) {
                    state.formError = _t("La orden actual ya tiene otro cliente y no se pudo reemplazar desde esta sesión. Usa un solo cliente por ticket.");
                    renderDetail(state.currentDetail);
                    return;
                } else {
                    state.formNotice = _t("El titular no está cargado en la sesión local del POS. La devolución se vinculará al confirmar el pago.");
                }
            }
            const productRecord = findProductInPos(state.cancellationRefundForm.productId);
            if (!productRecord) {
                state.formError = _t("El producto original de esta suscripción no está cargado en la sesión actual del POS.");
                renderDetail(state.currentDetail);
                return;
            }
            let targetLine = null;
            try {
                const lineResult = await addConfiguredProductLineToOrder(order, productRecord, {
                    quantity: -Math.max(1, Number(state.cancellationRefundForm.qty || 1)),
                    merge: false,
                    lineUnitPrice: Number(state.cancellationRefundForm.priceUnit || 0),
                    discount: Number(state.cancellationRefundForm.discount || 0),
                    metadata: {
                        flow: "cancellation_refund",
                        partner_id: holderPartnerId || false,
                        participant_ids: [],
                        plan_id: false,
                        pricing_id: false,
                        start_date: false,
                        end_date: false,
                        product_id: Number(state.cancellationRefundForm.productId || 0) || false,
                        product_name: state.cancellationRefundForm.productName || false,
                        source_subscription_id: Number(state.cancellationRefundForm.subscriptionId || 0) || false,
                        refund_origin_line_id: Number(state.cancellationRefundForm.originPosLineId || 0) || false,
                    },
                });
                targetLine = lineResult && lineResult.line ? lineResult.line : null;
                if (!targetLine && lineResult && lineResult.reason === "not_added") {
                    state.formError = _t("No se pudo agregar la devolución al ticket actual.");
                    renderDetail(state.currentDetail);
                    return;
                }
            } catch (error) {
                console.error("Error al agregar devolución por cancelación al ticket POS", error);
                state.formError = _t("No se pudo agregar la devolución al ticket actual.");
                renderDetail(state.currentDetail);
                return;
            }
            if (!targetLine) {
                state.formError = _t("No se pudo identificar la línea de devolución agregada al ticket.");
                renderDetail(state.currentDetail);
                return;
            }
            state.formMode = null;
            state.formError = "";
            state.formNotice = _t("Devolución agregada al ticket. Al cobrarla, la suscripción se cancelará.");
            state.renewalForm = null;
            state.upsaleForm = null;
            state.pendingChargeForm = null;
            state.cancellationRefundForm = null;
            state.participantEditForm = null;
            renderDetail(state.currentDetail);
        },
        "save-participants": async () => {
            state.formError = "";
            state.formNotice = "";
            if (!state.participantEditForm || !state.participantEditForm.subscriptionId) {
                state.formError = _t("La suscripción seleccionada no tiene datos suficientes para editar participantes.");
                renderDetail(state.currentDetail);
                return;
            }
            const participantIds = [...new Set((state.participantEditForm.participantIds || []).map((value) => Number(value || 0)).filter((value) => value > 0))];
            const holderPartnerId = Number(state.participantEditForm.holderPartnerId || 0) || false;
            if (holderPartnerId && !participantIds.includes(holderPartnerId)) {
                participantIds.unshift(holderPartnerId);
            }
            if (participantIds.length > Number(state.participantEditForm.maxParticipantsTotal || 1)) {
                state.formError = _t("Estas excediendo el cupo máximo de participantes para este paquete.");
                renderDetail(state.currentDetail);
                return;
            }
            try {
                const result = await saveSubscriptionParticipants(state.participantEditForm.subscriptionId, participantIds);
                state.formMode = null;
                state.participantEditForm = null;
                state.renewalForm = null;
                state.upsaleForm = null;
                state.pendingChargeForm = null;
                state.formNotice = _t("Participantes actualizados correctamente.");
                if (state.currentDetail && Array.isArray(state.currentDetail.items)) {
                    detailCache.delete(Number(state.currentDetail.partner_id || 0));
                }
                await loadDetail(state.selectedPartnerId, { force: true });
                if (result && result.ok) {
                    return;
                }
            } catch (error) {
                console.error("Error al actualizar participantes de suscripción POS", error);
                state.formError = (error && error.message) ? error.message : _t("No se pudieron guardar los participantes de la suscripción.");
                renderDetail(state.currentDetail);
            }
        },
        "save-upsale": async () => {
            state.formError = "";
            state.formNotice = "";
            if (!state.upsaleForm || !state.upsaleForm.subscriptionId || !state.upsaleForm.productId) {
                state.formError = _t("Selecciona el paquete destino para agregar el upsale al ticket.");
                renderDetail(state.currentDetail);
                return;
            }
            const pricingSnapshot = getPricingSnapshot(state.upsaleForm);
            if (!state.upsaleForm.pricingSnapshot) {
                state.formError = _t("No se pudo resolver el pricing del upsale.");
                renderDetail(state.currentDetail);
                return;
            }
            if (!Number(pricingSnapshot.plan_id || 0) && !Number(pricingSnapshot.pricing_id || 0)) {
                state.formError = _t("No se pudo resolver el plan destino del upsale.");
                renderDetail(state.currentDetail);
                return;
            }
            const participantIds = [...new Set((state.upsaleForm.participantIds || []).map((value) => Number(value || 0)).filter((value) => value > 0))];
            const holderPartnerId = Number(state.upsaleForm.holderPartnerId || 0) || false;
            if (holderPartnerId && !participantIds.includes(holderPartnerId)) {
                participantIds.unshift(holderPartnerId);
            }
            if (participantIds.length > Number(state.upsaleForm.maxParticipantsTotal || 1)) {
                state.formError = _t("Estas excediendo el cupo maximo permitido para el paquete destino.");
                renderDetail(state.currentDetail);
                return;
            }
            const order = getCurrentOrder();
            if (!order) {
                state.formError = _t("No hay una orden POS activa para agregar el upsale.");
                renderDetail(state.currentDetail);
                return;
            }
            const existingSubscriptionPartnerIds = getSubscriptionPartnerIdsFromOrder(order);
            if (existingSubscriptionPartnerIds.length && !existingSubscriptionPartnerIds.includes(holderPartnerId)) {
                state.formError = _t("La orden actual ya contiene suscripciones configuradas para otro cliente. Usa un solo titular por ticket.");
                renderDetail(state.currentDetail);
                return;
            }
            const partnerOnOrderId = getPartnerIdFromOrder(order);
            if (partnerOnOrderId !== holderPartnerId) {
                const partnerRecord = findPartnerInPos(holderPartnerId);
                if (partnerRecord && setPartnerOnCurrentOrder(partnerRecord)) {
                    // Partner aligned locally in POS.
                } else if (partnerOnOrderId) {
                    state.formError = _t("La orden actual ya tiene otro cliente y no se pudo reemplazar desde esta sesión. Usa un solo cliente por ticket.");
                    renderDetail(state.currentDetail);
                    return;
                } else {
                    state.formNotice = _t("El titular no está cargado en la sesión local del POS. El upsale se vinculará al confirmar el pago.");
                }
            }
            const productRecord = findProductInPos(state.upsaleForm.productId);
            if (!productRecord) {
                state.formError = _t("El producto destino no está cargado en la sesión actual del POS.");
                renderDetail(state.currentDetail);
                return;
            }
            if (!(await ensureEligibleProductForPartner(state, holderPartnerId, state.upsaleForm.productId, {
                flow: "upsale",
                sourceSubscriptionId: state.upsaleForm.subscriptionId,
                validateSubscriptionProductEligibility,
                renderDetail,
                _t,
            }))) {
                return;
            }
            let targetLine = null;
            try {
                const lineResult = await addConfiguredProductLineToOrder(order, productRecord, {
                    quantity: 1,
                    merge: false,
                    charge: buildChargeFromSnapshot(state.upsaleForm, "charge_now"),
                    metadata: {
                        flow: "upsale",
                        partner_id: holderPartnerId || false,
                        participant_ids: participantIds,
                        plan_id: Number(pricingSnapshot.plan_id || 0) || false,
                        pricing_id: Number(pricingSnapshot.pricing_id || 0) || false,
                        start_date: pricingSnapshot.subscription_start_date || false,
                        end_date: pricingSnapshot.subscription_end_date || false,
                        product_id: Number(state.upsaleForm.productId || 0) || false,
                        product_name: state.upsaleForm.productName || false,
                        source_subscription_id: Number(pricingSnapshot.source_subscription_id || 0) || Number(state.upsaleForm.subscriptionId || 0) || false,
                        pricing_snapshot: state.upsaleForm.pricingSnapshot || false,
                    },
                });
                targetLine = lineResult && lineResult.line ? lineResult.line : null;
                if (!targetLine && lineResult && lineResult.reason === "not_added") {
                    state.formError = _t("No se pudo agregar el upsale al ticket actual.");
                    renderDetail(state.currentDetail);
                    return;
                }
            } catch (error) {
                console.error("Error al agregar upsale al ticket POS", error);
                state.formError = _t("No se pudo agregar el upsale al ticket actual.");
                renderDetail(state.currentDetail);
                return;
            }
            if (!targetLine) {
                state.formError = _t("No se pudo identificar la línea de upsale agregada al ticket.");
                renderDetail(state.currentDetail);
                return;
            }
            state.formMode = null;
            state.formError = "";
            state.formNotice = _t("Upsale agregado al ticket. Puedes continuar al cobro normal del POS.");
            state.renewalForm = null;
            state.upsaleForm = null;
            state.pendingChargeForm = null;
            state.participantEditForm = null;
            renderDetail(state.currentDetail);
        },
        "save-renewal": async () => {
            state.formError = "";
            state.formNotice = "";
            const pricingSnapshot = getPricingSnapshot(state.renewalForm);
            if (!state.renewalForm || !state.renewalForm.subscriptionId || !state.renewalForm.productId) {
                state.formError = _t("La renovación seleccionada no tiene datos suficientes para agregarse al ticket.");
                renderDetail(state.currentDetail);
                return;
            }
            const order = getCurrentOrder();
            if (!order) {
                state.formError = _t("No hay una orden POS activa para agregar la renovación.");
                renderDetail(state.currentDetail);
                return;
            }
            const holderPartnerId = Number(state.renewalForm.holderPartnerId || 0) || false;
            const partnerOnOrderId = getPartnerIdFromOrder(order);
            if (partnerOnOrderId !== holderPartnerId) {
                const partnerRecord = findPartnerInPos(holderPartnerId);
                if (partnerRecord && setPartnerOnCurrentOrder(partnerRecord)) {
                    // Partner aligned locally in POS.
                } else if (partnerOnOrderId) {
                    state.formError = _t("La orden actual ya tiene otro cliente y no se pudo reemplazar desde esta sesión. Usa un solo cliente por ticket.");
                    renderDetail(state.currentDetail);
                    return;
                } else {
                    state.formNotice = _t("El titular no está cargado en la sesión local del POS. La renovación se vinculará al confirmar el pago.");
                }
            }
            const productRecord = findProductInPos(state.renewalForm.productId);
            if (!productRecord) {
                state.formError = _t("El producto recurrente de esta suscripción no está cargado en la sesión actual del POS.");
                renderDetail(state.currentDetail);
                return;
            }
            if (!(await ensureEligibleProductForPartner(state, holderPartnerId, state.renewalForm.productId, {
                flow: "renewal",
                sourceSubscriptionId: state.renewalForm.subscriptionId,
                validateSubscriptionProductEligibility,
                renderDetail,
                _t,
            }))) {
                return;
            }
            if (hasPendingDiscountAuthorization(state.renewalForm)) {
                state.formError = getPendingAuthorizationMessage(state.renewalForm, _t);
                renderDetail(state.currentDetail);
                return;
            }
            if (!state.renewalForm.pricingSnapshot) {
                state.formError = _t("No se pudo resolver el pricing de la renovación.");
                renderDetail(state.currentDetail);
                return;
            }
            let targetLine = null;
            try {
                const lineResult = await addConfiguredProductLineToOrder(order, productRecord, {
                    quantity: 1,
                    merge: false,
                    charge: buildChargeFromSnapshot(state.renewalForm, "charge_now"),
                    discount: getAuthorizedDiscountPercent(state.renewalForm),
                    metadata: {
                        flow: "renewal",
                        partner_id: holderPartnerId || false,
                        participant_ids: [],
                        plan_id: Number(pricingSnapshot.plan_id || 0) || false,
                        pricing_id: Number(pricingSnapshot.pricing_id || 0) || false,
                        start_date: false,
                        end_date: false,
                        product_id: Number(state.renewalForm.productId || 0) || false,
                        product_name: state.renewalForm.productName || false,
                        source_subscription_id: Number(pricingSnapshot.source_subscription_id || 0) || Number(state.renewalForm.subscriptionId || 0) || false,
                        pricing_snapshot: state.renewalForm.pricingSnapshot || false,
                        ...buildAuthorizedDiscountMetadata(state.renewalForm),
                    },
                });
                targetLine = lineResult && lineResult.line ? lineResult.line : null;
                if (!targetLine && lineResult && lineResult.reason === "not_added") {
                    state.formError = _t("No se pudo agregar la renovación al ticket actual.");
                    renderDetail(state.currentDetail);
                    return;
                }
            } catch (error) {
                console.error("Error al agregar renovación al ticket POS", error);
                state.formError = _t("No se pudo agregar la renovación al ticket actual.");
                renderDetail(state.currentDetail);
                return;
            }
            if (!targetLine) {
                state.formError = _t("No se pudo identificar la línea de renovación agregada al ticket.");
                renderDetail(state.currentDetail);
                return;
            }
            state.formMode = null;
            state.formError = "";
            state.formNotice = _t("Renovación agregada al ticket. Puedes continuar al cobro normal del POS.");
            state.renewalForm = null;
            state.upsaleForm = null;
            state.pendingChargeForm = null;
            state.participantEditForm = null;
            renderDetail(state.currentDetail);
        },
        "save-reenroll": async () => {
            state.formError = "";
            state.formNotice = "";
            const pricingSnapshot = getPricingSnapshot(state.renewalForm);
            if (!state.renewalForm || !state.renewalForm.subscriptionId || !state.renewalForm.productId) {
                state.formError = _t("La reinscripción seleccionada no tiene datos suficientes para agregarse al ticket.");
                renderDetail(state.currentDetail);
                return;
            }
            const order = getCurrentOrder();
            if (!order) {
                state.formError = _t("No hay una orden POS activa para agregar la reinscripción.");
                renderDetail(state.currentDetail);
                return;
            }
            const holderPartnerId = Number(state.renewalForm.holderPartnerId || 0) || false;
            const partnerOnOrderId = getPartnerIdFromOrder(order);
            if (partnerOnOrderId !== holderPartnerId) {
                const partnerRecord = findPartnerInPos(holderPartnerId);
                if (partnerRecord && setPartnerOnCurrentOrder(partnerRecord)) {
                    // Partner aligned locally in POS.
                } else if (partnerOnOrderId) {
                    state.formError = _t("La orden actual ya tiene otro cliente y no se pudo reemplazar desde esta sesión. Usa un solo cliente por ticket.");
                    renderDetail(state.currentDetail);
                    return;
                } else {
                    state.formNotice = _t("El titular no está cargado en la sesión local del POS. La reinscripción se vinculará al confirmar el pago.");
                }
            }
            const productRecord = findProductInPos(state.renewalForm.productId);
            if (!productRecord) {
                state.formError = _t("El producto recurrente de esta suscripción no está cargado en la sesión actual del POS.");
                renderDetail(state.currentDetail);
                return;
            }
            if (!(await ensureEligibleProductForPartner(state, holderPartnerId, state.renewalForm.productId, {
                flow: "reenroll",
                sourceSubscriptionId: state.renewalForm.subscriptionId,
                validateSubscriptionProductEligibility,
                renderDetail,
                _t,
            }))) {
                return;
            }
            if (hasPendingDiscountAuthorization(state.renewalForm)) {
                state.formError = getPendingAuthorizationMessage(state.renewalForm, _t);
                renderDetail(state.currentDetail);
                return;
            }
            if (!state.renewalForm.pricingSnapshot) {
                state.formError = _t("No se pudo resolver el pricing de la reinscripción.");
                renderDetail(state.currentDetail);
                return;
            }
            let targetLine = null;
            try {
                const lineResult = await addConfiguredProductLineToOrder(order, productRecord, {
                    quantity: 1,
                    merge: false,
                    charge: buildChargeFromSnapshot(state.renewalForm, "charge_now"),
                    discount: getAuthorizedDiscountPercent(state.renewalForm),
                    metadata: {
                        flow: "reenroll",
                        partner_id: holderPartnerId || false,
                        participant_ids: Array.isArray(state.renewalForm.participantIds) ? state.renewalForm.participantIds : [],
                        plan_id: Number(pricingSnapshot.plan_id || 0) || false,
                        pricing_id: Number(pricingSnapshot.pricing_id || 0) || false,
                        start_date: formatTodayISO(),
                        end_date: false,
                        product_id: Number(state.renewalForm.productId || 0) || false,
                        product_name: state.renewalForm.productName || false,
                        source_subscription_id: Number(pricingSnapshot.source_subscription_id || 0) || Number(state.renewalForm.subscriptionId || 0) || false,
                        pricing_snapshot: state.renewalForm.pricingSnapshot || false,
                        ...buildAuthorizedDiscountMetadata(state.renewalForm),
                    },
                });
                targetLine = lineResult && lineResult.line ? lineResult.line : null;
                if (!targetLine && lineResult && lineResult.reason === "not_added") {
                    state.formError = _t("No se pudo agregar la reinscripción al ticket actual.");
                    renderDetail(state.currentDetail);
                    return;
                }
            } catch (error) {
                console.error("Error al agregar reinscripción al ticket POS", error);
                state.formError = _t("No se pudo agregar la reinscripción al ticket actual.");
                renderDetail(state.currentDetail);
                return;
            }
            if (!targetLine) {
                state.formError = _t("No se pudo identificar la línea de reinscripción agregada al ticket.");
                renderDetail(state.currentDetail);
                return;
            }
            state.formMode = null;
            state.formError = "";
            state.formNotice = _t("Reinscripción agregada al ticket. Puedes continuar al cobro normal del POS.");
            state.renewalForm = null;
            state.upsaleForm = null;
            state.pendingChargeForm = null;
            state.participantEditForm = null;
            renderDetail(state.currentDetail);
        },
    };
}

async function handleSubscriptionInlineFieldChange({ field, target }, {
    state,
    clearFeedback,
    applySelectedProduct,
    updateSelectedPlan,
    applySelectedUpsaleProduct,
    updateSelectedUpsalePlan,
    toggleParticipant,
    toggleUpsaleParticipant,
    toggleEditedParticipant,
    formatTodayISO,
    renderDetail,
}) {
    clearFeedback();
    if (state.formMode === "new" && field === "product_id") {
        await applySelectedProduct(target.value);
    } else if (state.formMode === "new" && field === "plan_choice") {
        await updateSelectedPlan(target.value);
    } else if (state.formMode === "new" && field === "new_discount_code") {
        state.newSubscriptionForm.selectedDiscountCode = target.value || "";
        state.newSubscriptionForm.supervisorPin = "";
        state.newSubscriptionForm.authorizedDiscount = null;
    } else if (state.formMode === "new" && field === "start_date") {
        state.newSubscriptionForm.startDate = target.value || formatTodayISO();
    } else if (state.formMode === "new" && field === "participant_toggle") {
        toggleParticipant(target.value, target.checked);
    } else if ((state.formMode === "renewal" || state.formMode === "reenroll") && field === "renewal_discount_code") {
        state.renewalForm.selectedDiscountCode = target.value || "";
        state.renewalForm.supervisorPin = "";
        state.renewalForm.authorizedDiscount = null;
    } else if (state.formMode === "upsale" && field === "upsale_product_id") {
        await applySelectedUpsaleProduct(target.value);
    } else if (state.formMode === "upsale" && field === "upsale_plan_choice") {
        await updateSelectedUpsalePlan(target.value);
    } else if (state.formMode === "upsale" && field === "upsale_participant_toggle") {
        toggleUpsaleParticipant(target.value, target.checked);
    } else if (state.formMode === "participants" && field === "edit_participant_toggle") {
        toggleEditedParticipant(target.value, target.checked);
    } else {
        return false;
    }
    renderDetail(state.currentDetail);
    return true;
}

function handleSubscriptionInlineFieldInput({ field, target }, {
    state,
}) {
    if (state.formMode === "new" && field === "participant_search") {
        state.newSubscriptionForm.participantSearch = target.value || "";
        return true;
    }
    if (state.formMode === "new" && field === "new_supervisor_pin") {
        state.newSubscriptionForm.supervisorPin = target.value || "";
        return true;
    }
    if (state.formMode === "new" && field === "subscription_curp") {
        state.newSubscriptionForm.curp = target.value || "";
        return true;
    }
    if ((state.formMode === "renewal" || state.formMode === "reenroll") && field === "renewal_supervisor_pin") {
        state.renewalForm.supervisorPin = target.value || "";
        return true;
    }
    if (state.formMode === "upsale" && field === "upsale_participant_search") {
        state.upsaleForm.participantSearch = target.value || "";
        return true;
    }
    if (state.formMode === "participants" && field === "edit_participant_search") {
        state.participantEditForm.participantSearch = target.value || "";
        return true;
    }
    return false;
}

export {
    buildSubscriptionInlineActionHandlers,
    handleSubscriptionInlineFieldChange,
    handleSubscriptionInlineFieldInput,
};
