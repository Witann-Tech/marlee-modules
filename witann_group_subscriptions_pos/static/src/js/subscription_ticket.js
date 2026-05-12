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

export function getCurrentCompanyId(source) {
    const pos = getPos(source);
    if (!pos) {
        return 0;
    }
    const candidates = [
        pos.company,
        pos.company_id,
        pos.companyId,
        pos.config && pos.config.company_id,
        pos.config && pos.config.companyId,
    ];
    for (const value of candidates) {
        if (!value) {
            continue;
        }
        if (typeof value === "number") {
            return Number(value || 0);
        }
        if (Array.isArray(value)) {
            return Number(value[0] || 0);
        }
        if (typeof value === "object" && value.id) {
            return Number(value.id || 0);
        }
    }
    return 0;
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

export async function ensurePartnerLoadedInPos(source, partnerId, fetchPartnerRecord) {
    const numericId = Number(partnerId || 0);
    if (numericId <= 0) {
        return null;
    }
    const localPartner = findPartnerInPos(source, numericId);
    if (localPartner) {
        return localPartner;
    }
    if (typeof fetchPartnerRecord !== "function") {
        return null;
    }
    const partnerData = await fetchPartnerRecord(numericId);
    if (!partnerData || Number(partnerData.id || 0) !== numericId) {
        return null;
    }
    const pos = getPos(source);
    if (pos && pos.db && typeof pos.db.add_partners === "function") {
        pos.db.add_partners([partnerData]);
    }
    return findPartnerInPos(source, numericId) || partnerData;
}

function addProductToLocalPosCaches(pos, productData) {
    if (!pos || !productData || !productData.id) {
        return false;
    }
    if (pos.db && typeof pos.db.add_products === "function") {
        pos.db.add_products([productData]);
    } else if (pos.db) {
        if (!pos.db.product_by_id) {
            pos.db.product_by_id = {};
        }
        pos.db.product_by_id[Number(productData.id)] = productData;
    }

    if (Array.isArray(pos.products) && !pos.products.some((item) => Number(item && item.id) === Number(productData.id))) {
        pos.products.push(productData);
    }

    const productCollection = pos.models && pos.models["product.product"];
    if (productCollection) {
        if (Array.isArray(productCollection.records) && !productCollection.records.some((item) => Number(item && item.id) === Number(productData.id))) {
            productCollection.records.push(productData);
        } else if (Array.isArray(productCollection) && !productCollection.some((item) => Number(item && item.id) === Number(productData.id))) {
            productCollection.push(productData);
        }
    }
    return true;
}

async function loadProductWithNativePosApi(source, productId) {
    const pos = getPos(source);
    const numericId = Number(productId || 0);
    if (!pos || numericId <= 0) {
        return null;
    }
    if (pos.data && typeof pos.data.searchRead === "function") {
        const products = await pos.data.searchRead("product.product", [["id", "=", numericId]]);
        const loadedProducts = Array.isArray(products) ? products : [];
        if (loadedProducts.length) {
            if (typeof pos._loadMissingPricelistItems === "function") {
                await pos._loadMissingPricelistItems(loadedProducts);
            }
            if (typeof pos.processProductAttributesByProducts === "function") {
                await pos.processProductAttributesByProducts(loadedProducts);
            }
            return findProductInPos(source, numericId);
        }
    }
    if (typeof pos._addProducts === "function") {
        await pos._addProducts([numericId]);
        return findProductInPos(source, numericId);
    }
    if (typeof pos.addProducts === "function") {
        await pos.addProducts([numericId]);
        return findProductInPos(source, numericId);
    }
    return null;
}

export async function ensureProductLoadedInPos(source, productId, fetchProductRecord) {
    const numericId = Number(productId || 0);
    if (numericId <= 0) {
        return null;
    }
    const localProduct = findProductInPos(source, numericId);
    if (localProduct) {
        return localProduct;
    }
    const nativeProduct = await loadProductWithNativePosApi(source, numericId);
    if (nativeProduct) {
        return nativeProduct;
    }
    if (typeof fetchProductRecord !== "function") {
        return null;
    }
    const productData = await fetchProductRecord(numericId, getCurrentCompanyId(source) || false);
    if (!productData || Number(productData.id || 0) !== numericId) {
        return null;
    }
    addProductToLocalPosCaches(getPos(source), productData);
    return findProductInPos(source, numericId) || productData;
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
    const quantity = Number(options.quantity || options.qty || 1) || 1;
    const price = Number(
        options.price_unit !== undefined
            ? options.price_unit
            : (options.price !== undefined ? options.price : 0)
    ) || 0;
    const legacyPayload = {
        quantity,
        merge: false,
        ...options,
        price,
    };
    const lineValues = {
        product_id: product,
        qty: quantity,
        price_unit: price,
    };
    const lineOptions = {
        ...options,
        quantity,
    };
    delete lineOptions.price;
    delete lineOptions.price_unit;

    if (typeof pos.addLineToCurrentOrder === "function") {
        const line = await pos.addLineToCurrentOrder(lineValues, lineOptions, false);
        return line || getSelectedOrderLine(source, order);
    }
    if (typeof pos.addLineToOrder === "function") {
        const line = await pos.addLineToOrder(lineValues, order, lineOptions, false);
        return line || getSelectedOrderLine(source, order);
    }
    if (typeof order.add_product === "function") {
        order.add_product(product, legacyPayload);
        return getSelectedOrderLine(source, order);
    }
    if (typeof order.addProduct === "function") {
        order.addProduct(product, legacyPayload);
        return getSelectedOrderLine(source, order);
    }
    return null;
}

function getProductTaxIds(product) {
    if (!product) {
        return [];
    }
    const rawTaxes = product.taxes_id || product.tax_ids || product.taxes || [];
    const values = Array.isArray(rawTaxes) ? rawTaxes : [rawTaxes];
    return [...new Set(values.map((item) => {
        if (typeof item === "number") {
            return item;
        }
        if (Array.isArray(item)) {
            return Number(item[0] || 0);
        }
        if (item && typeof item === "object") {
            return Number(item.id || 0);
        }
        return Number(item || 0);
    }).filter((item) => item > 0))];
}

function findTaxInPos(source, taxId) {
    const pos = getPos(source);
    if (!pos || !taxId) {
        return null;
    }
    const numericId = Number(taxId || 0);
    const taxCollection = pos.models && pos.models["account.tax"];
    if (taxCollection && typeof taxCollection.get === "function") {
        const tax = taxCollection.get(numericId);
        if (tax) {
            return tax;
        }
    }
    if (pos.db) {
        if (pos.db.tax_by_id && pos.db.tax_by_id[numericId]) {
            return pos.db.tax_by_id[numericId];
        }
        if (typeof pos.db.get_tax_by_id === "function") {
            const tax = pos.db.get_tax_by_id(numericId);
            if (tax) {
                return tax;
            }
        }
    }
    if (taxCollection && typeof taxCollection.getAll === "function") {
        return (taxCollection.getAll() || []).find((item) => Number(item.id) === numericId) || null;
    }
    if (Array.isArray(pos.taxes)) {
        return pos.taxes.find((item) => Number(item.id) === numericId) || null;
    }
    return null;
}

function getTaxCompanyId(tax) {
    if (!tax) {
        return 0;
    }
    const rawCompany = tax.company_id || tax.companyId || false;
    if (!rawCompany) {
        return 0;
    }
    if (typeof rawCompany === "number") {
        return Number(rawCompany || 0);
    }
    if (Array.isArray(rawCompany)) {
        return Number(rawCompany[0] || 0);
    }
    if (typeof rawCompany === "object" && rawCompany.id) {
        return Number(rawCompany.id || 0);
    }
    return 0;
}

function normalizeProductTaxesForCurrentCompany(source, product) {
    if (!product) {
        return product;
    }
    const companyId = getCurrentCompanyId(source);
    if (!companyId) {
        return product;
    }
    const originalTaxIds = getProductTaxIds(product);
    if (!originalTaxIds.length) {
        return product;
    }
    const filteredTaxIds = originalTaxIds.filter((taxId) => {
        const tax = findTaxInPos(source, taxId);
        const taxCompanyId = getTaxCompanyId(tax);
        return !taxCompanyId || taxCompanyId === companyId;
    });
    if (!filteredTaxIds.length || filteredTaxIds.length === originalTaxIds.length) {
        return product;
    }
    product.taxes_id = [...filteredTaxIds];
    product.tax_ids = [...filteredTaxIds];
    if (Array.isArray(product.taxes)) {
        product.taxes = product.taxes.filter((tax) => {
            const taxId = Number(tax && tax.id ? tax.id : 0);
            return filteredTaxIds.includes(taxId);
        });
    }
    return product;
}

function convertDisplayPriceToTaxExcluded(source, product, displayPrice) {
    const grossAmount = Number(displayPrice || 0);
    if (!grossAmount || !product) {
        return grossAmount;
    }
    const taxIds = getProductTaxIds(product);
    if (!taxIds.length) {
        return grossAmount;
    }
    const taxes = taxIds.map((taxId) => findTaxInPos(source, taxId)).filter(Boolean);
    if (!taxes.length) {
        return grossAmount;
    }

    let baseAmount = grossAmount;
    let percentFactor = 0;
    let fixedAmount = 0;
    for (const tax of taxes) {
        const amountType = String(tax.amount_type || tax.amountType || "percent");
        const isPriceIncluded = Boolean(tax.price_include ?? tax.priceInclude ?? false);
        if (isPriceIncluded) {
            continue;
        }
        if (!["percent", "fixed"].includes(amountType)) {
            return grossAmount;
        }
        const amount = Number(tax.amount || 0);
        if (amountType === "fixed") {
            fixedAmount += amount;
            continue;
        }
        percentFactor += amount / 100;
    }

    baseAmount -= fixedAmount;
    if (baseAmount < 0) {
        baseAmount = 0;
    }
    if (percentFactor) {
        baseAmount = baseAmount / (1 + percentFactor);
    }
    return Math.round(baseAmount * 1000000) / 1000000;
}

export function convertTaxExcludedPriceToDisplay(source, product, basePrice) {
    const netAmount = Number(basePrice || 0);
    if (!netAmount || !product) {
        return netAmount;
    }
    const normalizedProduct = normalizeProductTaxesForCurrentCompany(source, product);
    const taxIds = getProductTaxIds(normalizedProduct);
    if (!taxIds.length) {
        return netAmount;
    }
    const taxes = taxIds.map((taxId) => findTaxInPos(source, taxId)).filter(Boolean);
    if (!taxes.length) {
        return netAmount;
    }

    let totalAmount = netAmount;
    for (const tax of taxes) {
        const amountType = String(tax.amount_type || tax.amountType || "percent");
        const isPriceIncluded = Boolean(tax.price_include ?? tax.priceInclude ?? false);
        if (isPriceIncluded) {
            continue;
        }
        const amount = Number(tax.amount || 0);
        if (amountType === "fixed") {
            totalAmount += amount;
            continue;
        }
        if (amountType === "percent") {
            totalAmount += netAmount * (amount / 100);
            continue;
        }
        return netAmount;
    }
    return Math.round(totalAmount * 1000000) / 1000000;
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
        ? Number(
            charge.ticketUnitPrice !== undefined
                ? charge.ticketUnitPrice
                : (charge.baseAmount !== undefined
                    ? charge.baseAmount
                    : (charge.displayAmount || 0))
        )
        : Number(lineUnitPrice || 0);

    const normalizedProduct = normalizeProductTaxesForCurrentCompany(source, product);

    const addResult = await addProductToOrder(source, order, normalizedProduct, {
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
