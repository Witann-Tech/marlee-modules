/** @odoo-module **/

export function createSubscriptionPosApi(orm) {
    return {
        async fetchPartnerDirectorySummary(options = {}) {
            return orm.call("pos.order", "wgs_get_partner_directory_summary_for_pos", [{
                company_id: options.companyId || options.company_id || false,
            }]);
        },
        async fetchPartnerDirectoryBatch(offset = 0, limit = 500, options = {}) {
            return orm.call(
                "pos.order",
                "wgs_get_partner_directory_rows_for_pos",
                [
                    offset,
                    limit,
                    options.stateFilter || "actionable",
                    options.searchTerm || "",
                    options.companyId || options.company_id || false,
                ]
            );
        },
        async fetchPartnerDirectoryRow(partnerId, options = {}) {
            return orm.call("pos.order", "wgs_get_partner_directory_row_for_pos", [
                partnerId || false,
                options.companyId || options.company_id || false,
            ]);
        },
        async searchSubscriptionParticipants(searchTerm = "", limit = 120) {
            return orm.call(
                "pos.order",
                "wgs_search_subscription_participants_for_pos",
                [searchTerm || "", limit || 120]
            );
        },
        async fetchPartnerSubscriptionDetail(partnerId) {
            return orm.call("pos.order", "wgs_get_partner_subscription_detail_for_pos", [partnerId]);
        },
        async fetchAccessEventLog(options = {}) {
            return orm.call("pos.order", "wgs_get_access_event_log_for_pos", [options || {}]);
        },
        async fetchPosSalesHistory(options = {}) {
            return orm.call("pos.order", "wgs_get_pos_sales_history_for_pos", [options || {}]);
        },
        async openAccessDoor(deviceId, options = {}) {
            return orm.call("pos.order", "wgs_open_access_door_for_pos", [deviceId || false, options || {}]);
        },
        async blockPartnerAccess(partnerId, reason) {
            return orm.call("pos.order", "wgs_block_partner_access_for_pos", [partnerId || false, reason || ""]);
        },
        async unblockPartnerAccess(partnerId) {
            return orm.call("pos.order", "wgs_unblock_partner_access_for_pos", [partnerId || false]);
        },
        async grantExternalAccess(partnerId, provider, options = {}) {
            return orm.call("pos.order", "wgs_grant_external_access_for_pos", [partnerId || false, provider || "", options || {}]);
        },
        async fetchPartnerRecord(partnerId) {
            return orm.call("pos.order", "wgs_get_partner_record_for_pos", [partnerId || false]);
        },
        async fetchProductRecord(productId, companyId = false) {
            return orm.call("pos.order", "wgs_get_product_record_for_pos", [productId || false, companyId || false]);
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
        async authorizeSubscriptionDiscount(partnerId, productId, flow = "new", discountPercent = 0, supervisorPin = false, sourceSubscriptionId = false) {
            return orm.call(
                "pos.order",
                "wgs_authorize_subscription_discount_for_pos",
                [partnerId, productId, flow || "new", discountPercent || 0, supervisorPin || false, sourceSubscriptionId || false]
            );
        },
        async updatePartnerPhoto(partnerId, imageBase64) {
            return orm.call("pos.order", "wgs_update_partner_photo_for_pos", [partnerId, imageBase64 || false]);
        },
        async fetchSubscriptionProductCatalog(searchTerm = "", limit = 200, companyId = false) {
            return orm.call("pos.order", "wgs_get_subscription_product_catalog_for_pos", [searchTerm, limit, companyId || false]);
        },
        async fetchSubscriptionPricing(partnerId = false, productId = false, flow = "new", sourceSubscriptionId = false, pendingMoveId = false, fallback = 0, planId = false, pricingId = false, startDate = false) {
            return orm.call(
                "pos.order",
                "wgs_get_subscription_pricing_for_pos",
                [partnerId || false, productId || false, flow || "new", sourceSubscriptionId || false, pendingMoveId || false, fallback || 0, planId || false, pricingId || false, startDate || false]
            );
        },
        async fetchSubscriptionQuote(partnerId = false, productId = false, flow = "new", sourceSubscriptionId = false, pendingMoveId = false, fallback = 0, planId = false, pricingId = false, startDate = false) {
            return orm.call(
                "pos.order",
                "wgs_get_subscription_quote_for_pos",
                [partnerId || false, productId || false, flow || "new", sourceSubscriptionId || false, pendingMoveId || false, fallback || 0, planId || false, pricingId || false, startDate || false]
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
