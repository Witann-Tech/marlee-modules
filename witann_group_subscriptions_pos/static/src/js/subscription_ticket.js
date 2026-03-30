/** @odoo-module **/

export function getPos(source) {
    if (!source) {
        return null;
    }
    if (source.pos) {
        return source.pos;
    }
    if (source.env && source.env.pos) {
        return source.env.pos;
    }
    return source;
}

export function getCurrentOrder(source) {
    const pos = getPos(source);
    if (!pos) {
        return null;
    }
    if (typeof pos.get_order === "function") {
        return pos.get_order();
    }
    if (typeof pos.getOrder === "function") {
        return pos.getOrder();
    }
    return pos.selectedOrder || pos.order || null;
}

export function getOrderUid(order) {
    if (!order) {
        return null;
    }
    return order.uuid || order.uid || order.order_uuid || order.orderUid || null;
}

export function getOrderLines(order) {
    if (!order) {
        return [];
    }
    if (typeof order.get_orderlines === "function") {
        return order.get_orderlines() || [];
    }
    if (typeof order.getOrderlines === "function") {
        return order.getOrderlines() || [];
    }
    if (Array.isArray(order.lines)) {
        return order.lines;
    }
    if (order.lines && Array.isArray(order.lines.models)) {
        return order.lines.models;
    }
    if (order.lines && typeof order.lines.toArray === "function") {
        const values = order.lines.toArray();
        if (Array.isArray(values)) {
            return values;
        }
    }
    if (Array.isArray(order.orderlines)) {
        return order.orderlines;
    }
    if (order.orderlines && Array.isArray(order.orderlines.models)) {
        return order.orderlines.models;
    }
    return [];
}

export function getPartnerIdFromOrder(order) {
    if (!order) {
        return 0;
    }
    const partner = typeof order.get_partner === "function"
        ? order.get_partner()
        : typeof order.getPartner === "function"
            ? order.getPartner()
            : order.partner || null;
    return Number(partner && partner.id ? partner.id : 0);
}

function setOrderPartner(order, partner) {
    if (!order || !partner || !partner.id) {
        return false;
    }
    if (typeof order.set_partner === "function") {
        order.set_partner(partner);
        return true;
    }
    if (typeof order.setPartner === "function") {
        order.setPartner(partner);
        return true;
    }
    if (typeof order.set_client === "function") {
        order.set_client(partner);
        return true;
    }
    if (typeof order.setClient === "function") {
        order.setClient(partner);
        return true;
    }
    order.partner = partner;
    order.partner_id = partner.id;
    return true;
}

export function setPartnerOnCurrentOrder(source, partner) {
    const pos = getPos(source);
    const order = getCurrentOrder(source);
    if (!partner || !partner.id) {
        return false;
    }
    if (pos && typeof pos.setPartnerToCurrentOrder === "function") {
        pos.setPartnerToCurrentOrder(partner);
        return true;
    }
    return setOrderPartner(order, partner);
}

export function getProductIdFromLine(line) {
    if (!line) {
        return 0;
    }
    if (typeof line.get_product === "function") {
        const product = line.get_product();
        return Number(product && product.id ? product.id : 0);
    }
    if (line.product && line.product.id) {
        return Number(line.product.id);
    }
    if (line.product_id && Array.isArray(line.product_id)) {
        return Number(line.product_id[0] || 0);
    }
    return Number(line.product_id || 0);
}

export function getLineQty(line) {
    if (!line) {
        return 0;
    }
    if (typeof line.get_quantity === "function") {
        return Number(line.get_quantity() || 0);
    }
    if (typeof line.getQuantity === "function") {
        return Number(line.getQuantity() || 0);
    }
    return Number(line.quantity || line.qty || 0);
}

function setLineUnitPrice(line, price) {
    if (!line) {
        return;
    }
    if (typeof line.set_unit_price === "function") {
        line.set_unit_price(price);
    } else if (typeof line.setUnitPrice === "function") {
        line.setUnitPrice(price);
    } else {
        line.price = price;
        line.price_unit = price;
    }

    if (typeof line.set_price_manually === "function") {
        line.set_price_manually(true);
    } else if (typeof line.setPriceManually === "function") {
        line.setPriceManually(true);
    }

    if ("price_manually_set" in line) {
        line.price_manually_set = true;
    }
    if ("priceManuallySet" in line) {
        line.priceManuallySet = true;
    }
}

function setLineDiscount(line, discount) {
    if (!line) {
        return;
    }
    if (typeof line.set_discount === "function") {
        line.set_discount(discount);
        return;
    }
    if (typeof line.setDiscount === "function") {
        line.setDiscount(discount);
        return;
    }
    line.discount = discount;
}

function getSelectedOrderLine(source, maybeOrder = null) {
    const order = maybeOrder || getCurrentOrder(source);
    if (!order) {
        return null;
    }
    if (typeof order.get_selected_orderline === "function") {
        return order.get_selected_orderline();
    }
    if (typeof order.getSelectedOrderline === "function") {
        return order.getSelectedOrderline();
    }
    if (typeof order.get_selected_order_line === "function") {
        return order.get_selected_order_line();
    }
    if (typeof order.getSelectedOrderLine === "function") {
        return order.getSelectedOrderLine();
    }
    return order.selected_orderline || order.selectedOrderline || order.selectedOrderLine || null;
}

async function addProductToOrder(source, order, product, options = {}) {
    const pos = getPos(source);
    if (!order || !product || !pos) {
        return null;
    }
    const payload = {
        quantity: 1,
        merge: false,
        ...options,
    };
    if (typeof pos.addLineToCurrentOrder === "function") {
        const line = await pos.addLineToCurrentOrder({ product_id: product }, payload);
        return line || getSelectedOrderLine(source, order);
    }
    if (typeof pos.addLineToOrder === "function") {
        const line = await pos.addLineToOrder(order, { product_id: product }, payload);
        return line || getSelectedOrderLine(source, order);
    }
    if (typeof order.add_product === "function") {
        order.add_product(product, payload);
        return getSelectedOrderLine(source, order);
    }
    if (typeof order.addProduct === "function") {
        order.addProduct(product, payload);
        return getSelectedOrderLine(source, order);
    }
    return null;
}

export async function addConfiguredProductLineToOrder(source, order, product, options = {}) {
    const {
        quantity = 1,
        lineUnitPrice = null,
        discount = 0,
        merge = false,
        metadata = null,
        charge = null,
    } = options;
    if (!order || !product) {
        return null;
    }

    const beforeLines = getOrderLines(order);
    const beforeCount = beforeLines.length;
    const beforeSet = new Set(beforeLines);
    const beforeSelectedLine = getSelectedOrderLine(source, order);

    const resolvedLineUnitPrice = charge && typeof charge === "object"
        ? Number(charge.ticketUnitPrice || 0)
        : Number(lineUnitPrice || 0);

    const addResult = await addProductToOrder(source, order, product, {
        quantity,
        merge,
        price: resolvedLineUnitPrice,
    });
    await waitForNextTick();
    await waitForNextTick();

    const afterLines = getOrderLines(order);
    let targetLine = afterLines.find((line) => !beforeSet.has(line)) || null;
    if (!targetLine && addResult && typeof addResult === "object") {
        targetLine = addResult;
    }
    if (!targetLine) {
        const selectedAfter = getSelectedOrderLine(source, order);
        if (selectedAfter && selectedAfter !== beforeSelectedLine) {
            targetLine = selectedAfter;
        }
    }
    if (!targetLine && afterLines.length <= beforeCount) {
        return { line: null, reason: "not_added" };
    }
    if (!targetLine) {
        return { line: null, reason: "not_identified" };
    }

    setLineUnitPrice(targetLine, Number(resolvedLineUnitPrice || 0));
    if (Number(discount || 0)) {
        setLineDiscount(targetLine, Number(discount || 0));
    }
    if (metadata) {
        targetLine.wgsSubscriptionConfig = metadata;
    }
    return { line: targetLine, reason: null };
}

export function findProductInPos(source, productId) {
    const pos = getPos(source);
    if (!pos || !productId) {
        return null;
    }
    const numericId = Number(productId);
    const productCollection = pos.models && pos.models["product.product"];
    if (productCollection && typeof productCollection.get === "function") {
        const product = productCollection.get(numericId);
        if (product) {
            return product;
        }
    }
    if (pos.db) {
        if (typeof pos.db.get_product_by_id === "function") {
            const product = pos.db.get_product_by_id(numericId);
            if (product) {
                return product;
            }
        }
        if (pos.db.product_by_id && pos.db.product_by_id[numericId]) {
            return pos.db.product_by_id[numericId];
        }
    }
    if (productCollection) {
        if (typeof productCollection.get === "function") {
            const product = productCollection.get(numericId);
            if (product) {
                return product;
            }
        }
        if (typeof productCollection.getAll === "function") {
            return (productCollection.getAll() || []).find((item) => Number(item.id) === numericId) || null;
        }
        if (Array.isArray(productCollection)) {
            return productCollection.find((item) => Number(item.id) === numericId) || null;
        }
    }
    if (Array.isArray(pos.products)) {
        return pos.products.find((item) => Number(item.id) === numericId) || null;
    }
    return null;
}

export function findPartnerInPos(source, partnerId) {
    const pos = getPos(source);
    if (!pos || !partnerId) {
        return null;
    }
    const numericId = Number(partnerId);
    const partnerCollection = pos.models && pos.models["res.partner"];
    if (partnerCollection && typeof partnerCollection.get === "function") {
        const partner = partnerCollection.get(numericId);
        if (partner) {
            return partner;
        }
    }
    if (pos.db) {
        if (typeof pos.db.get_partner_by_id === "function") {
            const partner = pos.db.get_partner_by_id(numericId);
            if (partner) {
                return partner;
            }
        }
        if (pos.db.partner_by_id && pos.db.partner_by_id[numericId]) {
            return pos.db.partner_by_id[numericId];
        }
    }
    if (partnerCollection) {
        if (typeof partnerCollection.get === "function") {
            const partner = partnerCollection.get(numericId);
            if (partner) {
                return partner;
            }
        }
        if (typeof partnerCollection.getAll === "function") {
            return (partnerCollection.getAll() || []).find((item) => Number(item.id) === numericId) || null;
        }
        if (Array.isArray(partnerCollection)) {
            return partnerCollection.find((item) => Number(item.id) === numericId) || null;
        }
    }
    return null;
}

export function getAllLocalPosProducts(source) {
    const pos = getPos(source);
    if (!pos) {
        return [];
    }
    const productCollection = pos.models && pos.models["product.product"];
    if (productCollection) {
        if (typeof productCollection.getAll === "function") {
            return productCollection.getAll() || [];
        }
        if (Array.isArray(productCollection.records)) {
            return productCollection.records;
        }
        if (Array.isArray(productCollection)) {
            return productCollection;
        }
    }
    if (pos.db && pos.db.product_by_id) {
        return Object.values(pos.db.product_by_id);
    }
    if (Array.isArray(pos.products)) {
        return pos.products;
    }
    return [];
}

export function collectSubscriptionConfigsFromOrder(order) {
    const output = [];
    for (const line of getOrderLines(order)) {
        if (!line || !line.wgsSubscriptionConfig) {
            continue;
        }
        const config = { ...line.wgsSubscriptionConfig };
        config.product_id = getProductIdFromLine(line) || config.product_id || false;
        config.quantity = Math.abs(getLineQty(line) || 1);
        output.push(config);
    }
    return output;
}

export function getSubscriptionPartnerIdsFromOrder(order) {
    const ids = [];
    for (const config of collectSubscriptionConfigsFromOrder(order)) {
        const partnerId = Number(config.partner_id || 0);
        if (partnerId > 0) {
            ids.push(partnerId);
        }
    }
    return [...new Set(ids)];
}

export function waitForNextTick() {
    return new Promise((resolve) => window.setTimeout(resolve, 0));
}
