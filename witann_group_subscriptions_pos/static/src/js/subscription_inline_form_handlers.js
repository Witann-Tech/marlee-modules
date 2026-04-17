/** @odoo-module **/

async function ensureEligibleProductForPartner(state, partnerId, productId, {
    validateSubscriptionProductEligibility,
    renderDetail,
    _t,
}) {
    try {
        const result = await validateSubscriptionProductEligibility(partnerId, productId);
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
        "save-new": async () => {
            state.formError = "";
            state.formNotice = "";
            const selectedPlan = getSelectedPlan();
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
            if (!selectedPlan) {
                state.formError = _t("Selecciona un plan recurrente.");
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
            const posCharge = buildChargeBreakdown(null, null, state.newSubscriptionForm.charge || {});
            if (participantIds.length > Number(state.newSubscriptionForm.maxParticipantsTotal || 1)) {
                state.formError = _t("Estas excediendo el cupo maximo de participantes para este paquete.");
                renderDetail(state.currentDetail);
                return;
            }
            const automaticEndDate = getPlanPeriodEndDate(
                state.newSubscriptionForm.startDate,
                selectedPlan.interval_value,
                selectedPlan.interval_unit
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
                    charge: posCharge,
                    metadata: {
                        flow: "new",
                        partner_id: state.selectedPartnerId,
                        participant_ids: participantIds,
                        plan_id: Number(selectedPlan.plan_id || 0) || false,
                        pricing_id: Number(selectedPlan.pricing_id || 0) || false,
                        start_date: state.newSubscriptionForm.startDate,
                        end_date: automaticEndDate || false,
                        product_id: Number(state.newSubscriptionForm.productId || 0) || false,
                        product_name: state.newSubscriptionForm.productName || false,
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
            let targetLine = null;
            try {
                const lineResult = await addConfiguredProductLineToOrder(order, productRecord, {
                    quantity: 1,
                    merge: false,
                    charge: state.pendingChargeForm.charge,
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
            const selectedUpsalePlan = getSelectedUpsalePlan();
            if (!selectedUpsalePlan) {
                state.formError = _t("Selecciona el plan destino para el upsale.");
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
                    charge: state.upsaleForm.charge,
                    metadata: {
                        flow: "upsale",
                        partner_id: holderPartnerId || false,
                        participant_ids: participantIds,
                        plan_id: Number(selectedUpsalePlan.plan_id || 0) || false,
                        pricing_id: Number(selectedUpsalePlan.pricing_id || 0) || false,
                        start_date: formatTodayISO(),
                        end_date: false,
                        product_id: Number(state.upsaleForm.productId || 0) || false,
                        product_name: state.upsaleForm.productName || false,
                        source_subscription_id: Number(state.upsaleForm.subscriptionId || 0) || false,
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
                    charge: state.renewalForm.charge,
                    metadata: {
                        flow: "renewal",
                        partner_id: holderPartnerId || false,
                        participant_ids: [],
                        plan_id: Number(state.renewalForm.planId || 0) || false,
                        pricing_id: Number(state.renewalForm.pricingId || 0) || false,
                        start_date: false,
                        end_date: false,
                        product_id: Number(state.renewalForm.productId || 0) || false,
                        product_name: state.renewalForm.productName || false,
                        source_subscription_id: Number(state.renewalForm.subscriptionId || 0) || false,
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
                    charge: state.renewalForm.charge,
                    metadata: {
                        flow: "reenroll",
                        partner_id: holderPartnerId || false,
                        participant_ids: Array.isArray(state.renewalForm.participantIds) ? state.renewalForm.participantIds : [],
                        plan_id: Number(state.renewalForm.planId || 0) || false,
                        pricing_id: Number(state.renewalForm.pricingId || 0) || false,
                        start_date: formatTodayISO(),
                        end_date: false,
                        product_id: Number(state.renewalForm.productId || 0) || false,
                        product_name: state.renewalForm.productName || false,
                        source_subscription_id: Number(state.renewalForm.subscriptionId || 0) || false,
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
    } else if (state.formMode === "new" && field === "start_date") {
        state.newSubscriptionForm.startDate = target.value || formatTodayISO();
    } else if (state.formMode === "new" && field === "participant_toggle") {
        toggleParticipant(target.value, target.checked);
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
    if (state.formMode === "new" && field === "subscription_curp") {
        state.newSubscriptionForm.curp = target.value || "";
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
