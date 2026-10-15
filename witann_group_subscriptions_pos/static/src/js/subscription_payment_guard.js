/** @odoo-module **/

import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { onMounted, onPatched } from "@odoo/owl";
import {
    collectMembershipRefundsFromOrder, collectSubscriptionConfigsFromOrder,
    getCurrentCompanyId, getLineQty, getOrderLines, getOrderUid,
    getPartnerIdFromOrder, getProductIdFromLine,
} from "./subscription_ticket";
import {
    clearInvoiceFlag, disableInvoiceControls, getOrderFromPaymentScreen, installInvoiceControlGuard,
} from "./subscription_invoice_lock";

export async function stageSubscriptionConfigsForOrder(orm, order, pos) {
    const refunds = collectMembershipRefundsFromOrder(order);
    if (refunds.length) {
        await orm.call("pos.order", "wgs_validate_subscription_refunds_for_pos", [refunds]);
    }
    const configs = collectSubscriptionConfigsFromOrder(order).filter((config) => config.flow !== "cancellation_refund");
    const hasMembership = getOrderLines(order).some((line) =>
        getLineQty(line) > 0 && line.product_id?.recurring_invoice
    );
    if (!configs.length && !hasMembership) {
        return { ok: true, skipped: true };
    }
    const lines = getOrderLines(order).map((line) => ({
        uuid: line.uuid,
        product_id: getProductIdFromLine(line),
        qty: getLineQty(line),
        price_unit: Number(line.price_unit || 0),
        discount: Number(line.discount || 0),
    }));
    const rawIds = [getOrderUid(order), order && order.uid, order && order.uuid].filter(Boolean);
    const orderIds = [...new Set(rawIds.map((value) => String(value).trim()).filter(Boolean))];
    if (!orderIds.length) {
        return { ok: false, reason: "missing_uuid" };
    }
    let lastResult = { ok: true };
    for (const orderId of orderIds) {
        lastResult = await orm.call("pos.order", "wgs_stage_subscription_config_for_uuid", [orderId, configs, {
            partner_id: getPartnerIdFromOrder(order), company_id: getCurrentCompanyId(pos), lines,
        }]);
        if (!lastResult || !lastResult.ok) {
            return lastResult || { ok: false, reason: "unknown" };
        }
    }
    return lastResult;
}

// One PaymentScreen extension owns both commercial preflight and ticket-only policy.
patch(PaymentScreen.prototype, {
    setup() {
        super.setup(...arguments);
        this.orm = this.orm || useService("orm");
        this.notification = this.notification || useService("notification");
        installInvoiceControlGuard();
        onMounted(() => this.wgsDisableInvoiceControls());
        onPatched(() => this.wgsDisableInvoiceControls());
    },

    wgsDisableInvoiceControls() {
        clearInvoiceFlag(getOrderFromPaymentScreen(this));
        disableInvoiceControls(this.el || document);
    },

    toggleIsToInvoice() {
        clearInvoiceFlag(getOrderFromPaymentScreen(this));
        this.notification?.add(_t("Facturación deshabilitada en POS. Emite solo ticket."), { type: "warning" });
        this.wgsDisableInvoiceControls();
        return false;
    },

    async validateOrder() {
        const order = getOrderFromPaymentScreen(this);
        clearInvoiceFlag(order);
        try {
            const result = await stageSubscriptionConfigsForOrder(this.orm, order, this.pos);
            if (result && result.ok === false) {
                window.alert(_t("No se pudo preparar la configuracion de suscripcion para esta venta. Actualiza el modulo y vuelve a intentar."));
                return;
            }
        } catch (error) {
            console.error("Error al preparar configuracion de suscripcion antes del cobro POS", error);
            window.alert(error?.data?.message || error?.message || _t("No se pudo preparar la configuracion de suscripcion antes del cobro."));
            return;
        }
        return super.validateOrder(...arguments);
    },
});
