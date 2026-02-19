/** @odoo-module **/

import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";

patch(ControlButtons.prototype, {
    setup() {
        super.setup(...arguments);
        this.orm = useService("orm");
    },

    async onClickSubscriptionStatus() {
        const order = this._getCurrentOrder();
        const partner = this._getCurrentPartner(order);

        if (!partner) {
            window.alert(_t("Selecciona un cliente para consultar su vigencia de paquetes."));
            return;
        }

        let result;
        try {
            result = await this.orm.call(
                "sale.order",
                "get_partner_subscription_status_for_pos",
                [partner.id]
            );
        } catch (error) {
            window.alert(_t("No se pudo consultar la vigencia en este momento."));
            console.error("Error al consultar vigencia de suscripción en POS", error);
            return;
        }

        const items = result.items || [];
        let body;

        if (!items.length) {
            body = _t("No hay paquetes de suscripción para este participante.");
        } else {
            body = items
                .map((item) => {
                    const packages = (item.package_names || []).join(", ") || item.subscription_name;
                    const periodStart = item.period_start || _t("N/D");
                    const validUntil = item.valid_until || _t("N/D");
                    return `${item.status_label}: ${packages}\nPeriodo: ${periodStart} a ${validUntil}\n${item.reason}`;
                })
                .join("\n\n");
        }

        window.alert(`${_t("Vigencia de paquetes")} - ${partner.name}\n\n${body}`);
    },

    _getCurrentOrder() {
        if (this.currentOrder) {
            return this.currentOrder;
        }
        if (this.props && this.props.order) {
            return this.props.order;
        }
        if (this.pos && this.pos.get_order) {
            return this.pos.get_order();
        }
        if (this.env && this.env.pos && this.env.pos.get_order) {
            return this.env.pos.get_order();
        }
        return null;
    },

    _getCurrentPartner(order) {
        if (this.props && this.props.partner && this.props.partner.id) {
            return this.props.partner;
        }

        if (!order) {
            return null;
        }

        if (typeof order.get_partner === "function") {
            const partner = order.get_partner();
            if (partner) {
                return partner;
            }
        }

        if (order.partner && order.partner.id) {
            return order.partner;
        }

        const partnerField = order.partner_id;
        let partnerId = null;

        if (Array.isArray(partnerField) && partnerField.length) {
            partnerId = partnerField[0];
        } else if (typeof partnerField === "number") {
            partnerId = partnerField;
        } else if (partnerField && typeof partnerField === "object" && partnerField.id) {
            return partnerField;
        }

        if (!partnerId) {
            return null;
        }

        if (this.pos && this.pos.models && this.pos.models["res.partner"] && this.pos.models["res.partner"].get) {
            return this.pos.models["res.partner"].get(partnerId) || { id: partnerId, name: _t("Cliente") };
        }

        if (this.pos && this.pos.db && this.pos.db.get_partner_by_id) {
            return this.pos.db.get_partner_by_id(partnerId) || { id: partnerId, name: _t("Cliente") };
        }

        return { id: partnerId, name: _t("Cliente") };
    },
});
