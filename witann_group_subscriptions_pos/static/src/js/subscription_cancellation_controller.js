/** @odoo-module **/

import {
    addConfiguredProductLineToOrder, ensureProductLoadedInPos, getCurrentOrder, getPos,
    collectSubscriptionConfigsFromOrder, resolveSubscriptionOrderPartner,
} from "./subscription_ticket";

export async function cancelPackageFromPos(source, item, { api, showDialog, isCurrent, onCancelled, onFeeAdded }) {
    if (!item?.can_cancel) { return; }
    const order = getCurrentOrder(source);
    const input = await showDialog({ subscriptionName: item.subscription_name || "",
        hasScheduledChanges: Boolean(item.scheduled_changes?.length) });
    if (!input || !isCurrent()) { return; }
    if (getCurrentOrder(source) !== order) { throw new Error("Cambio el ticket. Abre nuevamente Cancelar paquete."); }
    let quote = await api.preparePackageCancellation(item.subscription_id, input.amount, input.reason,
        getPos(source).session.id, order?.fiscal_position_id?.id || false);
    if (!isCurrent() || getCurrentOrder(source) !== order) { return; }
    if (quote.amount_total === 0) {
        const result = await api.cancelPackageWithoutCharge(quote);
        if (isCurrent()) { await onCancelled(result); }
        return;
    }
    if (collectSubscriptionConfigsFromOrder(order).some((config) =>
        Number(config.source_subscription_id || 0) === Number(item.subscription_id))) {
        throw new Error("El ticket ya contiene una operacion de este paquete. Retirala antes de cancelar.");
    }
    const metadata = { flow: "cancellation_charge", source_subscription_id: item.subscription_id,
        partner_id: quote.partner_id, participant_ids: [quote.partner_id], quantity: 1,
        product_id: quote.product_id, pricing_snapshot: quote };
    await resolveSubscriptionOrderPartner(source, order, [metadata]);
    if (!isCurrent() || getCurrentOrder(source) !== order) { return; }
    const fiscalPositionId = order?.fiscal_position_id?.id || false;
    if (fiscalPositionId !== quote.fiscal_position_id) {
        // Loading the holder can change the ticket's fiscal position. Quote
        // again in that context instead of adding a fee that checkout rejects.
        quote = await api.preparePackageCancellation(item.subscription_id, input.amount, input.reason,
            getPos(source).session.id, fiscalPositionId);
        if (!isCurrent() || getCurrentOrder(source) !== order) { return; }
        if (quote.partner_id !== metadata.partner_id) { throw new Error("Cambio el titular del paquete. Abre nuevamente la cancelacion."); }
        metadata.pricing_snapshot = quote;
        metadata.product_id = quote.product_id;
    }
    const product = await ensureProductLoadedInPos(source, quote.product_id,
        (id, companyId) => api.fetchProductRecord(id, companyId));
    if (!isCurrent() || getCurrentOrder(source) !== order) { return; }
    if ((order?.fiscal_position_id?.id || false) !== quote.fiscal_position_id) {
        throw new Error("Cambio la posicion fiscal del ticket. Abre nuevamente la cancelacion.");
    }
    const result = await addConfiguredProductLineToOrder(source, order, product, {
        quantity: 1, lineUnitPrice: quote.ticket_charge_now, discount: 0, merge: false, metadata,
    });
    if (!result?.line) { throw new Error("No se pudo agregar el cargo. El paquete no se cancelo."); }
    if (isCurrent()) { await onFeeAdded(); }
}
