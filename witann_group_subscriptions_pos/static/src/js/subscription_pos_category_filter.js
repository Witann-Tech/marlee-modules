/** @odoo-module **/

import { PosCategory } from "@point_of_sale/app/models/pos_category";
import { ProductTemplate } from "@point_of_sale/app/models/product_template";

function isSubscriptionProductTemplate(product) {
    if (!product) {
        return false;
    }
    if (product.recurring_invoice || product.product_tmpl_id?.recurring_invoice) {
        return true;
    }
    const variants = Array.isArray(product.product_variant_ids) ? product.product_variant_ids : [];
    return variants.some((variant) => variant?.recurring_invoice || variant?.product_tmpl_id?.recurring_invoice);
}

const originalCanBeDisplayed = Object.getOwnPropertyDescriptor(ProductTemplate.prototype, "canBeDisplayed");

Object.defineProperty(ProductTemplate.prototype, "canBeDisplayed", {
    get() {
        const canBeDisplayed = originalCanBeDisplayed?.get ? originalCanBeDisplayed.get.call(this) : Boolean(this.active && this.available_in_pos);
        return Boolean(canBeDisplayed && !isSubscriptionProductTemplate(this));
    },
    configurable: true,
});

Object.defineProperty(PosCategory.prototype, "hasProductsToShow", {
    get() {
        return this.associatedProducts.some((product) => product.canBeDisplayed);
    },
    configurable: true,
});
