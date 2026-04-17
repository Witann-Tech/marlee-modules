/** @odoo-module **/

export function createSubscriptionPosApi(orm) {
    return {
        async fetchPartnerDirectoryBatch(offset = 0, limit = 500) {
            return orm.call("pos.order", "wgs_get_partner_directory_rows_for_pos", [offset, limit]);
        },
        async fetchPartnerSubscriptionDetail(partnerId) {
            return orm.call("pos.order", "wgs_get_partner_subscription_detail_for_pos", [partnerId]);
        },
        async createPartner(values) {
            return orm.call("pos.order", "wgs_create_partner_for_pos", [values || {}]);
        },
        async updatePartnerCurp(partnerId, curp) {
            return orm.call("pos.order", "wgs_update_partner_curp_for_pos", [partnerId, curp || false]);
        },
        async updatePartner(partnerId, values) {
            return orm.call("pos.order", "wgs_update_partner_for_pos", [partnerId, values || {}]);
        },
        async updatePartnerPhoto(partnerId, imageBase64) {
            return orm.call("pos.order", "wgs_update_partner_photo_for_pos", [partnerId, imageBase64 || false]);
        },
        async fetchSubscriptionProductCatalog(searchTerm = "", limit = 200) {
            return orm.call("pos.order", "wgs_get_subscription_product_catalog_for_pos", [searchTerm, limit]);
        },
        async fetchSubscriptionCharge(partnerId, productId, fallback = 0, planId = false, pricingId = false) {
            return orm.call(
                "pos.order",
                "wgs_get_subscription_charge_for_pos",
                [partnerId || false, productId, fallback || 0, planId || false, pricingId || false]
            );
        },
        async fetchSubscriptionRenewalCharge(subscriptionId, productId = false, planId = false, pricingId = false) {
            return orm.call(
                "pos.order",
                "wgs_get_subscription_renewal_charge_for_pos",
                [subscriptionId, productId || false, planId || false, pricingId || false]
            );
        },
        async fetchSubscriptionReenrollCharge(subscriptionId, productId = false, planId = false, pricingId = false) {
            return orm.call(
                "pos.order",
                "wgs_get_subscription_reenroll_charge_for_pos",
                [subscriptionId, productId || false, planId || false, pricingId || false]
            );
        },
        async fetchSubscriptionUpsaleCharge(subscriptionId, productId, fallback = 0, planId = false, pricingId = false) {
            return orm.call(
                "pos.order",
                "wgs_get_subscription_upsale_charge_for_pos",
                [subscriptionId, productId, fallback || 0, planId || false, pricingId || false]
            );
        },
        async fetchSubscriptionPendingCharge(subscriptionId, pendingMoveId = false) {
            return orm.call(
                "pos.order",
                "wgs_get_subscription_pending_charge_for_pos",
                [subscriptionId, pendingMoveId || false]
            );
        },
        async fetchSubscriptionCancellationRefund(subscriptionId) {
            return orm.call(
                "pos.order",
                "wgs_get_subscription_cancellation_refund_for_pos",
                [subscriptionId]
            );
        },
        async saveSubscriptionParticipants(subscriptionId, participantIds) {
            return orm.call(
                "pos.order",
                "wgs_update_subscription_participants_for_pos",
                [subscriptionId, participantIds || []]
            );
        },
        async resyncSubscriptionAccess(subscriptionId) {
            return orm.call(
                "pos.order",
                "wgs_resync_subscription_access_for_pos",
                [subscriptionId]
            );
        },
    };
}
