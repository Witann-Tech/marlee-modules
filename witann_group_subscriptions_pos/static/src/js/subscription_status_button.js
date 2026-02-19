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
        const order = this.env.pos && this.env.pos.get_order ? this.env.pos.get_order() : null;
        const partner = order && order.get_partner();

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
});
