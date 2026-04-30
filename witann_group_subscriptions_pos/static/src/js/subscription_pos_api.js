/** @odoo-module **/

export function createSubscriptionPosApi(orm) {
    return {
        async fetchPartnerDirectoryBatch(offset = 0, limit = 500) {
            return orm.call("pos.order", "wgs_get_partner_directory_rows_for_pos", [offset, limit]);
        },
        async fetchPartnerSubscriptionDetail(partnerId) {
            return orm.call("pos.order", "wgs_get_partner_subscription_detail_for_pos", [partnerId]);
        },
        async fetchPartnerRecord(partnerId) {
            return orm.call("pos.order", "wgs_get_partner_record_for_pos", [partnerId || false]);
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
        async validateSubscriptionProductEligibility(partnerId, productId, flow = "new", sourceSubscriptionId = false) {
            return orm.call(
                "pos.order",
                "wgs_validate_subscription_product_eligibility_for_pos",
                [partnerId, productId, flow || "new", sourceSubscriptionId || false]
            );
        },
        async authorizeSubscriptionDiscount(partnerId, productId, flow = "new", discountCode = false, supervisorPin = false, sourceSubscriptionId = false) {
            return orm.call(
                "pos.order",
                "wgs_authorize_subscription_discount_for_pos",
                [partnerId, productId, flow || "new", discountCode || false, supervisorPin || false, sourceSubscriptionId || false]
            );
        },
        async updatePartnerPhoto(partnerId, imageBase64) {
            return orm.call("pos.order", "wgs_update_partner_photo_for_pos", [partnerId, imageBase64 || false]);
        },
        async fetchSubscriptionProductCatalog(searchTerm = "", limit = 200) {
            return orm.call("pos.order", "wgs_get_subscription_product_catalog_for_pos", [searchTerm, limit]);
        },
        async fetchSubscriptionPricing(partnerId = false, productId = false, flow = "new", sourceSubscriptionId = false, pendingMoveId = false, fallback = 0, planId = false, pricingId = false) {
            return orm.call(
                "pos.order",
                "wgs_get_subscription_pricing_for_pos",
                [partnerId || false, productId || false, flow || "new", sourceSubscriptionId || false, pendingMoveId || false, fallback || 0, planId || false, pricingId || false]
            );
        },
        async fetchSubscriptionQuote(partnerId = false, productId = false, flow = "new", sourceSubscriptionId = false, pendingMoveId = false, fallback = 0, planId = false, pricingId = false) {
            return orm.call(
                "pos.order",
                "wgs_get_subscription_quote_for_pos",
                [partnerId || false, productId || false, flow || "new", sourceSubscriptionId || false, pendingMoveId || false, fallback || 0, planId || false, pricingId || false]
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
