/** @odoo-module **/

import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { onMounted, onPatched } from "@odoo/owl";

const STYLE_ID = "wgs-pos-invoice-lock-style";
const INVOICE_TEXT_RE = /(invoice|factur|to_invoice)/i;
const PRODUCT_INFORMATION_ACTION_RE = /(?:product.*info|info.*product)/i;
const CONTROL_SELECTOR = "button, .button, [role='button'], .control-button, .payment-button, .js_invoice";
let invoiceGuardObserver = null;
let invoiceGuardEventsInstalled = false;

function ensureInvoiceLockStyle() {
    if (document.getElementById(STYLE_ID)) {
        return;
    }
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
        .wgs-pos-invoice-disabled {
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

function isProductInformationControl(element) {
    if (!element) {
        return false;
    }
    const label = (element.textContent || "").trim().toLocaleLowerCase();
    return (
        label === "informacion" ||
        label === "información" ||
        PRODUCT_INFORMATION_ACTION_RE.test(elementInvoiceHaystack(element))
    );
}

function disableInvoiceControl(control) {
    if (!isInvoiceControl(control)) {
        return;
    }
    control.classList.add("wgs-pos-invoice-disabled");
    control.setAttribute("aria-disabled", "true");
    control.setAttribute("title", _t("Facturación deshabilitada en POS. Emite solo ticket."));
    if ("disabled" in control) {
        control.disabled = true;
    }
}

function disableProductInformationControl(control) {
    if (!isProductInformationControl(control)) {
        return;
    }
    control.classList.add("wgs-pos-invoice-disabled");
    control.setAttribute("aria-disabled", "true");
    control.setAttribute("title", _t("La edición de productos está deshabilitada en POS."));
    if ("disabled" in control) {
        control.disabled = true;
    }
}

function disableInvoiceControls(root) {
    const scope = root || document;
    if (scope.nodeType === Node.ELEMENT_NODE && scope.matches(CONTROL_SELECTOR)) {
        disableInvoiceControl(scope);
        disableProductInformationControl(scope);
    }
    if (!scope.querySelectorAll) {
        return;
    }
    for (const control of scope.querySelectorAll(CONTROL_SELECTOR)) {
        disableInvoiceControl(control);
        disableProductInformationControl(control);
    }
}

function blockInvoiceControlEvent(event) {
    const control = event.target?.closest?.(CONTROL_SELECTOR);
    if (!isInvoiceControl(control) && !isProductInformationControl(control)) {
        return;
    }
    disableInvoiceControl(control);
    disableProductInformationControl(control);
    event.preventDefault();
    event.stopImmediatePropagation();
}

function installInvoiceControlGuard() {
    if (typeof document === "undefined") {
        return;
    }
    ensureInvoiceLockStyle();
    disableInvoiceControls(document);
    if (!invoiceGuardEventsInstalled) {
        invoiceGuardEventsInstalled = true;
        document.addEventListener("click", blockInvoiceControlEvent, true);
        document.addEventListener("keydown", (event) => {
            if (event.key === "Enter" || event.key === " ") {
                blockInvoiceControlEvent(event);
            }
        }, true);
    }
    if (!invoiceGuardObserver && typeof MutationObserver !== "undefined" && document.body) {
        invoiceGuardObserver = new MutationObserver((mutations) => {
            for (const mutation of mutations) {
                for (const node of mutation.addedNodes) {
                    if (node.nodeType === Node.ELEMENT_NODE) {
                        disableInvoiceControls(node);
                    }
                }
            }
        });
        invoiceGuardObserver.observe(document.body, {
            childList: true,
            subtree: true,
        });
    }
}

if (typeof document !== "undefined") {
    if (document.body) {
        installInvoiceControlGuard();
    } else {
        document.addEventListener("DOMContentLoaded", installInvoiceControlGuard, { once: true });
    }
}

patch(PaymentScreen.prototype, {
    setup() {
        super.setup(...arguments);
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
