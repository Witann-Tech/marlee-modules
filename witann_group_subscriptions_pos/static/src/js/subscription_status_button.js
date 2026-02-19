/** @odoo-module **/

import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { Component } from "@odoo/owl";

export class SubscriptionStatusButton extends Component {
    static template = "witann_group_subscriptions_pos.SubscriptionStatusButton";

    setup() {
        this.pos = usePos();
        this.orm = useService("orm");
        this.dialog = useService("dialog");
    }

    async onClick() {
        const order = this.pos.get_order();
        const partner = order && order.get_partner();

        if (!partner) {
            this.dialog.add(AlertDialog, {
                title: _t("Cliente no seleccionado"),
                body: _t("Selecciona un cliente para consultar su vigencia de paquetes."),
            });
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
            this.dialog.add(AlertDialog, {
                title: _t("Error al consultar vigencia"),
                body: _t("No se pudo consultar la vigencia en este momento."),
            });
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

        this.dialog.add(AlertDialog, {
            title: `${_t("Vigencia de paquetes")} - ${partner.name}`,
            body,
        });
    }
}

ProductScreen.addControlButton({
    component: SubscriptionStatusButton,
    condition: () => true,
});
