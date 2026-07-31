/** @odoo-module **/

import { useState } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";

patch(ControlButtons.prototype, {
    setup() {
        super.setup(...arguments);
        this.pos = usePos();
        this.wgsEarlyReceiptState = useState({ printing: false });
    },

    get wgsCanPrintEarlyReceipt() {
        const order = this.pos.get_order();
        return Boolean(
            this.pos.config.wgs_early_receipt_printing &&
                order &&
                order.get_orderlines().length &&
                !this.wgsEarlyReceiptState.printing
        );
    },

    async onWgsPrintEarlyReceipt() {
        if (!this.wgsCanPrintEarlyReceipt) {
            return;
        }

        const order = this.pos.get_order();
        this.wgsEarlyReceiptState.printing = true;
        try {
            // Reuse the native POS printing pipeline; this does not validate payment.
            await this.pos.printReceipt({ order });
        } catch (error) {
            this.env.services.notification.add(
                _t("No se pudo imprimir la precuenta. Revisa la impresora e intenta nuevamente."),
                { type: "danger" }
            );
            throw error;
        } finally {
            this.wgsEarlyReceiptState.printing = false;
        }
    },
});
