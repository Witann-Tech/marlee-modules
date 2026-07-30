/** @odoo-module **/

import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { onMounted, onPatched, onWillUnmount } from "@odoo/owl";

const STYLE_ID = "wgs-pos-invoice-lock-style";
const INVOICE_TEXT_RE = /(invoice|factur|to_invoice)/i;

function ensureInvoiceLockStyle() {
    if (document.getElementById(STYLE_ID)) {
        return;
    }
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
        .payment-screen .wgs-pos-invoice-disabled {
            opacity: 0.45 !important;
            cursor: not-allowed !important;
            pointer-events: none !important;
            filter: grayscale(1);
        }
    `;
    document.head.appendChild(style);
}

function getOrderFromPaymentScreen(screen) {
    if (!screen) {
        return null;
    }
    if (screen.currentOrder) {
        return screen.currentOrder;
    }
    if (screen.pos && typeof screen.pos.get_order === "function") {
        return screen.pos.get_order();
    }
    if (screen.pos && typeof screen.pos.getOrder === "function") {
        return screen.pos.getOrder();
    }
    return screen.pos ? screen.pos.selectedOrder || screen.pos.order || null : null;
}

function clearInvoiceFlag(order) {
    if (!order) {
        return;
    }
    if (typeof order.set_to_invoice === "function") {
        order.set_to_invoice(false);
    }
    if (typeof order.setToInvoice === "function") {
        order.setToInvoice(false);
    }
    if ("to_invoice" in order) {
        order.to_invoice = false;
    }
    if ("toInvoice" in order) {
        order.toInvoice = false;
    }
    if ("is_to_invoice" in order && typeof order.is_to_invoice !== "function") {
        order.is_to_invoice = false;
    }
}

function elementInvoiceHaystack(element) {
    const values = [
        element.textContent || "",
        element.className || "",
        element.getAttribute("name") || "",
        element.getAttribute("title") || "",
        element.getAttribute("aria-label") || "",
        element.getAttribute("data-action") || "",
        element.getAttribute("data-testid") || "",
    ];
    if (element.dataset) {
        values.push(...Object.values(element.dataset));
    }
    return values.join(" ");
}

function isInvoiceControl(element) {
    if (!element) {
        return false;
    }
    return INVOICE_TEXT_RE.test(elementInvoiceHaystack(element));
}

function disableInvoiceControls(root) {
    const scope = root || document.querySelector(".payment-screen") || document;
    const controls = scope.querySelectorAll("button, .button, [role='button'], .control-button, .payment-button, .js_invoice");
    for (const control of controls) {
        if (!isInvoiceControl(control)) {
            continue;
        }
        control.classList.add("wgs-pos-invoice-disabled");
        control.setAttribute("aria-disabled", "true");
        control.setAttribute("title", _t("Facturación deshabilitada en POS. Emite solo ticket."));
        if ("disabled" in control) {
            control.disabled = true;
        }
    }
}

patch(PaymentScreen.prototype, {
    setup() {
        super.setup(...arguments);
        this.notification = this.notification || useService("notification");
        ensureInvoiceLockStyle();
        onMounted(() => this.wgsDisableInvoiceControls());
        onPatched(() => this.wgsDisableInvoiceControls());
        onWillUnmount(() => {
            if (this.wgsInvoiceLockObserver) {
                this.wgsInvoiceLockObserver.disconnect();
                this.wgsInvoiceLockObserver = null;
            }
        });
    },

    wgsDisableInvoiceControls() {
        clearInvoiceFlag(getOrderFromPaymentScreen(this));
        disableInvoiceControls(this.el || document.querySelector(".payment-screen") || document);
        if (!this.wgsInvoiceLockObserver && typeof MutationObserver !== "undefined") {
            this.wgsInvoiceLockObserver = new MutationObserver(() => {
                clearInvoiceFlag(getOrderFromPaymentScreen(this));
                disableInvoiceControls(this.el || document.querySelector(".payment-screen") || document);
            });
            this.wgsInvoiceLockObserver.observe(this.el || document.body, {
                childList: true,
                subtree: true,
            });
        }
    },

    toggleIsToInvoice() {
        clearInvoiceFlag(getOrderFromPaymentScreen(this));
        if (this.notification) {
            this.notification.add(_t("Facturación deshabilitada en POS. Emite solo ticket."), {
                type: "warning",
            });
        }
        this.wgsDisableInvoiceControls();
        return false;
    },

    async validateOrder() {
        clearInvoiceFlag(getOrderFromPaymentScreen(this));
        return super.validateOrder(...arguments);
    },
});
