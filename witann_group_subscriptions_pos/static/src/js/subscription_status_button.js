/** @odoo-module **/

import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { onWillUnmount } from "@odoo/owl";

const MODAL_ID = "wgs-subscription-status-modal";
const STYLE_ID = "wgs-subscription-status-style";
const STATE_SORT_RANK = {
    progress: 0,
    renew: 1,
    paused: 2,
    draft: 3,
    cancel: 4,
    closed: 5,
    upsell: 6,
    other: 7,
    none: 8,
};

function parseISODate(value) {
    if (!value || typeof value !== "string") {
        return null;
    }
    const match = value.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!match) {
        return null;
    }
    const year = Number(match[1]);
    const month = Number(match[2]);
    const day = Number(match[3]);
    const date = new Date(Date.UTC(year, month - 1, day));
    if (
        date.getUTCFullYear() !== year
        || (date.getUTCMonth() + 1) !== month
        || date.getUTCDate() !== day
    ) {
        return null;
    }
    return date;
}

function formatTodayISO() {
    return new Date().toISOString().slice(0, 10);
}

function getPos(source) {
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

function getCurrentOrder(source) {
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

function getOrderUid(order) {
    if (!order) {
        return null;
    }
    return order.uuid || order.uid || order.order_uuid || order.orderUid || null;
}

function getOrderLines(order) {
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

function getPartnerIdFromOrder(order) {
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

function setPartnerOnCurrentOrder(source, partner) {
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

function getProductIdFromLine(line) {
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

function getLineQty(line) {
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
        return;
    }
    if (typeof line.setUnitPrice === "function") {
        line.setUnitPrice(price);
        return;
    }
    line.price = price;
    line.price_unit = price;
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

function findProductInPos(source, productId) {
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

function findPartnerInPos(source, partnerId) {
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

function getAllLocalPosProducts(source) {
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

function collectSubscriptionConfigsFromOrder(order) {
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

function getSubscriptionPartnerIdsFromOrder(order) {
    const ids = [];
    for (const config of collectSubscriptionConfigsFromOrder(order)) {
        const partnerId = Number(config.partner_id || 0);
        if (partnerId > 0) {
            ids.push(partnerId);
        }
    }
    return [...new Set(ids)];
}

function waitForNextTick() {
    return new Promise((resolve) => window.setTimeout(resolve, 0));
}

async function stageSubscriptionConfigsForOrder(orm, order) {
    const configs = collectSubscriptionConfigsFromOrder(order);
    if (!configs.length) {
        return { ok: true, skipped: true };
    }
    const rawIds = [getOrderUid(order), order && order.uid, order && order.uuid].filter(Boolean);
    const orderIds = [...new Set(rawIds.map((value) => String(value).trim()).filter(Boolean))];
    if (!orderIds.length) {
        return { ok: false, reason: "missing_uuid" };
    }
    let lastResult = { ok: true };
    for (const orderId of orderIds) {
        lastResult = await orm.call("pos.order", "wgs_stage_subscription_config_for_uuid", [orderId, configs]);
        if (!lastResult || !lastResult.ok) {
            return lastResult || { ok: false, reason: "unknown" };
        }
    }
    return lastResult;
}

function addPeriodToDate(dateValue, intervalValue, intervalUnit) {
    const parsed = parseISODate(String(dateValue || "").trim());
    if (!parsed) {
        return "";
    }
    const date = new Date(parsed.getUTCFullYear(), parsed.getUTCMonth(), parsed.getUTCDate());
    const value = Math.max(1, Number(intervalValue || 1));
    const unit = String(intervalUnit || "month").toLowerCase();
    if (unit.includes("day")) {
        date.setDate(date.getDate() + value);
    } else if (unit.includes("week")) {
        date.setDate(date.getDate() + (value * 7));
    } else if (unit.includes("year")) {
        date.setFullYear(date.getFullYear() + value);
    } else {
        date.setMonth(date.getMonth() + value);
    }
    return date.toISOString().slice(0, 10);
}

patch(ControlButtons.prototype, {
    setup() {
        super.setup(...arguments);
        this.orm = useService("orm");
        this._ensureStatusStyles();

        onWillUnmount(() => {
            const modal = document.getElementById(MODAL_ID);
            if (modal) {
                modal.remove();
            }
        });
    },

    async onClickSubscriptionStatus() {
        let rows = [];
        try {
            rows = await this._fetchPartnerDirectoryRows();
        } catch (error) {
            this._showSimpleInfoModal(
                _t("Error al consultar suscripciones"),
                _t("No se pudo consultar la informacion en este momento.")
            );
            console.error("Error al consultar suscripciones en POS", error);
            return;
        }

        if (!rows.length) {
            this._showSimpleInfoModal(
                _t("Sin clientes"),
                _t("No se encontraron clientes disponibles para mostrar.")
            );
            return;
        }

        this._showSubscriptionsModal(rows);
    },

    async _fetchPartnerDirectoryRows() {
        const rows = [];
        const batchSize = 500;
        let offset = 0;

        while (true) {
            const batch = await this.orm.call(
                "sale.order",
                "get_partner_directory_rows_for_pos",
                [offset, batchSize]
            );
            if (!Array.isArray(batch) || !batch.length) {
                break;
            }
            rows.push(...batch);
            if (batch.length < batchSize) {
                break;
            }
            offset += batchSize;
        }

        return rows;
    },

    async _fetchPartnerSubscriptionDetail(partnerId) {
        return this.orm.call("sale.order", "get_partner_subscription_detail_for_pos", [partnerId]);
    },

    async _fetchSubscriptionProductCatalog(searchTerm = "") {
        const backendCatalog = await this.orm.call(
            "pos.order",
            "wgs_get_subscription_product_catalog_for_pos",
            [searchTerm, 200]
        );
        const localProducts = getAllLocalPosProducts(this);
        const localIds = new Set(
            (localProducts || [])
                .map((product) => Number(product && product.id ? product.id : 0))
                .filter((id) => id > 0)
        );
        return (Array.isArray(backendCatalog) ? backendCatalog : []).filter((item) => {
            return localIds.has(Number(item && item.id ? item.id : 0));
        });
    },

    async _fetchSubscriptionRenewalCharge(subscriptionId, productId = false, planId = false, pricingId = false) {
        return this.orm.call(
            "pos.order",
            "wgs_get_subscription_renewal_charge_for_pos",
            [subscriptionId, productId || false, planId || false, pricingId || false]
        );
    },

    _showSubscriptionsModal(rows) {
        const previous = document.getElementById(MODAL_ID);
        if (previous) {
            previous.remove();
        }

        const overlay = document.createElement("div");
        overlay.id = MODAL_ID;
        overlay.className = "wgs-status-modal-overlay";

        const modal = document.createElement("div");
        modal.className = "wgs-status-modal wgs-directory-modal";

        const header = document.createElement("div");
        header.className = "wgs-status-modal-header";
        header.innerHTML = `
            <h3>${this._escapeHtml(_t("Suscripciones"))}</h3>
            <p class="wgs-subtitle">${this._escapeHtml(_t("Directorio de clientes con detalle de suscripciones nativas, participantes y datos clave."))}</p>
        `;

        const toolbar = document.createElement("div");
        toolbar.className = "wgs-status-toolbar";
        toolbar.innerHTML = `
            <input type="text" class="wgs-filter-search" placeholder="${_t("Buscar por cliente, paquete, telefono o email")}" />
            <select class="wgs-filter-state">
                <option value="all">${_t("Estado: Todos")}</option>
                <option value="progress">${_t("Estado: En progreso")}</option>
                <option value="renew">${_t("Estado: Por renovar")}</option>
                <option value="paused">${_t("Estado: Pausada")}</option>
                <option value="draft">${_t("Estado: Borrador")}</option>
                <option value="cancel">${_t("Estado: Cancelada")}</option>
                <option value="closed">${_t("Estado: Cerrada")}</option>
                <option value="other">${_t("Estado: Otros")}</option>
                <option value="none">${_t("Estado: Sin suscripcion")}</option>
            </select>
            <select class="wgs-filter-birthday">
                <option value="all">${_t("Cumpleanos: Todos")}</option>
                <option value="today">${_t("Cumpleanos: Hoy")}</option>
                <option value="this_month">${_t("Cumpleanos: Este mes")}</option>
                <option value="next_7">${_t("Cumpleanos: Proximos 7 dias")}</option>
                <option value="missing">${_t("Cumpleanos: Sin dato")}</option>
            </select>
            <select class="wgs-sort">
                <option value="name_asc">${_t("Orden: Nombre A-Z")}</option>
                <option value="name_desc">${_t("Orden: Nombre Z-A")}</option>
                <option value="state">${_t("Orden: Estado")}</option>
                <option value="valid_until_asc">${_t("Orden: Vencimiento cercano")}</option>
                <option value="valid_until_desc">${_t("Orden: Vencimiento lejano")}</option>
                <option value="birthday_asc">${_t("Orden: Cumpleanos proximo")}</option>
                <option value="last_access_desc">${_t("Orden: Ultimo acceso reciente")}</option>
            </select>
            <button type="button" class="wgs-status-close-btn wgs-btn-export">${this._escapeHtml(_t("Descargar XLS"))}</button>
        `;

        const summary = document.createElement("div");
        summary.className = "wgs-status-summary";

        const body = document.createElement("div");
        body.className = "wgs-status-modal-body";

        const layout = document.createElement("div");
        layout.className = "wgs-subscription-layout";

        const listPane = document.createElement("div");
        listPane.className = "wgs-subscription-list-pane";
        const table = document.createElement("table");
        table.className = "wgs-status-table wgs-subscription-table";
        table.innerHTML = `
            <thead>
                <tr>
                    <th>${_t("Foto")}</th>
                    <th>${_t("Cliente")}</th>
                    <th>${_t("Estado")}</th>
                    <th>${_t("Paquete")}</th>
                    <th>${_t("Plan")}</th>
                    <th>${_t("Vencimiento")}</th>
                    <th>${_t("Ultimo acceso")}</th>
                </tr>
            </thead>
            <tbody></tbody>
        `;
        listPane.appendChild(table);

        const detailPane = document.createElement("div");
        detailPane.className = "wgs-subscription-detail-pane";
        detailPane.innerHTML = `
            <div class="wgs-detail-empty">
                <strong>${this._escapeHtml(_t("Selecciona un cliente"))}</strong>
                <p>${this._escapeHtml(_t("Aqui veras sus suscripciones nativas, participantes y acciones disponibles."))}</p>
            </div>
        `;

        layout.appendChild(listPane);
        layout.appendChild(detailPane);
        body.appendChild(layout);

        const footer = document.createElement("div");
        footer.className = "wgs-status-modal-footer";
        const closeButton = document.createElement("button");
        closeButton.type = "button";
        closeButton.className = "wgs-status-close-btn";
        closeButton.textContent = _t("Cerrar");
        const closeModal = () => overlay.remove();
        closeButton.addEventListener("click", closeModal);
        footer.appendChild(closeButton);

        modal.appendChild(header);
        modal.appendChild(toolbar);
        modal.appendChild(summary);
        modal.appendChild(body);
        modal.appendChild(footer);
        overlay.appendChild(modal);

        overlay.addEventListener("click", (event) => {
            if (event.target === overlay) {
                closeModal();
            }
        });

        document.body.appendChild(overlay);

        const searchInput = toolbar.querySelector(".wgs-filter-search");
        const stateSelect = toolbar.querySelector(".wgs-filter-state");
        const birthdaySelect = toolbar.querySelector(".wgs-filter-birthday");
        const sortSelect = toolbar.querySelector(".wgs-sort");
        const exportButton = toolbar.querySelector(".wgs-btn-export");
        const tbody = table.querySelector("tbody");

        let filteredSnapshot = [...rows];
        let selectedPartnerId = rows[0] ? rows[0].id : false;
        let detailRequestToken = 0;
        let currentDetail = null;
        let formMode = null;
        let formError = "";
        let formNotice = "";
        let catalogLoading = false;
        let productCatalog = [];
        let renewalForm = null;
        let upsaleForm = null;
        const detailCache = new Map();
        let newSubscriptionForm = this._getDefaultNewSubscriptionForm(selectedPartnerId);

        const renderDetailEmpty = (title, message) => {
            detailPane.innerHTML = `
                <div class="wgs-detail-empty">
                    <strong>${this._escapeHtml(title)}</strong>
                    <p>${this._escapeHtml(message)}</p>
                </div>
            `;
        };

        const renderDetailLoading = () => {
            detailPane.innerHTML = `
                <div class="wgs-detail-empty">
                    <strong>${this._escapeHtml(_t("Cargando detalle"))}</strong>
                    <p>${this._escapeHtml(_t("Estamos consultando las suscripciones del cliente seleccionado."))}</p>
                </div>
            `;
        };

        const getSelectedPlan = () => {
            const planKey = String(newSubscriptionForm.planChoice || "");
            return (newSubscriptionForm.plans || []).find((item) => {
                return `${Number(item.plan_id || 0)}:${Number(item.pricing_id || 0)}` === planKey;
            }) || null;
        };

        const openNewSubscriptionForm = async () => {
            if (!selectedPartnerId) {
                return;
            }
            formMode = "new";
            formError = "";
            formNotice = "";
            renewalForm = null;
            upsaleForm = null;
            newSubscriptionForm = this._getDefaultNewSubscriptionForm(selectedPartnerId);
            renderDetail(currentDetail);
            if (productCatalog.length || catalogLoading) {
                return;
            }
            catalogLoading = true;
            renderDetail(currentDetail);
            try {
                productCatalog = await this._fetchSubscriptionProductCatalog("");
                if (!Array.isArray(productCatalog)) {
                    productCatalog = [];
                }
                if (!productCatalog.length) {
                    formError = _t("No hay productos de suscripción cargados en esta sesión del POS.");
                }
            } catch (error) {
                console.error("Error al consultar catalogo de suscripciones en POS", error);
                formError = _t("No se pudo cargar el catalogo de productos de suscripcion.");
            } finally {
                catalogLoading = false;
                renderDetail(currentDetail);
            }
        };

        const openRenewalForm = async (item) => {
            if (!item || !item.subscription_id) {
                return;
            }
            formMode = "renewal";
            formError = "";
            formNotice = "";
            renewalForm = {
                subscriptionId: Number(item.subscription_id || 0) || false,
                subscriptionName: item.subscription_name || "",
                holderPartnerId: Number(item.holder_partner_id || 0) || false,
                holderPartnerName: item.holder_partner_name || "",
                productId: Number(item.renewal_product_id || 0) || false,
                productName: item.renewal_product_name || "",
                planId: Number(item.renewal_plan_id || 0) || false,
                pricingId: Number(item.renewal_pricing_id || 0) || false,
                amount: 0,
                nextInvoiceDate: item.next_invoice_date || false,
                loading: true,
            };
            renderDetail(currentDetail);
            try {
                const charge = await this._fetchSubscriptionRenewalCharge(
                    renewalForm.subscriptionId,
                    renewalForm.productId,
                    renewalForm.planId,
                    renewalForm.pricingId
                );
                renewalForm = {
                    ...renewalForm,
                    loading: false,
                    amount: Number(charge && charge.charge_now ? charge.charge_now : 0),
                    planId: Number(charge && charge.plan_id ? charge.plan_id : renewalForm.planId) || false,
                    pricingId: Number(charge && charge.pricing_id ? charge.pricing_id : renewalForm.pricingId) || false,
                };
            } catch (error) {
                console.error("Error al consultar cobro de renovación POS", error);
                formError = _t("No se pudo consultar el cobro de renovación para esta suscripción.");
                renewalForm = {
                    ...renewalForm,
                    loading: false,
                };
            }
            renderDetail(currentDetail);
        };

        const applySelectedProduct = (productId) => {
            const numericProductId = Number(productId || 0);
            const product = productCatalog.find((item) => Number(item.id) === numericProductId) || null;
            newSubscriptionForm.productId = numericProductId;
            newSubscriptionForm.productName = product ? product.name || "" : "";
            newSubscriptionForm.maxParticipantsTotal = product ? Number(product.max_participants_total || 1) : 1;
            newSubscriptionForm.plans = product ? [...(product.plans || [])] : [];
            const defaultPlanId = product ? Number(product.default_plan_id || 0) : 0;
            const defaultPricingId = product ? Number(product.default_pricing_id || 0) : 0;
            const defaultChoice = newSubscriptionForm.plans.find((item) => {
                return Number(item.plan_id || 0) === defaultPlanId && Number(item.pricing_id || 0) === defaultPricingId;
            }) || newSubscriptionForm.plans[0] || null;
            if (defaultChoice) {
                newSubscriptionForm.planChoice = `${Number(defaultChoice.plan_id || 0)}:${Number(defaultChoice.pricing_id || 0)}`;
                newSubscriptionForm.price = Number(defaultChoice.price || 0);
            } else {
                newSubscriptionForm.planChoice = "";
                newSubscriptionForm.price = Number(product ? product.default_price || 0 : 0);
            }
        };

        const updateSelectedPlan = (planChoice) => {
            newSubscriptionForm.planChoice = String(planChoice || "");
            const plan = getSelectedPlan();
            if (plan) {
                newSubscriptionForm.price = Number(plan.price || 0);
            }
        };

        const toggleParticipant = (partnerId, checked) => {
            const numericPartnerId = Number(partnerId || 0);
            let values = [...(newSubscriptionForm.participantIds || [])].map((item) => Number(item));
            values = values.filter((item) => item > 0 && item !== selectedPartnerId);
            if (checked && numericPartnerId > 0 && numericPartnerId !== selectedPartnerId) {
                values.push(numericPartnerId);
            }
            newSubscriptionForm.participantIds = [selectedPartnerId, ...new Set(values)];
        };

        const renderNewSubscriptionForm = () => {
            if (formMode !== "new") {
                return "";
            }
            const plan = getSelectedPlan();
            const minEndDate = plan
                ? addPeriodToDate(newSubscriptionForm.startDate, plan.interval_value, plan.interval_unit)
                : "";
            const participantOptions = rows
                .slice()
                .sort((a, b) => (a.name || "").localeCompare(b.name || "", "es"))
                .map((row) => {
                    const rowId = Number(row.id || 0);
                    const selected = (newSubscriptionForm.participantIds || []).includes(rowId);
                    const isOwner = rowId === selectedPartnerId;
                    return `
                        <label class="wgs-checkbox-option ${isOwner ? "wgs-checkbox-owner" : ""}">
                            <input type="checkbox" data-field="participant_toggle" value="${this._escapeHtml(String(rowId))}" ${selected ? "checked" : ""} ${isOwner ? "disabled" : ""} />
                            <span>${this._escapeHtml(row.name || "-")}${isOwner ? ` ${this._escapeHtml(_t("(Titular)"))}` : ""}</span>
                        </label>
                    `;
                }).join("");
            const productOptions = productCatalog.map((product) => {
                const selected = Number(product.id) === Number(newSubscriptionForm.productId) ? "selected" : "";
                return `<option value="${this._escapeHtml(String(product.id))}" ${selected}>${this._escapeHtml(product.name || "-")}</option>`;
            }).join("");
            const planOptions = (newSubscriptionForm.plans || []).map((item) => {
                const value = `${Number(item.plan_id || 0)}:${Number(item.pricing_id || 0)}`;
                const selected = value === String(newSubscriptionForm.planChoice || "") ? "selected" : "";
                const label = `${item.plan_name || _t("Plan recurrente")} | ${this._formatMoney(item.price || 0)}${item.interval_label ? ` | ${item.interval_label}` : ""}`;
                return `<option value="${this._escapeHtml(value)}" ${selected}>${this._escapeHtml(label)}</option>`;
            }).join("");

            return `
                <div class="wgs-inline-form-card">
                    <div class="wgs-inline-form-header">
                        <strong>${this._escapeHtml(_t("Nueva suscripcion"))}</strong>
                        <button type="button" class="wgs-inline-close-btn" data-action="cancel-new">${this._escapeHtml(_t("Cancelar"))}</button>
                    </div>
                    ${formError ? `<div class="wgs-inline-error">${this._escapeHtml(formError)}</div>` : ""}
                    ${formNotice ? `<div class="wgs-inline-notice">${this._escapeHtml(formNotice)}</div>` : ""}
                    ${catalogLoading ? `<div class="wgs-inline-loading">${this._escapeHtml(_t("Cargando productos de suscripcion..."))}</div>` : ""}
                    <div class="wgs-inline-form-grid">
                        <label>
                            <span>${this._escapeHtml(_t("Producto"))}</span>
                            <select data-field="product_id">
                                <option value="">${this._escapeHtml(_t("Selecciona un producto"))}</option>
                                ${productOptions}
                            </select>
                        </label>
                        <label>
                            <span>${this._escapeHtml(_t("Plan recurrente"))}</span>
                            <select data-field="plan_choice" ${newSubscriptionForm.plans.length ? "" : "disabled"}>
                                <option value="">${this._escapeHtml(_t("Selecciona un plan"))}</option>
                                ${planOptions}
                            </select>
                        </label>
                        <label>
                            <span>${this._escapeHtml(_t("Fecha de inicio"))}</span>
                            <input type="date" data-field="start_date" value="${this._escapeHtml(newSubscriptionForm.startDate || formatTodayISO())}" />
                        </label>
                        <label>
                            <span>${this._escapeHtml(_t("Fecha de fin (opcional)"))}</span>
                            <input type="date" data-field="end_date" value="${this._escapeHtml(newSubscriptionForm.endDate || "")}" />
                        </label>
                    </div>
                    <div class="wgs-inline-form-meta">
                        <div><span>${this._escapeHtml(_t("Precio"))}</span><strong>${this._escapeHtml(this._formatMoney(newSubscriptionForm.price || 0))}</strong></div>
                        <div><span>${this._escapeHtml(_t("Cupo total"))}</span><strong>${this._escapeHtml(String(newSubscriptionForm.maxParticipantsTotal || 1))}</strong></div>
                        <div><span>${this._escapeHtml(_t("Participantes seleccionados"))}</span><strong>${this._escapeHtml(String((newSubscriptionForm.participantIds || []).length || 0))}</strong></div>
                        <div><span>${this._escapeHtml(_t("Fin minimo sugerido"))}</span><strong>${this._escapeHtml(this._formatDateDisplay(minEndDate) || "-")}</strong></div>
                    </div>
                    <div class="wgs-inline-participants">
                        <span class="wgs-inline-section-title">${this._escapeHtml(_t("Participantes permitidos"))}</span>
                        <div class="wgs-inline-participant-list">${participantOptions}</div>
                    </div>
                    <div class="wgs-inline-actions">
                        <button type="button" class="wgs-primary-action-btn" data-action="save-new">${this._escapeHtml(_t("Agregar al ticket"))}</button>
                        <button type="button" class="wgs-secondary-action-btn" data-action="cancel-new">${this._escapeHtml(_t("Cancelar"))}</button>
                    </div>
                </div>
            `;
        };

        const renderRenewalForm = (item) => {
            if (
                formMode !== "renewal"
                || !renewalForm
                || Number(renewalForm.subscriptionId || 0) !== Number(item.subscription_id || 0)
            ) {
                return "";
            }
            return `
                <div class="wgs-inline-form-card">
                    <div class="wgs-inline-form-header">
                        <strong>${this._escapeHtml(_t("Renovar suscripción"))}</strong>
                        <button type="button" class="wgs-inline-close-btn" data-action="cancel-renewal">${this._escapeHtml(_t("Cancelar"))}</button>
                    </div>
                    ${formError ? `<div class="wgs-inline-error">${this._escapeHtml(formError)}</div>` : ""}
                    ${formNotice ? `<div class="wgs-inline-notice">${this._escapeHtml(formNotice)}</div>` : ""}
                    ${renewalForm.loading ? `<div class="wgs-inline-loading">${this._escapeHtml(_t("Calculando importe de renovación..."))}</div>` : ""}
                    <div class="wgs-inline-form-meta">
                        <div><span>${this._escapeHtml(_t("Suscripción"))}</span><strong>${this._escapeHtml(renewalForm.subscriptionName || "-")}</strong></div>
                        <div><span>${this._escapeHtml(_t("Titular"))}</span><strong>${this._escapeHtml(renewalForm.holderPartnerName || "-")}</strong></div>
                        <div><span>${this._escapeHtml(_t("Producto"))}</span><strong>${this._escapeHtml(renewalForm.productName || "-")}</strong></div>
                        <div><span>${this._escapeHtml(_t("Próxima fecha"))}</span><strong>${this._escapeHtml(this._formatDateDisplay(renewalForm.nextInvoiceDate) || "-")}</strong></div>
                        <div><span>${this._escapeHtml(_t("Importe a cobrar"))}</span><strong>${this._escapeHtml(this._formatMoney(renewalForm.amount || 0))}</strong></div>
                    </div>
                    <div class="wgs-inline-actions">
                        <button type="button" class="wgs-primary-action-btn" data-action="save-renewal" ${renewalForm.loading ? "disabled" : ""}>${this._escapeHtml(_t("Agregar al ticket"))}</button>
                        <button type="button" class="wgs-secondary-action-btn" data-action="cancel-renewal">${this._escapeHtml(_t("Cancelar"))}</button>
                    </div>
                </div>
            `;
        };

        const renderUpsalePlaceholder = (item) => {
            if (
                formMode !== "upsale"
                || !upsaleForm
                || Number(upsaleForm.subscriptionId || 0) !== Number(item.subscription_id || 0)
            ) {
                return "";
            }
            return `
                <div class="wgs-inline-form-card">
                    <div class="wgs-inline-form-header">
                        <strong>${this._escapeHtml(_t("Upsale de suscripción"))}</strong>
                        <button type="button" class="wgs-inline-close-btn" data-action="cancel-upsale">${this._escapeHtml(_t("Cancelar"))}</button>
                    </div>
                    <div class="wgs-inline-notice">
                        ${this._escapeHtml(_t("El flujo de upsale se integrará en esta misma tarjeta usando la suscripción origen seleccionada."))}
                    </div>
                    <div class="wgs-inline-form-meta">
                        <div><span>${this._escapeHtml(_t("Suscripción"))}</span><strong>${this._escapeHtml(upsaleForm.subscriptionName || "-")}</strong></div>
                        <div><span>${this._escapeHtml(_t("Titular"))}</span><strong>${this._escapeHtml(upsaleForm.holderPartnerName || "-")}</strong></div>
                        <div><span>${this._escapeHtml(_t("Paquete actual"))}</span><strong>${this._escapeHtml((item.package_names || []).join(", ") || "-")}</strong></div>
                        <div><span>${this._escapeHtml(_t("Plan actual"))}</span><strong>${this._escapeHtml(item.plan_name || "-")}</strong></div>
                    </div>
                </div>
            `;
        };

        const renderDetail = (detail) => {
            currentDetail = detail || null;
            if (!detail || !detail.partner_id) {
                renderDetailEmpty(
                    _t("Sin detalle"),
                    _t("No se pudo cargar la informacion del cliente seleccionado.")
                );
                return;
            }

            const subscriptions = Array.isArray(detail.items) ? detail.items : [];
            const summaryStateClass = this._getStateClass(detail.state);
            const subscriptionsHtml = subscriptions.length
                ? subscriptions.map((item) => {
                    const stateClass = this._getStateClass(item.native_state_key);
                    const participantNames = (item.participant_names || []).length
                        ? item.participant_names.map((name) => this._escapeHtml(name)).join(", ")
                        : this._escapeHtml(_t("Sin participantes"));
                    return `
                        <div class="wgs-subscription-card">
                            <div class="wgs-subscription-card-header">
                                <div>
                                    <strong>${this._escapeHtml(item.subscription_name || "-")}</strong>
                                    <div class="wgs-subscription-card-meta">${this._escapeHtml(item.partner_role_label || "-")}</div>
                                </div>
                                <span class="wgs-state-badge ${stateClass}">${this._escapeHtml(item.native_state_label || _t("Sin estado"))}</span>
                            </div>
                            <div class="wgs-subscription-grid">
                                <div><span>${this._escapeHtml(_t("Paquete"))}</span><strong>${this._escapeHtml((item.package_names || []).join(", ") || "-")}</strong></div>
                                <div><span>${this._escapeHtml(_t("Plan"))}</span><strong>${this._escapeHtml(item.plan_name || "-")}</strong></div>
                                <div><span>${this._escapeHtml(_t("Inicio"))}</span><strong>${this._escapeHtml(this._formatDateDisplay(item.start_date) || "-")}</strong></div>
                                <div><span>${this._escapeHtml(_t("Vencimiento"))}</span><strong>${this._escapeHtml(this._formatDateDisplay(item.valid_until) || "-")}</strong></div>
                                <div><span>${this._escapeHtml(_t("Proxima fecha"))}</span><strong>${this._escapeHtml(this._formatDateDisplay(item.next_invoice_date) || "-")}</strong></div>
                                <div><span>${this._escapeHtml(_t("Participantes"))}</span><strong>${this._escapeHtml(String(item.participant_count || 0))}</strong></div>
                            </div>
                            <div class="wgs-subscription-participants">
                                <span>${this._escapeHtml(_t("Listado de participantes"))}</span>
                                <p>${participantNames}</p>
                            </div>
                            <div class="wgs-subscription-actions">
                                <button
                                    type="button"
                                    class="wgs-action-btn"
                                    data-action="open-renewal"
                                    data-subscription-id="${this._escapeHtml(String(item.subscription_id || 0))}"
                                    ${item.access_state === "enabled" ? "" : "disabled"}
                                >${this._escapeHtml(_t("Renovar"))}</button>
                                <button
                                    type="button"
                                    class="wgs-action-btn"
                                    data-action="open-upsale"
                                    data-subscription-id="${this._escapeHtml(String(item.subscription_id || 0))}"
                                    ${item.access_state === "enabled" ? "" : "disabled"}
                                >${this._escapeHtml(_t("Upsale"))}</button>
                                <button type="button" class="wgs-action-btn" disabled>${this._escapeHtml(_t("Cobrar pendiente"))}</button>
                                <button type="button" class="wgs-action-btn" disabled>${this._escapeHtml(_t("Editar participantes"))}</button>
                            </div>
                            ${renderRenewalForm(item)}
                            ${renderUpsalePlaceholder(item)}
                        </div>
                    `;
                }).join("")
                : `
                    <div class="wgs-detail-empty wgs-detail-empty-inline">
                        <strong>${this._escapeHtml(_t("Sin suscripciones relacionadas"))}</strong>
                        <p>${this._escapeHtml(_t("Este cliente no tiene suscripciones nativas vigentes o historicas visibles para POS."))}</p>
                    </div>
                `;

            detailPane.innerHTML = `
                <div class="wgs-detail-header-card">
                    <img class="wgs-detail-avatar" src="${this._escapeHtml(detail.image_url || "")}" alt="${this._escapeHtml(detail.partner_name || "")}" loading="lazy" />
                    <div class="wgs-detail-header-text">
                        <div class="wgs-detail-title-row">
                            <h4>${this._escapeHtml(detail.partner_name || "-")}</h4>
                            <span class="wgs-state-badge ${summaryStateClass}">${this._escapeHtml(detail.state_label || _t("Sin suscripcion"))}</span>
                        </div>
                        <div class="wgs-detail-contact-grid">
                            <div><span>${this._escapeHtml(_t("Telefono"))}</span><strong>${this._escapeHtml(detail.phone || "-")}</strong></div>
                            <div><span>${this._escapeHtml(_t("Email"))}</span><strong>${this._escapeHtml(detail.email || "-")}</strong></div>
                            <div><span>${this._escapeHtml(_t("Genero"))}</span><strong>${this._escapeHtml(detail.gender || "-")}</strong></div>
                            <div><span>${this._escapeHtml(_t("Cumpleanos"))}</span><strong>${this._escapeHtml(this._formatDateDisplay(detail.birthday) || "-")}</strong></div>
                            <div><span>${this._escapeHtml(_t("Ultimo acceso"))}</span><strong>${this._escapeHtml(this._formatDateTimeDisplay(detail.last_access) || "-")}</strong></div>
                            <div><span>${this._escapeHtml(_t("Resumen"))}</span><strong>${this._escapeHtml(detail.package_label || _t("Sin suscripcion"))}</strong></div>
                        </div>
                    </div>
                </div>
                <div class="wgs-detail-actions-bar">
                    <button type="button" class="wgs-primary-action-btn" data-action="open-new">${this._escapeHtml(_t("Nueva suscripcion"))}</button>
                </div>
                ${renderNewSubscriptionForm()}
                <div class="wgs-detail-note">${this._escapeHtml(_t("Renovación, upsale, cobro pendiente y participantes se operan desde cada tarjeta de suscripción."))}</div>
                <div class="wgs-detail-section">
                    <div class="wgs-detail-section-title">${this._escapeHtml(_t("Suscripciones del cliente"))}</div>
                    <div class="wgs-subscription-cards">${subscriptionsHtml}</div>
                </div>
            `;
        };

        const loadDetail = async (partnerId) => {
            if (!partnerId) {
                renderDetailEmpty(
                    _t("Selecciona un cliente"),
                    _t("Aqui veras sus suscripciones nativas, participantes y acciones disponibles.")
                );
                return;
            }
            if (detailCache.has(partnerId)) {
                renderDetail(detailCache.get(partnerId));
                return;
            }

            renderDetailLoading();
            const requestId = ++detailRequestToken;
            try {
                const detail = await this._fetchPartnerSubscriptionDetail(partnerId);
                if (requestId !== detailRequestToken) {
                    return;
                }
                detailCache.set(partnerId, detail);
                if (selectedPartnerId === partnerId) {
                    renderDetail(detail);
                }
            } catch (error) {
                if (requestId !== detailRequestToken) {
                    return;
                }
                detailPane.innerHTML = `
                    <div class="wgs-detail-empty">
                        <strong>${this._escapeHtml(_t("Error al cargar detalle"))}</strong>
                        <p>${this._escapeHtml(_t("No se pudo consultar el detalle de suscripciones para este cliente."))}</p>
                    </div>
                `;
                console.error("Error al consultar detalle de suscripciones en POS", error);
            }
        };

        const render = () => {
            const query = (searchInput.value || "").trim().toLowerCase();
            const stateFilter = stateSelect.value;
            const birthdayFilter = birthdaySelect.value;
            const sortMode = sortSelect.value;

            let filtered = rows.filter((row) => {
                if (stateFilter !== "all" && (row.state || "none") !== stateFilter) {
                    return false;
                }
                if (!this._matchesBirthdayFilter(row.birthday, birthdayFilter)) {
                    return false;
                }
                if (!query) {
                    return true;
                }
                const haystack = `${row.name || ""} ${row.phone || ""} ${row.email || ""} ${row.package_label || ""} ${row.plan_name || ""} ${row.state_label || ""}`.toLowerCase();
                return haystack.includes(query);
            });

            filtered = filtered.sort((a, b) => {
                if (sortMode === "name_desc") {
                    return (b.name || "").localeCompare(a.name || "", "es");
                }
                if (sortMode === "state") {
                    const diff = this._getStateRank(a.state) - this._getStateRank(b.state);
                    if (diff !== 0) {
                        return diff;
                    }
                    return (a.name || "").localeCompare(b.name || "", "es");
                }
                if (sortMode === "valid_until_asc") {
                    const av = this._toTimestamp(a.valid_until);
                    const bv = this._toTimestamp(b.valid_until);
                    if (av === null && bv === null) {
                        return (a.name || "").localeCompare(b.name || "", "es");
                    }
                    if (av === null) {
                        return 1;
                    }
                    if (bv === null) {
                        return -1;
                    }
                    return av - bv;
                }
                if (sortMode === "valid_until_desc") {
                    const av = this._toTimestamp(a.valid_until);
                    const bv = this._toTimestamp(b.valid_until);
                    if (av === null && bv === null) {
                        return (a.name || "").localeCompare(b.name || "", "es");
                    }
                    if (av === null) {
                        return 1;
                    }
                    if (bv === null) {
                        return -1;
                    }
                    return bv - av;
                }
                if (sortMode === "birthday_asc") {
                    const av = this._birthdaySortRank(a.birthday);
                    const bv = this._birthdaySortRank(b.birthday);
                    if (av !== bv) {
                        return av - bv;
                    }
                    return (a.name || "").localeCompare(b.name || "", "es");
                }
                if (sortMode === "last_access_desc") {
                    const av = this._toTimestamp(a.last_access);
                    const bv = this._toTimestamp(b.last_access);
                    if (av === null && bv === null) {
                        return (a.name || "").localeCompare(b.name || "", "es");
                    }
                    if (av === null) {
                        return 1;
                    }
                    if (bv === null) {
                        return -1;
                    }
                    return bv - av;
                }
                return (a.name || "").localeCompare(b.name || "", "es");
            });

            filteredSnapshot = filtered;

            const counts = rows.reduce(
                (acc, row) => {
                    const state = row.state || "none";
                    acc.total += 1;
                    acc[state] = (acc[state] || 0) + 1;
                    if (row.birthday) {
                        acc.birthday += 1;
                    }
                    return acc;
                },
                { total: 0, birthday: 0 }
            );

            summary.innerHTML = `
                <span class="wgs-summary-pill">${_t("Total")}: ${counts.total || 0}</span>
                <span class="wgs-summary-pill wgs-summary-positive">${_t("En progreso")}: ${counts.progress || 0}</span>
                <span class="wgs-summary-pill wgs-summary-positive">${_t("Por renovar")}: ${counts.renew || 0}</span>
                <span class="wgs-summary-pill wgs-summary-warning">${_t("Pausadas")}: ${counts.paused || 0}</span>
                <span class="wgs-summary-pill wgs-summary-negative">${_t("Canceladas")}: ${counts.cancel || 0}</span>
                <span class="wgs-summary-pill wgs-summary-none">${_t("Sin suscripcion")}: ${counts.none || 0}</span>
                <span class="wgs-summary-pill">${_t("Con cumpleanos")}: ${counts.birthday || 0}</span>
                <span class="wgs-summary-pill">${_t("Mostrando")}: ${filtered.length}</span>
            `;

            if (!filtered.length) {
                tbody.innerHTML = `<tr><td colspan="7">${_t("No hay resultados para el filtro actual.")}</td></tr>`;
                selectedPartnerId = false;
                currentDetail = null;
                formMode = null;
                renderDetailEmpty(
                    _t("Sin resultados"),
                    _t("Ajusta los filtros para volver a cargar clientes en el directorio.")
                );
                return;
            }

            const filteredIds = filtered.map((row) => row.id);
            if (!selectedPartnerId || !filteredIds.includes(selectedPartnerId)) {
                selectedPartnerId = filtered[0].id;
                formMode = null;
                formError = "";
                formNotice = "";
                renewalForm = null;
                newSubscriptionForm = this._getDefaultNewSubscriptionForm(selectedPartnerId);
            }

            tbody.innerHTML = filtered.map((row) => {
                const rowClass = row.id === selectedPartnerId ? "wgs-selected-row" : "";
                const stateClass = this._getStateClass(row.state);
                return `
                    <tr class="${rowClass}" data-partner-id="${this._escapeHtml(String(row.id))}">
                        <td><img class="wgs-partner-avatar" src="${this._escapeHtml(row.image_url || "")}" alt="${this._escapeHtml(row.name || "")}" loading="lazy" /></td>
                        <td class="wgs-cell-name">${this._escapeHtml(row.name || "-")}</td>
                        <td><span class="wgs-state-badge ${stateClass}">${this._escapeHtml(row.state_label || _t("Sin suscripcion"))}</span></td>
                        <td>${this._escapeHtml(row.package_label || "-")}</td>
                        <td>${this._escapeHtml(row.plan_name || "-")}</td>
                        <td>${this._escapeHtml(this._formatDateDisplay(row.valid_until) || "-")}</td>
                        <td>${this._escapeHtml(this._formatDateTimeDisplay(row.last_access) || "-")}</td>
                    </tr>
                `;
            }).join("");

            loadDetail(selectedPartnerId);
        };

        tbody.addEventListener("click", (event) => {
            const rowElement = event.target.closest("tr[data-partner-id]");
            if (!rowElement) {
                return;
            }
            const partnerId = Number(rowElement.dataset.partnerId || 0);
            if (!partnerId || partnerId === selectedPartnerId) {
                return;
            }
            selectedPartnerId = partnerId;
            formMode = null;
            formError = "";
            formNotice = "";
            renewalForm = null;
            newSubscriptionForm = this._getDefaultNewSubscriptionForm(selectedPartnerId);
            render();
        });

        detailPane.addEventListener("click", async (event) => {
            const actionButton = event.target.closest("[data-action]");
            if (!actionButton) {
                return;
            }
            const action = actionButton.dataset.action;
            if (action === "open-new") {
                await openNewSubscriptionForm();
                return;
            }
            if (action === "cancel-new") {
                formMode = null;
                formError = "";
                formNotice = "";
                renewalForm = null;
                upsaleForm = null;
                renderDetail(currentDetail);
                return;
            }
            if (action === "open-renewal") {
                const subscriptionId = Number(actionButton.dataset.subscriptionId || 0);
                const item = (currentDetail && Array.isArray(currentDetail.items) ? currentDetail.items : []).find(
                    (row) => Number(row.subscription_id || 0) === subscriptionId
                );
                await openRenewalForm(item);
                return;
            }
            if (action === "open-upsale") {
                const subscriptionId = Number(actionButton.dataset.subscriptionId || 0);
                const item = (currentDetail && Array.isArray(currentDetail.items) ? currentDetail.items : []).find(
                    (row) => Number(row.subscription_id || 0) === subscriptionId
                );
                if (!item) {
                    return;
                }
                formMode = "upsale";
                formError = "";
                formNotice = "";
                renewalForm = null;
                upsaleForm = {
                    subscriptionId: Number(item.subscription_id || 0) || false,
                    subscriptionName: item.subscription_name || "",
                    holderPartnerId: Number(item.holder_partner_id || 0) || false,
                    holderPartnerName: item.holder_partner_name || "",
                };
                renderDetail(currentDetail);
                return;
            }
            if (action === "cancel-renewal") {
                formMode = null;
                formError = "";
                formNotice = "";
                renewalForm = null;
                upsaleForm = null;
                renderDetail(currentDetail);
                return;
            }
            if (action === "cancel-upsale") {
                formMode = null;
                formError = "";
                formNotice = "";
                renewalForm = null;
                upsaleForm = null;
                renderDetail(currentDetail);
                return;
            }
            if (action === "save-new") {
                formError = "";
                formNotice = "";
                const selectedPlan = getSelectedPlan();
                if (!selectedPartnerId) {
                    formError = _t("Selecciona un cliente para agregar la suscripcion al ticket.");
                    renderDetail(currentDetail);
                    return;
                }
                if (!newSubscriptionForm.productId) {
                    formError = _t("Selecciona un producto de suscripcion.");
                    renderDetail(currentDetail);
                    return;
                }
                if (!selectedPlan) {
                    formError = _t("Selecciona un plan recurrente.");
                    renderDetail(currentDetail);
                    return;
                }
                const existingSubscriptionPartnerIds = getSubscriptionPartnerIdsFromOrder(getCurrentOrder(this));
                if (existingSubscriptionPartnerIds.length && !existingSubscriptionPartnerIds.includes(selectedPartnerId)) {
                    formError = _t("La orden actual ya contiene suscripciones configuradas para otro cliente. Usa un solo titular por ticket.");
                    renderDetail(currentDetail);
                    return;
                }
                const participantIds = [...new Set((newSubscriptionForm.participantIds || []).map((value) => Number(value || 0)).filter((value) => value > 0))];
                if (!participantIds.includes(selectedPartnerId)) {
                    participantIds.unshift(selectedPartnerId);
                }
                if (participantIds.length > Number(newSubscriptionForm.maxParticipantsTotal || 1)) {
                    formError = _t("Estas excediendo el cupo maximo de participantes para este paquete.");
                    renderDetail(currentDetail);
                    return;
                }
                const minEndDate = addPeriodToDate(newSubscriptionForm.startDate, selectedPlan.interval_value, selectedPlan.interval_unit);
                if (newSubscriptionForm.endDate && minEndDate && newSubscriptionForm.endDate < minEndDate) {
                    formError = _t("La fecha fin debe ser posterior al primer periodo del plan seleccionado.");
                    renderDetail(currentDetail);
                    return;
                }

                const order = getCurrentOrder(this);
                if (!order) {
                    formError = _t("No hay una orden POS activa para agregar la suscripcion.");
                    renderDetail(currentDetail);
                    return;
                }
                const partnerOnOrderId = getPartnerIdFromOrder(order);
                if (partnerOnOrderId !== selectedPartnerId) {
                    const partnerRecord = findPartnerInPos(this, selectedPartnerId);
                    if (partnerRecord && setPartnerOnCurrentOrder(this, partnerRecord)) {
                        // Partner aligned locally in POS.
                    } else if (partnerOnOrderId) {
                        formError = _t("La orden actual ya tiene otro cliente y no se pudo reemplazar desde esta sesion. Usa un solo cliente por ticket.");
                        renderDetail(currentDetail);
                        return;
                    } else {
                        formNotice = _t("El cliente no esta cargado en la sesion local del POS. La suscripcion se vinculara al titular al confirmar el pago.");
                    }
                }

                const productRecord = findProductInPos(this, newSubscriptionForm.productId);
                if (!productRecord) {
                    formError = _t("El producto seleccionado no está cargado en la sesión actual del POS.");
                    renderDetail(currentDetail);
                    return;
                }

                const beforeLines = getOrderLines(order);
                const beforeCount = beforeLines.length;
                const beforeSet = new Set(beforeLines);
                const beforeSelectedLine = getSelectedOrderLine(this, order);
                let added = false;
                let addResult = null;
                let addErrorMessage = "";
                try {
                    addResult = await addProductToOrder(this, order, productRecord, {
                        quantity: 1,
                        merge: false,
                        price: Number(newSubscriptionForm.price || 0),
                    });
                    added = Boolean(addResult);
                } catch (error) {
                    console.error("Error al agregar producto de suscripcion al ticket POS", error);
                    added = false;
                    addErrorMessage = error && error.message ? error.message : String(error || "");
                }
                await waitForNextTick();
                await waitForNextTick();
                const afterLines = getOrderLines(order);
                const selectedAfter = getSelectedOrderLine(this, order);
                let targetLine = afterLines.find((line) => !beforeSet.has(line)) || null;
                if (!targetLine && addResult && typeof addResult === "object") {
                    targetLine = addResult;
                }
                if (!targetLine) {
                    if (selectedAfter && selectedAfter !== beforeSelectedLine) {
                        targetLine = selectedAfter;
                    }
                }
                if (!added && !targetLine && afterLines.length <= beforeCount) {
                    formError = _t("No se pudo agregar el producto al ticket actual.");
                    renderDetail(currentDetail);
                    return;
                }
                if (!targetLine) {
                    formError = _t("No se pudo identificar la linea agregada al ticket.");
                    renderDetail(currentDetail);
                    return;
                }

                setLineUnitPrice(targetLine, Number(newSubscriptionForm.price || 0));
                targetLine.wgsSubscriptionConfig = {
                    flow: "new",
                    partner_id: selectedPartnerId,
                    participant_ids: participantIds,
                    plan_id: Number(selectedPlan.plan_id || 0) || false,
                    pricing_id: Number(selectedPlan.pricing_id || 0) || false,
                    start_date: newSubscriptionForm.startDate || formatTodayISO(),
                    end_date: newSubscriptionForm.endDate || false,
                    product_id: Number(newSubscriptionForm.productId || 0) || false,
                    product_name: newSubscriptionForm.productName || false,
                };

                formMode = null;
                formError = "";
                formNotice = _t("Suscripcion agregada al ticket. Puedes continuar al cobro normal del POS.");
                renderDetail(currentDetail);
                return;
            }
            if (action === "save-renewal") {
                formError = "";
                formNotice = "";
                if (!renewalForm || !renewalForm.subscriptionId || !renewalForm.productId) {
                    formError = _t("La renovación seleccionada no tiene datos suficientes para agregarse al ticket.");
                    renderDetail(currentDetail);
                    return;
                }

                const order = getCurrentOrder(this);
                if (!order) {
                    formError = _t("No hay una orden POS activa para agregar la renovación.");
                    renderDetail(currentDetail);
                    return;
                }

                const holderPartnerId = Number(renewalForm.holderPartnerId || 0) || false;
                const partnerOnOrderId = getPartnerIdFromOrder(order);
                if (partnerOnOrderId !== holderPartnerId) {
                    const partnerRecord = findPartnerInPos(this, holderPartnerId);
                    if (partnerRecord && setPartnerOnCurrentOrder(this, partnerRecord)) {
                        // Partner aligned locally in POS.
                    } else if (partnerOnOrderId) {
                        formError = _t("La orden actual ya tiene otro cliente y no se pudo reemplazar desde esta sesión. Usa un solo cliente por ticket.");
                        renderDetail(currentDetail);
                        return;
                    } else {
                        formNotice = _t("El titular no está cargado en la sesión local del POS. La renovación se vinculará al confirmar el pago.");
                    }
                }

                const productRecord = findProductInPos(this, renewalForm.productId);
                if (!productRecord) {
                    formError = _t("El producto recurrente de esta suscripción no está cargado en la sesión actual del POS.");
                    renderDetail(currentDetail);
                    return;
                }

                const beforeLines = getOrderLines(order);
                const beforeCount = beforeLines.length;
                const beforeSet = new Set(beforeLines);
                const beforeSelectedLine = getSelectedOrderLine(this, order);
                let targetLine = null;
                try {
                    const addResult = await addProductToOrder(this, order, productRecord, {
                        quantity: 1,
                        merge: false,
                        price: Number(renewalForm.amount || 0),
                    });
                    await waitForNextTick();
                    await waitForNextTick();
                    const afterLines = getOrderLines(order);
                    targetLine = afterLines.find((line) => !beforeSet.has(line)) || null;
                    if (!targetLine && addResult && typeof addResult === "object") {
                        targetLine = addResult;
                    }
                    if (!targetLine) {
                        const selectedAfter = getSelectedOrderLine(this, order);
                        if (selectedAfter && selectedAfter !== beforeSelectedLine) {
                            targetLine = selectedAfter;
                        }
                    }
                    if (!targetLine && afterLines.length <= beforeCount) {
                        formError = _t("No se pudo agregar la renovación al ticket actual.");
                        renderDetail(currentDetail);
                        return;
                    }
                } catch (error) {
                    console.error("Error al agregar renovación al ticket POS", error);
                    formError = _t("No se pudo agregar la renovación al ticket actual.");
                    renderDetail(currentDetail);
                    return;
                }

                if (!targetLine) {
                    formError = _t("No se pudo identificar la línea de renovación agregada al ticket.");
                    renderDetail(currentDetail);
                    return;
                }

                setLineUnitPrice(targetLine, Number(renewalForm.amount || 0));
                targetLine.wgsSubscriptionConfig = {
                    flow: "renewal",
                    partner_id: holderPartnerId || false,
                    participant_ids: [],
                    plan_id: Number(renewalForm.planId || 0) || false,
                    pricing_id: Number(renewalForm.pricingId || 0) || false,
                    start_date: false,
                    end_date: false,
                    product_id: Number(renewalForm.productId || 0) || false,
                    product_name: renewalForm.productName || false,
                    source_subscription_id: Number(renewalForm.subscriptionId || 0) || false,
                };

                formMode = null;
                formError = "";
                formNotice = _t("Renovación agregada al ticket. Puedes continuar al cobro normal del POS.");
                renewalForm = null;
                upsaleForm = null;
                renderDetail(currentDetail);
                return;
            }
        });

        detailPane.addEventListener("change", (event) => {
            const field = event.target.dataset.field;
            if (formMode !== "new" || !field) {
                return;
            }
            formError = "";
            formNotice = "";
            if (field === "product_id") {
                applySelectedProduct(event.target.value);
            } else if (field === "plan_choice") {
                updateSelectedPlan(event.target.value);
            } else if (field === "start_date") {
                newSubscriptionForm.startDate = event.target.value || formatTodayISO();
            } else if (field === "end_date") {
                newSubscriptionForm.endDate = event.target.value || "";
            } else if (field === "participant_toggle") {
                toggleParticipant(event.target.value, event.target.checked);
            }
            renderDetail(currentDetail);
        });

        searchInput.addEventListener("input", render);
        stateSelect.addEventListener("change", render);
        birthdaySelect.addEventListener("change", render);
        sortSelect.addEventListener("change", render);
        exportButton.addEventListener("click", () => {
            this._downloadDirectoryAsXls(filteredSnapshot);
        });

        render();
    },

    _getDefaultNewSubscriptionForm(partnerId) {
        const participantIds = [];
        if (partnerId) {
            participantIds.push(Number(partnerId));
        }
        return {
            productId: 0,
            productName: "",
            planChoice: "",
            plans: [],
            price: 0,
            startDate: formatTodayISO(),
            endDate: "",
            maxParticipantsTotal: 1,
            participantIds,
        };
    },

    _getStateRank(state) {
        return STATE_SORT_RANK[state || "other"] ?? STATE_SORT_RANK.other;
    },

    _getStateClass(state) {
        const value = state || "none";
        if (value === "progress" || value === "renew") {
            return "wgs-state-positive";
        }
        if (value === "paused" || value === "draft" || value === "upsell") {
            return "wgs-state-warning";
        }
        if (value === "cancel" || value === "closed") {
            return "wgs-state-negative";
        }
        return "wgs-state-neutral";
    },

    _formatMoney(value) {
        const amount = Number(value || 0);
        try {
            return new Intl.NumberFormat("es-MX", {
                style: "currency",
                currency: "MXN",
                minimumFractionDigits: 2,
            }).format(amount);
        } catch {
            return `$ ${amount.toFixed(2)}`;
        }
    },

    _toTimestamp(value) {
        if (!value) {
            return null;
        }
        const ts = Date.parse(String(value).trim());
        return Number.isNaN(ts) ? null : ts;
    },

    _birthdaySortRank(birthdayValue) {
        const parsed = parseISODate(String(birthdayValue || "").trim());
        if (!parsed) {
            return 367;
        }
        const today = new Date();
        const currentYear = today.getFullYear();
        let nextBirthday = new Date(currentYear, parsed.getUTCMonth(), parsed.getUTCDate());
        if (nextBirthday < new Date(currentYear, today.getMonth(), today.getDate())) {
            nextBirthday = new Date(currentYear + 1, parsed.getUTCMonth(), parsed.getUTCDate());
        }
        const diffMs = nextBirthday.getTime() - new Date(currentYear, today.getMonth(), today.getDate()).getTime();
        return Math.floor(diffMs / 86400000);
    },

    _matchesBirthdayFilter(birthdayValue, filterMode) {
        if (filterMode === "all") {
            return true;
        }
        const parsed = parseISODate(String(birthdayValue || "").trim());
        if (!parsed) {
            return filterMode === "missing";
        }
        if (filterMode === "missing") {
            return false;
        }

        const today = new Date();
        const todayMonth = today.getMonth() + 1;
        const todayDay = today.getDate();
        const birthMonth = parsed.getUTCMonth() + 1;
        const birthDay = parsed.getUTCDate();

        if (filterMode === "today") {
            return birthMonth === todayMonth && birthDay === todayDay;
        }
        if (filterMode === "this_month") {
            return birthMonth === todayMonth;
        }
        if (filterMode === "next_7") {
            return this._birthdaySortRank(birthdayValue) <= 7;
        }
        return true;
    },

    _formatDateDisplay(value) {
        if (!value) {
            return "";
        }
        const parsed = parseISODate(String(value).slice(0, 10));
        if (!parsed) {
            return String(value);
        }
        const date = new Date(parsed.getUTCFullYear(), parsed.getUTCMonth(), parsed.getUTCDate());
        return date.toLocaleDateString("es-MX", {
            day: "2-digit",
            month: "short",
            year: "numeric",
        });
    },

    _formatDateTimeDisplay(value) {
        if (!value) {
            return "";
        }
        const ts = this._toTimestamp(value);
        if (ts === null) {
            return String(value);
        }
        return new Date(ts).toLocaleString("es-MX", {
            day: "2-digit",
            month: "short",
            year: "numeric",
            hour: "2-digit",
            minute: "2-digit",
        });
    },

    _downloadDirectoryAsXls(rows) {
        const dataRows = Array.isArray(rows) ? rows : [];
        const filenameDate = new Date().toISOString().slice(0, 10);
        const filename = `suscripciones_pos_${filenameDate}.xls`;

        const tableRows = dataRows.map((row) => `
            <tr>
                <td>${this._escapeHtml(row.name || "-")}</td>
                <td>${this._escapeHtml(row.state_label || _t("Sin suscripcion"))}</td>
                <td>${this._escapeHtml(row.package_label || "-")}</td>
                <td>${this._escapeHtml(row.plan_name || "-")}</td>
                <td>${this._escapeHtml(this._formatDateDisplay(row.start_date) || "-")}</td>
                <td>${this._escapeHtml(this._formatDateDisplay(row.valid_until) || "-")}</td>
                <td>${this._escapeHtml(row.gender || "-")}</td>
                <td>${this._escapeHtml(this._formatDateDisplay(row.birthday) || "-")}</td>
                <td>${this._escapeHtml(this._formatDateTimeDisplay(row.last_access) || "-")}</td>
                <td>${this._escapeHtml(row.phone || "-")}</td>
                <td>${this._escapeHtml(row.email || "-")}</td>
            </tr>
        `).join("");

        const html = `
            <html>
                <head>
                    <meta charset="UTF-8" />
                    <style>
                        table { border-collapse: collapse; font-family: Arial, sans-serif; font-size: 12px; }
                        th, td { border: 1px solid #999; padding: 6px; text-align: left; }
                        th { background: #e9eef5; }
                    </style>
                </head>
                <body>
                    <table>
                        <thead>
                            <tr>
                                <th>${this._escapeHtml(_t("Cliente"))}</th>
                                <th>${this._escapeHtml(_t("Estado"))}</th>
                                <th>${this._escapeHtml(_t("Paquete"))}</th>
                                <th>${this._escapeHtml(_t("Plan"))}</th>
                                <th>${this._escapeHtml(_t("Inicio"))}</th>
                                <th>${this._escapeHtml(_t("Vencimiento"))}</th>
                                <th>${this._escapeHtml(_t("Genero"))}</th>
                                <th>${this._escapeHtml(_t("Cumpleanos"))}</th>
                                <th>${this._escapeHtml(_t("Ultimo acceso"))}</th>
                                <th>${this._escapeHtml(_t("Telefono"))}</th>
                                <th>${this._escapeHtml(_t("Email"))}</th>
                            </tr>
                        </thead>
                        <tbody>${tableRows}</tbody>
                    </table>
                </body>
            </html>
        `;

        const blob = new Blob([`\uFEFF${html}`], { type: "application/vnd.ms-excel;charset=utf-8;" });
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = filename;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        setTimeout(() => URL.revokeObjectURL(url), 500);
    },

    _showSimpleInfoModal(title, message) {
        const previous = document.getElementById(MODAL_ID);
        if (previous) {
            previous.remove();
        }

        const overlay = document.createElement("div");
        overlay.id = MODAL_ID;
        overlay.className = "wgs-status-modal-overlay";

        const modal = document.createElement("div");
        modal.className = "wgs-status-modal";

        modal.innerHTML = `
            <div class="wgs-status-modal-header"><h3>${this._escapeHtml(title)}</h3></div>
            <div class="wgs-status-modal-body"><p class="wgs-simple-message">${this._escapeHtml(message)}</p></div>
            <div class="wgs-status-modal-footer">
                <button type="button" class="wgs-status-close-btn">${this._escapeHtml(_t("Cerrar"))}</button>
            </div>
        `;

        const closeModal = () => overlay.remove();
        modal.querySelector(".wgs-status-close-btn").addEventListener("click", closeModal);
        overlay.addEventListener("click", (event) => {
            if (event.target === overlay) {
                closeModal();
            }
        });

        overlay.appendChild(modal);
        document.body.appendChild(overlay);
    },

    _escapeHtml(value) {
        return String(value)
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#39;");
    },

    _ensureStatusStyles() {
        if (document.getElementById(STYLE_ID)) {
            return;
        }

        const style = document.createElement("style");
        style.id = STYLE_ID;
        style.textContent = `
            .wgs-status-modal-overlay {
                position: fixed;
                inset: 0;
                z-index: 10000;
                background: rgba(15, 23, 42, 0.45);
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 1rem;
            }
            .wgs-status-modal {
                width: min(1180px, 98vw);
                height: min(92vh, 980px);
                max-height: 92vh;
                overflow: hidden;
                background: #ffffff;
                border-radius: 0.75rem;
                box-shadow: 0 20px 50px rgba(0, 0, 0, 0.3);
                display: flex;
                flex-direction: column;
            }
            .wgs-directory-modal {
                width: min(1580px, 99vw);
            }
            .control-buttons {
                flex-wrap: wrap !important;
                align-content: flex-start;
            }
            .wgs-control-buttons-row {
                width: 100%;
                flex: 0 0 100%;
                order: 999;
                display: flex;
                gap: 0.35rem;
                margin-top: 0.35rem;
            }
            .wgs-control-button {
                flex: 1 1 auto;
                min-width: 0;
            }
            .wgs-status-modal-header {
                padding: 1rem 1.2rem;
                border-bottom: 1px solid #e5e7eb;
            }
            .wgs-status-modal-header h3 {
                margin: 0;
                font-size: 1.05rem;
                color: #111827;
            }
            .wgs-subtitle {
                margin: 0.35rem 0 0;
                color: #475569;
                font-size: 0.84rem;
            }
            .wgs-status-toolbar {
                padding: 0.8rem 1.2rem;
                display: grid;
                grid-template-columns: 2fr repeat(4, minmax(160px, 1fr));
                gap: 0.6rem;
                border-bottom: 1px solid #e5e7eb;
                align-items: center;
            }
            .wgs-status-toolbar input,
            .wgs-status-toolbar select,
            .wgs-status-toolbar button,
            .wgs-inline-form-grid input,
            .wgs-inline-form-grid select {
                width: 100%;
                border: 1px solid #d1d5db;
                border-radius: 0.45rem;
                padding: 0.45rem 0.55rem;
                font-size: 0.88rem;
                background: #fff;
                color: #111827;
            }
            .wgs-status-summary {
                padding: 0.55rem 1.2rem;
                border-bottom: 1px solid #e5e7eb;
                display: flex;
                gap: 0.5rem;
                flex-wrap: wrap;
            }
            .wgs-summary-pill {
                border: 1px solid #d1d5db;
                border-radius: 999px;
                padding: 0.2rem 0.55rem;
                font-size: 0.76rem;
                font-weight: 600;
                color: #374151;
                background: #f9fafb;
            }
            .wgs-summary-positive {
                border-color: #8ad9b5;
                color: #0f7b4b;
                background: #daf5e8;
            }
            .wgs-summary-warning {
                border-color: #fcd34d;
                color: #92400e;
                background: #fef3c7;
            }
            .wgs-summary-negative {
                border-color: #fda4af;
                color: #9f1239;
                background: #ffe4e6;
            }
            .wgs-summary-none {
                border-color: #cbd5e1;
                color: #475569;
                background: #f1f5f9;
            }
            .wgs-status-modal-body {
                padding: 0;
                overflow: hidden;
                color: #1f2937;
                flex: 1 1 auto;
                min-height: 0;
            }
            .wgs-subscription-layout {
                display: grid;
                grid-template-columns: minmax(620px, 1.2fr) minmax(420px, 0.8fr);
                height: 100%;
                min-height: 0;
            }
            .wgs-subscription-list-pane {
                border-right: 1px solid #e5e7eb;
                overflow: auto;
                min-height: 0;
            }
            .wgs-subscription-detail-pane {
                overflow: auto;
                background: #f8fafc;
                padding: 1rem;
                min-height: 0;
            }
            .wgs-detail-empty {
                border: 1px dashed #cbd5e1;
                border-radius: 0.75rem;
                background: #ffffff;
                padding: 1rem;
                color: #475569;
            }
            .wgs-detail-empty strong {
                display: block;
                color: #0f172a;
                margin-bottom: 0.3rem;
            }
            .wgs-detail-empty-inline {
                margin-top: 0.4rem;
            }
            .wgs-detail-header-card {
                display: grid;
                grid-template-columns: 72px 1fr;
                gap: 0.9rem;
                background: #ffffff;
                border: 1px solid #e5e7eb;
                border-radius: 0.85rem;
                padding: 1rem;
                margin-bottom: 0.85rem;
            }
            .wgs-detail-avatar {
                width: 72px;
                height: 72px;
                border-radius: 16px;
                object-fit: cover;
                background: #e2e8f0;
                border: 1px solid #d1d5db;
            }
            .wgs-detail-title-row {
                display: flex;
                justify-content: space-between;
                gap: 0.6rem;
                align-items: center;
                margin-bottom: 0.75rem;
            }
            .wgs-detail-title-row h4 {
                margin: 0;
                color: #0f172a;
                font-size: 1.05rem;
            }
            .wgs-detail-contact-grid {
                display: grid;
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 0.75rem;
            }
            .wgs-detail-contact-grid div,
            .wgs-subscription-grid div,
            .wgs-inline-form-meta div {
                display: flex;
                flex-direction: column;
                gap: 0.18rem;
            }
            .wgs-detail-contact-grid span,
            .wgs-subscription-grid span,
            .wgs-subscription-participants span,
            .wgs-inline-form-grid label span,
            .wgs-inline-form-meta span,
            .wgs-inline-section-title {
                font-size: 0.72rem;
                text-transform: uppercase;
                letter-spacing: 0.04em;
                color: #64748b;
                font-weight: 700;
            }
            .wgs-detail-contact-grid strong,
            .wgs-subscription-grid strong,
            .wgs-inline-form-meta strong {
                color: #0f172a;
                font-size: 0.9rem;
            }
            .wgs-detail-actions-bar,
            .wgs-subscription-actions,
            .wgs-inline-actions {
                display: grid;
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 0.55rem;
            }
            .wgs-primary-action-btn,
            .wgs-secondary-action-btn,
            .wgs-action-btn,
            .wgs-inline-close-btn {
                border-radius: 0.65rem;
                padding: 0.65rem 0.8rem;
                font-weight: 700;
                font-size: 0.84rem;
                border: 1px solid #cbd5e1;
                background: #ffffff;
                color: #334155;
            }
            .wgs-primary-action-btn {
                background: #0f766e;
                color: #ffffff;
                border-color: #0f766e;
            }
            .wgs-primary-action-btn:disabled,
            .wgs-secondary-action-btn:disabled,
            .wgs-action-btn:disabled {
                opacity: 0.7;
                cursor: not-allowed;
            }
            .wgs-detail-note {
                font-size: 0.8rem;
                color: #475569;
                margin-bottom: 0.9rem;
            }
            .wgs-detail-section {
                display: flex;
                flex-direction: column;
                gap: 0.6rem;
            }
            .wgs-detail-section-title {
                font-size: 0.84rem;
                font-weight: 800;
                text-transform: uppercase;
                letter-spacing: 0.05em;
                color: #334155;
            }
            .wgs-subscription-cards {
                display: flex;
                flex-direction: column;
                gap: 0.75rem;
            }
            .wgs-subscription-card,
            .wgs-inline-form-card {
                background: #ffffff;
                border: 1px solid #e5e7eb;
                border-radius: 0.85rem;
                padding: 0.9rem;
                display: flex;
                flex-direction: column;
                gap: 0.75rem;
                margin-bottom: 0.85rem;
            }
            .wgs-subscription-card-header,
            .wgs-inline-form-header {
                display: flex;
                justify-content: space-between;
                gap: 0.6rem;
                align-items: flex-start;
            }
            .wgs-subscription-card-meta {
                margin-top: 0.2rem;
                color: #64748b;
                font-size: 0.78rem;
            }
            .wgs-subscription-grid,
            .wgs-inline-form-grid,
            .wgs-inline-form-meta {
                display: grid;
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 0.7rem;
            }
            .wgs-subscription-participants p {
                margin: 0.25rem 0 0;
                color: #0f172a;
                line-height: 1.45;
            }
            .wgs-inline-error {
                border: 1px solid #fda4af;
                background: #fff1f2;
                color: #9f1239;
                border-radius: 0.65rem;
                padding: 0.65rem 0.75rem;
                font-size: 0.84rem;
                font-weight: 600;
            }
            .wgs-inline-notice {
                border: 1px solid #8ad9b5;
                background: #ecfdf5;
                color: #0f7b4b;
                border-radius: 0.65rem;
                padding: 0.65rem 0.75rem;
                font-size: 0.84rem;
                font-weight: 600;
            }
            .wgs-inline-loading {
                color: #475569;
                font-size: 0.84rem;
            }
            .wgs-inline-participant-list {
                max-height: 220px;
                overflow: auto;
                display: grid;
                grid-template-columns: 1fr;
                gap: 0.35rem;
                border: 1px solid #e5e7eb;
                border-radius: 0.65rem;
                padding: 0.55rem;
                background: #f8fafc;
            }
            .wgs-checkbox-option {
                display: flex;
                gap: 0.55rem;
                align-items: center;
                color: #0f172a;
                font-size: 0.84rem;
            }
            .wgs-checkbox-owner {
                font-weight: 700;
            }
            .wgs-status-modal-footer {
                padding: 0.8rem 1.2rem;
                border-top: 1px solid #e5e7eb;
                display: flex;
                justify-content: flex-end;
                gap: 0.5rem;
                align-items: center;
            }
            .wgs-status-close-btn {
                border: none;
                border-radius: 0.5rem;
                background: #0284c7;
                color: #ffffff;
                padding: 0.5rem 0.9rem;
                font-weight: 600;
                cursor: pointer;
            }
            .wgs-btn-export {
                background: #0369a1;
                white-space: nowrap;
            }
            .wgs-status-table {
                width: 100%;
                border-collapse: collapse;
            }
            .wgs-status-table th,
            .wgs-status-table td {
                border-bottom: 1px solid #e5e7eb;
                padding: 0.6rem 0.65rem;
                text-align: left;
                vertical-align: middle;
                font-size: 0.84rem;
            }
            .wgs-status-table tbody tr {
                cursor: pointer;
            }
            .wgs-status-table tbody tr:hover {
                background: #f8fafc;
            }
            .wgs-selected-row {
                background: #ecfeff !important;
            }
            .wgs-status-table th {
                position: sticky;
                top: 0;
                z-index: 1;
                background: #f8fafc;
                font-size: 0.74rem;
                color: #374151;
                text-transform: uppercase;
                letter-spacing: 0.03em;
            }
            .wgs-partner-avatar {
                width: 38px;
                height: 38px;
                border-radius: 50%;
                object-fit: cover;
                border: 1px solid #d1d5db;
                display: block;
                background: #f1f5f9;
            }
            .wgs-cell-name {
                font-weight: 700;
                color: #0f172a;
                min-width: 190px;
            }
            .wgs-state-badge {
                display: inline-flex;
                align-items: center;
                justify-content: center;
                border-radius: 999px;
                padding: 0.18rem 0.55rem;
                font-size: 0.74rem;
                font-weight: 700;
                border: 1px solid #d1d5db;
                white-space: nowrap;
            }
            .wgs-state-positive {
                border-color: #8ad9b5;
                color: #0f7b4b;
                background: #daf5e8;
            }
            .wgs-state-warning {
                border-color: #fcd34d;
                color: #92400e;
                background: #fef3c7;
            }
            .wgs-state-negative {
                border-color: #fda4af;
                color: #9f1239;
                background: #ffe4e6;
            }
            .wgs-state-neutral {
                border-color: #cbd5e1;
                color: #475569;
                background: #f1f5f9;
            }
            .wgs-simple-message {
                padding: 1rem 1.2rem;
            }
            @media (max-width: 1250px) {
                .wgs-subscription-layout {
                    grid-template-columns: 1fr;
                    height: auto;
                }
                .wgs-subscription-list-pane {
                    border-right: none;
                    border-bottom: 1px solid #e5e7eb;
                    max-height: 42vh;
                }
            }
            @media (max-width: 900px) {
                .wgs-status-toolbar,
                .wgs-detail-contact-grid,
                .wgs-subscription-grid,
                .wgs-detail-actions-bar,
                .wgs-subscription-actions,
                .wgs-inline-form-grid,
                .wgs-inline-form-meta,
                .wgs-inline-actions {
                    grid-template-columns: 1fr;
                }
                .wgs-detail-header-card {
                    grid-template-columns: 1fr;
                }
                .wgs-detail-avatar {
                    width: 64px;
                    height: 64px;
                }
            }
        `;
        document.head.appendChild(style);
    },
});

patch(PaymentScreen.prototype, {
    setup() {
        super.setup(...arguments);
        this.orm = this.orm || useService("orm");
    },

    async validateOrder(isForceValidate) {
        const order = getCurrentOrder(this.pos);
        try {
            const result = await stageSubscriptionConfigsForOrder(this.orm, order);
            if (result && result.ok === false) {
                window.alert(_t("No se pudo preparar la configuracion de suscripcion para esta venta. Actualiza el modulo y vuelve a intentar."));
                return;
            }
        } catch (error) {
            console.error("Error al preparar configuracion de suscripcion antes del cobro POS", error);
            window.alert(_t("No se pudo preparar la configuracion de suscripcion antes del cobro."));
            return;
        }
        return super.validateOrder(...arguments);
    },
});
