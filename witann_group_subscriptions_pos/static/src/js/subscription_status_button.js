/** @odoo-module **/

import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { onWillUnmount } from "@odoo/owl";

const MODAL_ID = "wgs-subscription-status-modal";
const STYLE_ID = "wgs-subscription-status-style";
const ORDERLINE_PATCH_FLAG = "__wgsParticipantSerializationPatched";
const ORDER_PATCH_FLAG = "__wgsOrderSerializationPatched";

function getPos(component) {
    if (component.pos) {
        return component.pos;
    }
    if (component.env && component.env.pos) {
        return component.env.pos;
    }
    return null;
}

function getCurrentOrder(component) {
    const pos = getPos(component);
    if (component.currentOrder) {
        return component.currentOrder;
    }
    if (component.props && component.props.order) {
        return component.props.order;
    }
    if (pos && typeof pos.get_order === "function") {
        return pos.get_order();
    }
    if (pos && typeof pos.getOrder === "function") {
        return pos.getOrder();
    }
    if (pos && pos.selectedOrder) {
        return pos.selectedOrder;
    }
    return null;
}

function getOrderUUID(order) {
    if (!order) {
        return "";
    }
    const candidates = [order.uuid, order.uid, order.order_uuid, order.orderUid];
    for (const value of candidates) {
        if (value) {
            return String(value);
        }
    }
    if (typeof order.get_uid === "function") {
        const value = order.get_uid();
        if (value) {
            return String(value);
        }
    }
    if (typeof order.getUID === "function") {
        const value = order.getUID();
        if (value) {
            return String(value);
        }
    }
    return "";
}

function getCurrentPartner(component, order = null) {
    if (component.props && component.props.partner && component.props.partner.id) {
        return component.props.partner;
    }

    const activeOrder = order || getCurrentOrder(component);
    if (!activeOrder) {
        return null;
    }

    if (typeof activeOrder.get_partner === "function") {
        const partner = activeOrder.get_partner();
        if (partner) {
            return partner;
        }
    }
    if (typeof activeOrder.getPartner === "function") {
        const partner = activeOrder.getPartner();
        if (partner) {
            return partner;
        }
    }

    if (activeOrder.partner && activeOrder.partner.id) {
        return activeOrder.partner;
    }

    const partnerField = activeOrder.partner_id;
    if (Array.isArray(partnerField) && partnerField.length) {
        return getPartnerById(component, partnerField[0]);
    }
    if (typeof partnerField === "number") {
        return getPartnerById(component, partnerField);
    }
    if (partnerField && typeof partnerField === "object" && partnerField.id) {
        return partnerField;
    }
    const camelPartnerField = activeOrder.partnerId;
    if (Array.isArray(camelPartnerField) && camelPartnerField.length) {
        return getPartnerById(component, camelPartnerField[0]);
    }
    if (typeof camelPartnerField === "number") {
        return getPartnerById(component, camelPartnerField);
    }
    if (camelPartnerField && typeof camelPartnerField === "object" && camelPartnerField.id) {
        return camelPartnerField;
    }

    return null;
}

function getPartnerById(component, partnerId) {
    const parsed = Number.parseInt(partnerId, 10);
    if (!Number.isInteger(parsed) || parsed <= 0) {
        return null;
    }

    const pos = getPos(component);
    if (!pos) {
        return null;
    }

    if (pos.models && pos.models["res.partner"] && typeof pos.models["res.partner"].get === "function") {
        const record = pos.models["res.partner"].get(parsed);
        if (record) {
            return record;
        }
    }

    if (pos.db && typeof pos.db.get_partner_by_id === "function") {
        const record = pos.db.get_partner_by_id(parsed);
        if (record) {
            return record;
        }
    }

    return { id: parsed, name: _t("Cliente") };
}

function getAllPartners(component) {
    const pos = getPos(component);
    if (!pos) {
        return [];
    }

    if (pos.models && pos.models["res.partner"]) {
        const partnerModel = pos.models["res.partner"];
        if (typeof partnerModel.getAll === "function") {
            return partnerModel.getAll();
        }
        if (Array.isArray(partnerModel.records)) {
            return partnerModel.records;
        }
    }

    if (pos.db) {
        if (typeof pos.db.get_partners_sorted === "function") {
            return pos.db.get_partners_sorted(100000) || [];
        }
        if (pos.db.partner_by_id) {
            return Object.values(pos.db.partner_by_id);
        }
    }

    return [];
}

function getSelectedOrderline(component, order = null) {
    const activeOrder = order || getCurrentOrder(component);
    if (!activeOrder) {
        return null;
    }

    if (typeof activeOrder.get_selected_orderline === "function") {
        return activeOrder.get_selected_orderline();
    }
    if (typeof activeOrder.getSelectedOrderline === "function") {
        return activeOrder.getSelectedOrderline();
    }
    if (typeof activeOrder.getSelectedOrderLine === "function") {
        return activeOrder.getSelectedOrderLine();
    }

    if (activeOrder.selected_orderline) {
        return activeOrder.selected_orderline;
    }
    if (activeOrder.selectedOrderline) {
        return activeOrder.selectedOrderline;
    }
    if (activeOrder.selectedOrderLine) {
        return activeOrder.selectedOrderLine;
    }

    return null;
}

function getOrderlines(order) {
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

function getLineProduct(component, line) {
    if (!line) {
        return null;
    }

    if (line.product) {
        return line.product;
    }

    if (typeof line.get_product === "function") {
        const product = line.get_product();
        if (product) {
            return product;
        }
    }
    if (typeof line.getProduct === "function") {
        const product = line.getProduct();
        if (product) {
            return product;
        }
    }

    let productId = line.product_id || (typeof line.get_product_id === "function" ? line.get_product_id() : null);
    if (Array.isArray(productId)) {
        productId = productId[0];
    }
    if (typeof productId === "object" && productId && productId.id) {
        productId = productId.id;
    }
    const parsedProductId = Number.parseInt(productId, 10);
    if (Number.isInteger(parsedProductId) && parsedProductId > 0) {
        productId = parsedProductId;
    }
    if (!productId) {
        return null;
    }

    const pos = getPos(component);
    if (pos && pos.db && typeof pos.db.get_product_by_id === "function") {
        return pos.db.get_product_by_id(productId);
    }

    return null;
}

function getLineProductId(line) {
    if (!line) {
        return 0;
    }
    if (line.product && line.product.id) {
        return Number.parseInt(line.product.id, 10) || 0;
    }
    if (typeof line.get_product === "function") {
        const product = line.get_product();
        if (product && product.id) {
            return Number.parseInt(product.id, 10) || 0;
        }
    }
    if (typeof line.getProduct === "function") {
        const product = line.getProduct();
        if (product && product.id) {
            return Number.parseInt(product.id, 10) || 0;
        }
    }
    let productId = line.product_id || (typeof line.get_product_id === "function" ? line.get_product_id() : null);
    if (Array.isArray(productId) && productId.length) {
        productId = productId[0];
    }
    if (typeof productId === "object" && productId && productId.id) {
        productId = productId.id;
    }
    const parsed = Number.parseInt(productId, 10);
    return Number.isInteger(parsed) && parsed > 0 ? parsed : 0;
}

function isSubscriptionProduct(product) {
    if (!product) {
        return false;
    }
    return !!(
        product.recurring_invoice
        || product.is_subscription
        || product.subscription_ok
        || (product.product_tmpl_id && product.product_tmpl_id.recurring_invoice)
    );
}

function getLineQuantity(line) {
    if (!line) {
        return 0;
    }
    if (typeof line.get_quantity === "function") {
        return Math.abs(Number(line.get_quantity()) || 0);
    }
    if (typeof line.getQuantity === "function") {
        return Math.abs(Number(line.getQuantity()) || 0);
    }
    if ("quantity" in line) {
        return Math.abs(Number(line.quantity) || 0);
    }
    return Math.abs(Number(line.qty) || 0);
}

function getLineParticipantIds(line, holderId = null) {
    const initial = Array.isArray(line && line.wgs_participant_ids) ? [...line.wgs_participant_ids] : [];
    const cleaned = [];

    for (const value of initial) {
        const parsed = Number.parseInt(value, 10);
        if (Number.isInteger(parsed) && parsed > 0 && !cleaned.includes(parsed)) {
            cleaned.push(parsed);
        }
    }

    if (holderId && !cleaned.includes(holderId)) {
        cleaned.unshift(holderId);
    }

    return cleaned;
}

function setLineParticipantIds(line, participantIds) {
    if (!line) {
        return;
    }

    const cleaned = [];
    for (const value of participantIds || []) {
        const parsed = Number.parseInt(value, 10);
        if (Number.isInteger(parsed) && parsed > 0 && !cleaned.includes(parsed)) {
            cleaned.push(parsed);
        }
    }

    line.wgs_participant_ids = cleaned;

    if (line.order && typeof line.order.trigger === "function") {
        line.order.trigger("change", line.order);
    }
}

function getLineParticipantCapacity(product, line) {
    const maxPerUnit = Number.parseInt(product && product.max_participants_total, 10) || 1;
    const qty = getLineQuantity(line) || 1;
    const total = Math.floor(maxPerUnit * qty);
    return total > 0 ? total : 1;
}

function getLineSubscriptionSelection(line) {
    if (!line) {
        return { planId: false, pricingId: false };
    }
    const planId = Number.parseInt(line.wgs_subscription_plan_id, 10);
    const pricingId = Number.parseInt(line.wgs_subscription_pricing_id, 10);
    return {
        planId: Number.isInteger(planId) && planId > 0 ? planId : false,
        pricingId: Number.isInteger(pricingId) && pricingId > 0 ? pricingId : false,
    };
}

function setLineSubscriptionSelection(line, planId = false, pricingId = false) {
    if (!line) {
        return;
    }
    const parsedPlanId = Number.parseInt(planId, 10);
    const parsedPricingId = Number.parseInt(pricingId, 10);
    line.wgs_subscription_plan_id = Number.isInteger(parsedPlanId) && parsedPlanId > 0 ? parsedPlanId : false;
    line.wgs_subscription_pricing_id = Number.isInteger(parsedPricingId) && parsedPricingId > 0 ? parsedPricingId : false;
}

function getLineSubscriptionEndDate(line) {
    if (!line || !line.wgs_subscription_end_date) {
        return "";
    }
    return String(line.wgs_subscription_end_date);
}

function setLineSubscriptionEndDate(line, endDateValue = "") {
    if (!line) {
        return;
    }
    const normalized = String(endDateValue || "").trim();
    line.wgs_subscription_end_date = normalized || false;

    if (line.order && typeof line.order.trigger === "function") {
        line.order.trigger("change", line.order);
    }
}

function getLineSubscriptionStartDate(line) {
    if (!line || !line.wgs_subscription_start_date) {
        return "";
    }
    return String(line.wgs_subscription_start_date);
}

function setLineSubscriptionStartDate(line, startDateValue = "") {
    if (!line) {
        return;
    }
    const normalized = String(startDateValue || "").trim();
    line.wgs_subscription_start_date = normalized || false;

    if (line.order && typeof line.order.trigger === "function") {
        line.order.trigger("change", line.order);
    }
}

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

function formatISODate(date) {
    if (!(date instanceof Date) || Number.isNaN(date.getTime())) {
        return "";
    }
    const year = date.getUTCFullYear();
    const month = `${date.getUTCMonth() + 1}`.padStart(2, "0");
    const day = `${date.getUTCDate()}`.padStart(2, "0");
    return `${year}-${month}-${day}`;
}

function getTodayUTCDate() {
    const baseDate = new Date();
    return new Date(Date.UTC(baseDate.getFullYear(), baseDate.getMonth(), baseDate.getDate()));
}

function addIntervalToDate(baseDate, intervalValue = 1, intervalUnit = "month") {
    const date = new Date(baseDate.getTime());
    const value = Math.max(1, Number.parseInt(intervalValue, 10) || 1);
    const normalizedUnit = String(intervalUnit || "month").toLowerCase();
    if (normalizedUnit === "day") {
        date.setUTCDate(date.getUTCDate() + value);
        return date;
    }
    if (normalizedUnit === "week") {
        date.setUTCDate(date.getUTCDate() + (7 * value));
        return date;
    }
    if (normalizedUnit === "year") {
        date.setUTCFullYear(date.getUTCFullYear() + value);
        return date;
    }
    date.setUTCMonth(date.getUTCMonth() + value);
    return date;
}

function getPlanMinEndDate(plan, startDateValue = "", minTermPeriods = 1) {
    if (!plan) {
        return null;
    }
    const periods = Math.max(0, Number.parseInt(minTermPeriods, 10) || 0);
    if (periods <= 0) {
        return null;
    }
    const parsedStartDate = parseISODate(String(startDateValue || "").trim());
    const utcStart = parsedStartDate || getTodayUTCDate();
    const intervalValue = Math.max(1, Number.parseInt(plan.interval_value, 10) || 1) * periods;
    const threshold = addIntervalToDate(
        utcStart,
        intervalValue,
        plan.interval_unit || "month"
    );
    // Rule is inclusive: at least the configured minimum term.
    return threshold;
}

function getLineUnitPrice(line) {
    if (!line) {
        return 0;
    }
    if (typeof line.get_unit_price === "function") {
        return Number(line.get_unit_price()) || 0;
    }
    if (typeof line.getUnitPrice === "function") {
        return Number(line.getUnitPrice()) || 0;
    }
    return Number(line.price_unit) || Number(line.price) || 0;
}

function setLineUnitPrice(line, price) {
    const unitPrice = Number(price) || 0;
    if (typeof line.set_unit_price === "function") {
        line.set_unit_price(unitPrice);
    } else if (typeof line.setUnitPrice === "function") {
        line.setUnitPrice(unitPrice);
    } else {
        line.price_unit = unitPrice;
        line.price = unitPrice;
        line.priceUnit = unitPrice;
    }

    if (line.order && typeof line.order.trigger === "function") {
        line.order.trigger("change", line.order);
    }
}

function getSubscriptionLineForParticipants(component, order = null) {
    const activeOrder = order || getCurrentOrder(component);
    if (!activeOrder) {
        return null;
    }

    const selected = getSelectedOrderline(component, activeOrder);
    if (selected && getLineQuantity(selected) > 0 && isSubscriptionProduct(getLineProduct(component, selected))) {
        return selected;
    }

    const lines = getOrderlines(activeOrder);
    for (let index = lines.length - 1; index >= 0; index -= 1) {
        const line = lines[index];
        if (getLineQuantity(line) > 0 && isSubscriptionProduct(getLineProduct(component, line))) {
            if (typeof activeOrder.select_orderline === "function") {
                activeOrder.select_orderline(line);
            } else if (typeof activeOrder.selectOrderline === "function") {
                activeOrder.selectOrderline(line);
            } else if (typeof activeOrder.selectOrderLine === "function") {
                activeOrder.selectOrderLine(line);
            } else if ("selected_orderline" in activeOrder) {
                activeOrder.selected_orderline = line;
            } else if ("selectedOrderline" in activeOrder) {
                activeOrder.selectedOrderline = line;
            }
            return line;
        }
    }

    if (selected && getLineQuantity(selected) > 0) {
        return selected;
    }

    for (let index = lines.length - 1; index >= 0; index -= 1) {
        if (getLineQuantity(lines[index]) > 0) {
            return lines[index];
        }
    }

    return null;
}

function ensureOrderlineSerializationPatched(component) {
    const order = getCurrentOrder(component);
    if (!order) {
        return;
    }

    const lines = getOrderlines(order);
    const sample = lines[0] || getSelectedOrderline(component, order);
    if (!sample || !sample.constructor || !sample.constructor.prototype) {
        return;
    }

    const proto = sample.constructor.prototype;
    if (proto[ORDERLINE_PATCH_FLAG]) {
        return;
    }

    const patchLinePayload = (payload, line) => {
        if (!payload || typeof payload !== "object") {
            return payload;
        }
        const participantIds = getLineParticipantIds(line);
        const selection = getLineSubscriptionSelection(line);
        const startDate = getLineSubscriptionStartDate(line) || false;
        const endDate = getLineSubscriptionEndDate(line) || false;
        payload.wgs_participant_ids = participantIds;
        payload.wgsParticipantIds = participantIds;
        payload.wgs_subscription_plan_id = selection.planId || false;
        payload.wgsSubscriptionPlanId = selection.planId || false;
        payload.wgs_subscription_pricing_id = selection.pricingId || false;
        payload.wgsSubscriptionPricingId = selection.pricingId || false;
        payload.wgs_subscription_start_date = startDate;
        payload.wgsSubscriptionStartDate = startDate;
        payload.wgs_subscription_end_date = endDate;
        payload.wgsSubscriptionEndDate = endDate;
        payload.wgs_subscription_config = {
            participant_ids: participantIds,
            plan_id: selection.planId || false,
            pricing_id: selection.pricingId || false,
            start_date: startDate,
            end_date: endDate,
        };
        return payload;
    };

    const baseExport = proto.export_as_JSON;
    if (typeof baseExport === "function") {
        proto.export_as_JSON = function (...args) {
            const json = baseExport.apply(this, args);
            return patchLinePayload(json, this);
        };
    }

    const baseSerialize = proto.serialize;
    if (typeof baseSerialize === "function") {
        proto.serialize = function (...args) {
            const data = baseSerialize.apply(this, args);
            return patchLinePayload(data, this);
        };
    }

    const baseInit = proto.init_from_JSON;
    if (typeof baseInit === "function") {
        proto.init_from_JSON = function (...args) {
            baseInit.apply(this, args);
            const json = args && args.length ? args[0] : null;
            const cfg = (json && json.wgs_subscription_config && typeof json.wgs_subscription_config === "object")
                ? json.wgs_subscription_config
                : {};
            this.wgs_participant_ids = getLineParticipantIds({
                wgs_participant_ids: (json && (json.wgs_participant_ids || json.wgsParticipantIds)) || cfg.participant_ids,
            });
            setLineSubscriptionSelection(
                this,
                (json && (json.wgs_subscription_plan_id || json.wgsSubscriptionPlanId)) || cfg.plan_id,
                (json && (json.wgs_subscription_pricing_id || json.wgsSubscriptionPricingId)) || cfg.pricing_id
            );
            setLineSubscriptionEndDate(
                this,
                (json && (json.wgs_subscription_end_date || json.wgsSubscriptionEndDate)) || cfg.end_date
            );
            setLineSubscriptionStartDate(
                this,
                (json && (json.wgs_subscription_start_date || json.wgsSubscriptionStartDate)) || cfg.start_date
            );
        };
    }

    proto[ORDERLINE_PATCH_FLAG] = true;
}

function ensureOrderSerializationPatched(component) {
    const order = getCurrentOrder(component);
    if (!order || !order.constructor || !order.constructor.prototype) {
        return;
    }
    const proto = order.constructor.prototype;
    if (proto[ORDER_PATCH_FLAG]) {
        return;
    }

    const patchExportPayload = function (jsonPayload, currentOrder) {
        if (!jsonPayload) {
            return jsonPayload;
        }
        const lines = getOrderlines(currentOrder);
        const configs = [];

        if (Array.isArray(jsonPayload.lines)) {
            jsonPayload.lines.forEach((uiLine, index) => {
                const line = lines[index];
                if (!line) {
                    return;
                }
                let linePayload = uiLine;
                if (Array.isArray(uiLine) && uiLine.length >= 3 && typeof uiLine[2] === "object") {
                    linePayload = uiLine[2];
                }
                if (!linePayload || typeof linePayload !== "object") {
                    return;
                }
                const selection = getLineSubscriptionSelection(line);
                const participantIds = getLineParticipantIds(line);
                const startDate = getLineSubscriptionStartDate(line) || false;
                const endDate = getLineSubscriptionEndDate(line) || false;
                const productId = getLineProductId(line);
                const quantity = getLineQuantity(line);

                linePayload.wgs_participant_ids = participantIds;
                linePayload.wgsParticipantIds = participantIds;
                linePayload.wgs_subscription_plan_id = selection.planId || false;
                linePayload.wgsSubscriptionPlanId = selection.planId || false;
                linePayload.wgs_subscription_pricing_id = selection.pricingId || false;
                linePayload.wgsSubscriptionPricingId = selection.pricingId || false;
                linePayload.wgs_subscription_start_date = startDate;
                linePayload.wgsSubscriptionStartDate = startDate;
                linePayload.wgs_subscription_end_date = endDate;
                linePayload.wgsSubscriptionEndDate = endDate;
                linePayload.wgs_subscription_config = {
                    participant_ids: participantIds,
                    plan_id: selection.planId || false,
                    pricing_id: selection.pricingId || false,
                    start_date: startDate,
                    end_date: endDate,
                    product_id: productId || false,
                    quantity: quantity || 0,
                    line_index: index,
                };

                configs.push({
                    participant_ids: participantIds,
                    plan_id: selection.planId || false,
                    pricing_id: selection.pricingId || false,
                    start_date: startDate,
                    end_date: endDate,
                    product_id: productId || false,
                    quantity: quantity || 0,
                    line_index: index,
                });
            });
        }

        // Root-level fallback payload consumed by backend parser for Odoo variants.
        jsonPayload.wgs_subscription_configs = configs;
        lines.forEach((line, index) => {
            const selection = getLineSubscriptionSelection(line);
            const participantIds = getLineParticipantIds(line);
            const startDate = getLineSubscriptionStartDate(line) || false;
            const endDate = getLineSubscriptionEndDate(line) || false;
            const productId = getLineProductId(line);
            const quantity = getLineQuantity(line);
            if (!participantIds.length && !selection.planId && !selection.pricingId && !startDate && !endDate) {
                return;
            }
            if (configs.find((row) => row.line_index === index)) {
                return;
            }
            configs.push({
                participant_ids: participantIds,
                plan_id: selection.planId || false,
                pricing_id: selection.pricingId || false,
                start_date: startDate,
                end_date: endDate,
                product_id: productId || false,
                quantity: quantity || 0,
                line_index: index,
            });
        });
        jsonPayload.wgs_subscription_configs = configs;

        return jsonPayload;
    };

    const baseExport = proto.export_as_JSON;
    if (typeof baseExport === "function") {
        proto.export_as_JSON = function (...args) {
            const json = baseExport.apply(this, args);
            return patchExportPayload(json, this);
        };
    }

    const baseExportCamel = proto.exportAsJSON;
    if (typeof baseExportCamel === "function") {
        proto.exportAsJSON = function (...args) {
            const json = baseExportCamel.apply(this, args);
            return patchExportPayload(json, this);
        };
    }

    const baseSerialize = proto.serialize;
    if (typeof baseSerialize === "function") {
        proto.serialize = function (...args) {
            const json = baseSerialize.apply(this, args);
            return patchExportPayload(json, this);
        };
    }

    proto[ORDER_PATCH_FLAG] = true;
}

function collectOrderSubscriptionConfigs(order) {
    const lines = getOrderlines(order);
    const configs = [];
    lines.forEach((line, index) => {
        if (getLineQuantity(line) <= 0) {
            return;
        }
        const productId = getLineProductId(line);
        const selection = getLineSubscriptionSelection(line);
        const participantIds = getLineParticipantIds(line);
        const startDate = getLineSubscriptionStartDate(line) || false;
        const endDate = getLineSubscriptionEndDate(line) || false;
        if (!participantIds.length && !selection.planId && !selection.pricingId && !startDate && !endDate) {
            return;
        }
        configs.push({
            participant_ids: participantIds,
            plan_id: selection.planId || false,
            pricing_id: selection.pricingId || false,
            start_date: startDate,
            end_date: endDate,
            product_id: productId || false,
            quantity: getLineQuantity(line) || 0,
            line_index: index,
        });
    });
    return configs;
}

async function getSubscriptionContext(component, product, fallbackPrice = 0) {
    if (!product || !product.id || !component.orm) {
        return { is_subscription: false, max_participants_total: 1, plans: [] };
    }

    const pos = getPos(component);
    const cache = pos
        ? (pos.wgsSubscriptionContextCache = pos.wgsSubscriptionContextCache || {})
        : (component._wgsSubscriptionContextCache = component._wgsSubscriptionContextCache || {});

    const cacheKey = String(product.id);
    if (cache[cacheKey]) {
        return cache[cacheKey];
    }

    const context = await component.orm.call(
        "pos.order",
        "wgs_get_subscription_product_context_for_pos",
        [product.id, fallbackPrice]
    );
    cache[cacheKey] = context || { is_subscription: false, max_participants_total: 1, plans: [] };
    return cache[cacheKey];
}

patch(PaymentScreen.prototype, {
    setup() {
        super.setup(...arguments);
        this.orm = useService("orm");
        this._wgsRecurringPriceCache = {};
        this._wgsSubscriptionContextCache = {};
    },

    async _wgsApplyRecurringPriceToLine(line) {
        const product = getLineProduct(this, line);
        if (!product) {
            return;
        }

        const selection = getLineSubscriptionSelection(line);
        const context = await getSubscriptionContext(this, product, getLineUnitPrice(line));
        if (!context || !context.is_subscription) {
            return;
        }

        const productId = Number(product.id || 0);
        const cacheKey = `${productId}:${selection.planId || 0}:${selection.pricingId || 0}`;
        let cached = this._wgsRecurringPriceCache[cacheKey];
        if (!cached) {
            cached = await this.orm.call(
                "pos.order",
                "wgs_get_recurring_price_for_pos",
                [productId, getLineUnitPrice(line), selection.planId || false, selection.pricingId || false]
            );
            this._wgsRecurringPriceCache[cacheKey] = cached || {};
        }

        const recurringPrice = Number(cached && cached.price);
        if (!Number.isFinite(recurringPrice) || recurringPrice <= 0) {
            return;
        }

        const currentPrice = getLineUnitPrice(line);
        if (Math.abs(currentPrice - recurringPrice) > 0.0001) {
            setLineUnitPrice(line, recurringPrice);
        }

        const resolvedPlanId = Number.parseInt(cached && cached.plan_id, 10);
        const resolvedPricingId = Number.parseInt(cached && cached.pricing_id, 10);
        setLineSubscriptionSelection(
            line,
            Number.isInteger(resolvedPlanId) && resolvedPlanId > 0 ? resolvedPlanId : selection.planId,
            Number.isInteger(resolvedPricingId) && resolvedPricingId > 0 ? resolvedPricingId : selection.pricingId
        );
    },

    async validateOrder(isForceValidate) {
        ensureOrderlineSerializationPatched(this);
        ensureOrderSerializationPatched(this);
        const order = getCurrentOrder(this);
        if (order && this.orm) {
            const orderUUID = getOrderUUID(order);
            const configs = collectOrderSubscriptionConfigs(order);
            if (orderUUID && configs.length) {
                try {
                    await this.orm.call(
                        "pos.order",
                        "wgs_stage_subscription_config_for_uuid",
                        [orderUUID, configs]
                    );
                } catch (error) {
                    console.warn("No se pudo guardar buffer de configuración de suscripción POS", error);
                }
            }
        }
        if (order) {
            const partner = getCurrentPartner(this, order);
            const lines = [];
            for (const line of getOrderlines(order)) {
                if (getLineQuantity(line) <= 0) {
                    continue;
                }
                const product = getLineProduct(this, line);
                if (!product) {
                    continue;
                }
                const context = await getSubscriptionContext(this, product, getLineUnitPrice(line));
                if (context && context.is_subscription) {
                    lines.push({ line, product, context });
                }
            }

            if (lines.length) {
                if (typeof navigator !== "undefined" && navigator.onLine === false) {
                    window.alert(_t("No se permite vender suscripciones sin conexión a internet."));
                    return;
                }

                if (!partner || !partner.id) {
                    window.alert(_t("Selecciona un cliente para vender suscripciones."));
                    return;
                }

                for (const row of lines) {
                    const line = row.line;
                    const product = row.product;
                    const context = row.context;
                    await this._wgsApplyRecurringPriceToLine(line);
                    const maxPerUnit = Number.parseInt(context.max_participants_total, 10) || product.max_participants_total || 1;
                    const capacity = getLineParticipantCapacity(
                        { ...product, max_participants_total: maxPerUnit },
                        line
                    );
                    const participantIds = getLineParticipantIds(line, partner.id);

                    if (participantIds.length > capacity) {
                        window.alert(
                            _t("Una línea de suscripción excede el máximo de participantes permitidos.")
                        );
                        return;
                    }

                    setLineParticipantIds(line, participantIds);
                }
            }
        }

        return super.validateOrder(...arguments);
    },
});

patch(ControlButtons.prototype, {
    setup() {
        super.setup(...arguments);
        this.orm = useService("orm");
        this._ensureStatusStyles();
        ensureOrderlineSerializationPatched(this);
        ensureOrderSerializationPatched(this);

        onWillUnmount(() => {
            const modal = document.getElementById(MODAL_ID);
            if (modal) {
                modal.remove();
            }
        });
    },

    async onClickSubscriptionParticipants() {
        ensureOrderlineSerializationPatched(this);
        ensureOrderSerializationPatched(this);

        if (typeof navigator !== "undefined" && navigator.onLine === false) {
            this._showSimpleInfoModal(
                _t("Sin conexión"),
                _t("No se permite vender suscripciones sin conexión a internet.")
            );
            return;
        }

        const order = getCurrentOrder(this);
        if (!order) {
            this._showSimpleInfoModal(_t("Sin orden"), _t("No hay una orden activa en este momento."));
            return;
        }

        const partner = getCurrentPartner(this, order);
        if (!partner || !partner.id) {
            this._showSimpleInfoModal(
                _t("Cliente requerido"),
                _t("Selecciona primero un cliente para configurar la suscripción.")
            );
            return;
        }

        const line = getSubscriptionLineForParticipants(this, order);
        if (!line) {
            this._showSimpleInfoModal(
                _t("Línea requerida"),
                _t("Agrega un producto de suscripción al ticket para configurarlo.")
            );
            return;
        }

        const product = getLineProduct(this, line);
        const context = await getSubscriptionContext(this, product, getLineUnitPrice(line));
        if (!context || !context.is_subscription) {
            this._showSimpleInfoModal(
                _t("Producto no válido"),
                _t("La línea seleccionada no corresponde a un producto de suscripción.")
            );
            return;
        }

        await this._wgsEnsureRecurringPriceOnLine(line, product, context);

        const maxPerUnit = Number.parseInt(context.max_participants_total, 10) || product.max_participants_total || 1;
        const capacity = getLineParticipantCapacity(
            { ...product, max_participants_total: maxPerUnit },
            line
        );
        const participants = getAllPartners(this);
        this._showParticipantsModal({
            holder: partner,
            product,
            line,
            participants,
            capacity,
            subscriptionContext: context,
        });
    },

    async onClickSubscriptionStatus() {
        const partners = getAllPartners(this);
        if (!partners.length) {
            this._showSimpleInfoModal(
                _t("Sin clientes cargados"),
                _t("No hay clientes disponibles en esta sesión de Punto de Venta.")
            );
            return;
        }

        const partnerIds = partners.map((partner) => partner.id).filter(Boolean);
        let statusMap = {};
        try {
            statusMap = await this._fetchPartnerStatusMap(partnerIds);
        } catch (error) {
            this._showSimpleInfoModal(
                _t("Error al consultar vigencia"),
                _t("No se pudo consultar la vigencia en este momento.")
            );
            console.error("Error al consultar vigencia global en POS", error);
            return;
        }

        const rows = partners.map((partner) => {
            const status = this._getPartnerStatusEntry(statusMap, partner.id) || {};
            return {
                id: partner.id,
                name: partner.name || partner.display_name || _t("Sin nombre"),
                email: partner.email || "",
                phone: partner.phone || partner.mobile || "",
                state: status.state || "none",
                valid_until: status.valid_until || "",
            };
        });

        this._showDirectoryModal(rows);
    },

    async _wgsEnsureRecurringPriceOnLine(line, product = null, providedContext = null) {
        const recurringProduct = product || getLineProduct(this, line);
        if (!recurringProduct) {
            return;
        }
        const context = providedContext || await getSubscriptionContext(this, recurringProduct, getLineUnitPrice(line));
        if (!context || !context.is_subscription) {
            return;
        }
        const productId = Number(recurringProduct.id || 0);
        if (!productId) {
            return;
        }

        const selection = getLineSubscriptionSelection(line);
        const preferredPlanId = selection.planId || context.default_plan_id || false;
        const preferredPricingId = selection.pricingId || context.default_pricing_id || false;
        const result = await this.orm.call(
            "pos.order",
            "wgs_get_recurring_price_for_pos",
            [productId, getLineUnitPrice(line), preferredPlanId, preferredPricingId]
        );
        const recurringPrice = Number(result && result.price);
        if (Number.isFinite(recurringPrice) && recurringPrice > 0) {
            const currentPrice = getLineUnitPrice(line);
            if (Math.abs(currentPrice - recurringPrice) > 0.0001) {
                setLineUnitPrice(line, recurringPrice);
            }
        }

        setLineSubscriptionSelection(
            line,
            result && result.plan_id ? result.plan_id : preferredPlanId,
            result && result.pricing_id ? result.pricing_id : preferredPricingId
        );
    },

    async _fetchPartnerStatusMap(partnerIds) {
        const statusMap = {};
        const chunkSize = 500;

        for (let index = 0; index < partnerIds.length; index += chunkSize) {
            const chunk = partnerIds.slice(index, index + chunkSize);
            const partialMap = await this.orm.call(
                "sale.order",
                "get_partner_subscription_status_map_for_pos",
                [chunk]
            );
            Object.assign(statusMap, partialMap || {});
        }

        return statusMap;
    },

    _showParticipantsModal({ holder, product, line, participants, capacity, subscriptionContext }) {
        const previous = document.getElementById(MODAL_ID);
        if (previous) {
            previous.remove();
        }

        const overlay = document.createElement("div");
        overlay.id = MODAL_ID;
        overlay.className = "wgs-status-modal-overlay";

        const modal = document.createElement("div");
        modal.className = "wgs-status-modal";

        const header = document.createElement("div");
        header.className = "wgs-status-modal-header";
        header.innerHTML = `
            <h3>${this._escapeHtml(_t("Configuración de Suscripción"))}</h3>
            <p class="wgs-subtitle">${this._escapeHtml(product.display_name || "")} | ${this._escapeHtml(_t("Cupo total"))}: ${capacity}</p>
        `;

        const toolbar = document.createElement("div");
        toolbar.className = "wgs-status-toolbar";
        const plans = Array.isArray(subscriptionContext && subscriptionContext.plans) ? subscriptionContext.plans : [];
        const selection = getLineSubscriptionSelection(line);
        const defaultPlanId = selection.planId || (subscriptionContext && subscriptionContext.default_plan_id) || (plans[0] && plans[0].plan_id) || false;
        const defaultPricingId = selection.pricingId || (subscriptionContext && subscriptionContext.default_pricing_id) || (plans[0] && plans[0].pricing_id) || false;

        const planOptions = plans.length
            ? plans
                .map((plan) => {
                    const planId = Number(plan.plan_id || 0);
                    const pricingId = Number(plan.pricing_id || 0);
                    const selected = (
                        (defaultPricingId && pricingId === Number(defaultPricingId))
                        || (!defaultPricingId && defaultPlanId && planId === Number(defaultPlanId))
                    ) ? "selected" : "";
                    const labelParts = [plan.plan_name || _t("Plan recurrente")];
                    if (plan.interval_label) {
                        labelParts.push(`(${plan.interval_label})`);
                    }
                    labelParts.push(`$${Number(plan.price || 0).toFixed(2)}`);
                    return `<option value="${planId || 0}" data-pricing-id="${pricingId || 0}" data-price="${Number(plan.price || 0)}" data-interval-value="${Number(plan.interval_value || 1)}" data-interval-unit="${this._escapeHtml(plan.interval_unit || "month")}" data-min-term-periods="${Number(plan.min_term_periods || 0)}" ${selected}>${this._escapeHtml(labelParts.join(" "))}</option>`;
                })
                .join("")
            : `<option value="0">${this._escapeHtml(_t("Sin planes configurados"))}</option>`;

        const todayISO = formatISODate(getTodayUTCDate());
        const currentStartDateValue = getLineSubscriptionStartDate(line) || todayISO;
        const currentEndDateValue = getLineSubscriptionEndDate(line);
        toolbar.innerHTML = `
            <input type="text" class="wgs-filter-search" placeholder="${_t("Buscar participante")}" />
            <select class="wgs-plan-select">${planOptions}</select>
            <input type="date" class="wgs-start-date-input" min="${this._escapeHtml(todayISO)}" value="${this._escapeHtml(currentStartDateValue)}" />
            <input type="date" class="wgs-end-date-input" value="${this._escapeHtml(currentEndDateValue)}" />
            <div class="wgs-inline-note">${_t("El titular siempre está incluido")}: <strong>${this._escapeHtml(holder.name || "")}</strong></div>
        `;

        const body = document.createElement("div");
        body.className = "wgs-status-modal-body";

        const list = document.createElement("div");
        list.className = "wgs-participant-list";
        body.appendChild(list);

        const footer = document.createElement("div");
        footer.className = "wgs-status-modal-footer";
        const counter = document.createElement("span");
        counter.className = "wgs-inline-note";
        footer.appendChild(counter);

        const cancelButton = document.createElement("button");
        cancelButton.type = "button";
        cancelButton.className = "wgs-status-close-btn wgs-btn-muted";
        cancelButton.textContent = _t("Cancelar");

        const saveButton = document.createElement("button");
        saveButton.type = "button";
        saveButton.className = "wgs-status-close-btn";
        saveButton.textContent = _t("Guardar configuración");

        footer.appendChild(cancelButton);
        footer.appendChild(saveButton);

        modal.appendChild(header);
        modal.appendChild(toolbar);
        modal.appendChild(body);
        modal.appendChild(footer);
        overlay.appendChild(modal);

        const closeModal = () => overlay.remove();
        cancelButton.addEventListener("click", closeModal);
        overlay.addEventListener("click", (event) => {
            if (event.target === overlay) {
                closeModal();
            }
        });

        document.body.appendChild(overlay);

        const searchInput = toolbar.querySelector(".wgs-filter-search");
        const planSelect = toolbar.querySelector(".wgs-plan-select");
        const startDateInput = toolbar.querySelector(".wgs-start-date-input");
        const endDateInput = toolbar.querySelector(".wgs-end-date-input");
        const holderId = holder.id;
        const selected = new Set(getLineParticipantIds(line, holderId));

        const getSelectedPlanData = () => {
            if (!planSelect) {
                return null;
            }
            const selectedOption = planSelect.options[planSelect.selectedIndex];
            if (!selectedOption) {
                return null;
            }
            const planId = Number.parseInt(planSelect.value, 10) || false;
            const pricingId = Number.parseInt((selectedOption.dataset && selectedOption.dataset.pricingId) || 0, 10) || false;
            const price = Number.parseFloat((selectedOption.dataset && selectedOption.dataset.price) || "0");
            const intervalValue = Number.parseInt((selectedOption.dataset && selectedOption.dataset.intervalValue) || "1", 10) || 1;
            const intervalUnit = (selectedOption.dataset && selectedOption.dataset.intervalUnit) || "month";
            const minTermPeriods = Math.max(0, Number.parseInt((selectedOption.dataset && selectedOption.dataset.minTermPeriods) || "0", 10) || 0);
            return { planId, pricingId, price, intervalValue, intervalUnit, minTermPeriods };
        };

        const syncDateConstraints = () => {
            if (startDateInput) {
                startDateInput.min = todayISO;
            }
            if (!endDateInput) {
                return;
            }
            const planData = getSelectedPlanData();
            if (!planData) {
                endDateInput.min = "";
                return;
            }
            const requiredTermPeriods = Math.max(1, planData.minTermPeriods || 0);
            const minDate = getPlanMinEndDate({
                interval_value: planData.intervalValue,
                interval_unit: planData.intervalUnit,
            }, (startDateInput && startDateInput.value) || "", requiredTermPeriods);
            endDateInput.min = minDate ? formatISODate(minDate) : "";
            if ((planData.minTermPeriods || 0) > 0 && minDate) {
                const currentEnd = parseISODate(String(endDateInput.value || "").trim());
                if (!currentEnd || currentEnd.getTime() < minDate.getTime()) {
                    endDateInput.value = formatISODate(minDate);
                }
            }
        };

        const syncPlanSelection = () => {
            const planData = getSelectedPlanData();
            if (!planData) {
                return;
            }
            setLineSubscriptionSelection(line, planData.planId, planData.pricingId);
            if (Number.isFinite(planData.price) && planData.price > 0) {
                const currentPrice = getLineUnitPrice(line);
                if (Math.abs(currentPrice - planData.price) > 0.0001) {
                    setLineUnitPrice(line, planData.price);
                }
            }
            syncDateConstraints();
        };

        syncPlanSelection();
        if (planSelect) {
            planSelect.addEventListener("change", () => {
                syncPlanSelection();
            });
        }
        if (startDateInput) {
            startDateInput.addEventListener("change", () => {
                syncDateConstraints();
            });
        }

        const setCounter = () => {
            counter.textContent = `${_t("Seleccionados")}: ${selected.size}/${capacity}`;
        };

        const renderList = () => {
            const query = (searchInput.value || "").trim().toLowerCase();
            const rows = participants
                .filter((partner) => partner && partner.id)
                .filter((partner) => {
                    if (!query) {
                        return true;
                    }
                    const haystack = `${partner.name || ""} ${partner.email || ""} ${partner.phone || ""}`.toLowerCase();
                    return haystack.includes(query);
                })
                .sort((a, b) => (a.name || "").localeCompare(b.name || "", "es"));

            list.innerHTML = rows
                .map((partner) => {
                    const checked = selected.has(partner.id) ? "checked" : "";
                    const disabled = partner.id === holderId ? "disabled" : "";
                    return `
                        <label class="wgs-participant-row" data-partner-id="${partner.id}">
                            <input type="checkbox" ${checked} ${disabled} />
                            <span class="wgs-participant-name">${this._escapeHtml(partner.name || _t("Sin nombre"))}</span>
                            <span class="wgs-participant-meta">${this._escapeHtml(partner.phone || partner.email || "")}</span>
                        </label>
                    `;
                })
                .join("");

            list.querySelectorAll(".wgs-participant-row input[type='checkbox']").forEach((checkbox) => {
                checkbox.addEventListener("change", (event) => {
                    const row = event.target.closest(".wgs-participant-row");
                    const partnerId = Number.parseInt(row.getAttribute("data-partner-id"), 10);
                    if (!partnerId || partnerId === holderId) {
                        return;
                    }

                    if (event.target.checked) {
                        if (selected.size >= capacity) {
                            event.target.checked = false;
                            this._showSimpleInfoModal(
                                _t("Cupo excedido"),
                                _t("No puedes exceder el máximo de participantes permitido para esta suscripción.")
                            );
                            return;
                        }
                        selected.add(partnerId);
                    } else {
                        selected.delete(partnerId);
                    }
                    selected.add(holderId);
                    setCounter();
                });
            });
        };

        searchInput.addEventListener("input", renderList);

        saveButton.addEventListener("click", () => {
            syncPlanSelection();
            selected.add(holderId);
            if (selected.size > capacity) {
                this._showSimpleInfoModal(
                    _t("Cupo excedido"),
                    _t("No puedes exceder el máximo de participantes permitido para esta suscripción.")
                );
                return;
            }
            const startDateValue = String((startDateInput && startDateInput.value) || "").trim();
            const parsedStartDate = parseISODate(startDateValue);
            if (!parsedStartDate) {
                this._showSimpleInfoModal(
                    _t("Fecha inválida"),
                    _t("La fecha de inicio no tiene un formato válido.")
                );
                return;
            }
            const todayDate = getTodayUTCDate();
            if (parsedStartDate.getTime() < todayDate.getTime()) {
                this._showSimpleInfoModal(
                    _t("Fecha de inicio inválida"),
                    _t("La fecha de inicio no puede ser anterior al día actual.")
                );
                return;
            }
            let endDateValue = String((endDateInput && endDateInput.value) || "").trim();
            const planData = getSelectedPlanData();
            const minimumTermPeriods = Math.max(0, Number.parseInt(planData && planData.minTermPeriods, 10) || 0);
            const requiredTermPeriods = Math.max(1, minimumTermPeriods);
            if (!endDateValue && minimumTermPeriods > 0) {
                const minEndDate = planData
                    ? getPlanMinEndDate(
                        {
                            interval_value: planData.intervalValue,
                            interval_unit: planData.intervalUnit,
                        },
                        startDateValue,
                        requiredTermPeriods
                    )
                    : null;
                if (minEndDate) {
                    endDateValue = formatISODate(minEndDate);
                    if (endDateInput) {
                        endDateInput.value = endDateValue;
                    }
                }
            }
            if (endDateValue) {
                const parsedEndDate = parseISODate(endDateValue);
                if (!parsedEndDate) {
                    this._showSimpleInfoModal(
                        _t("Fecha inválida"),
                        _t("La fecha de finalización no tiene un formato válido.")
                    );
                    return;
                }
                if (planData) {
                    const minEndDate = getPlanMinEndDate({
                        interval_value: planData.intervalValue,
                        interval_unit: planData.intervalUnit,
                    }, startDateValue, requiredTermPeriods);
                    if (minEndDate && parsedEndDate.getTime() < minEndDate.getTime()) {
                        this._showSimpleInfoModal(
                            _t("Fecha de finalización inválida"),
                            _t("La fecha final debe ser igual o posterior al mínimo permitido por este paquete.")
                        );
                        return;
                    }
                }
            }
            setLineParticipantIds(line, Array.from(selected));
            setLineSubscriptionStartDate(line, startDateValue || false);
            setLineSubscriptionEndDate(line, endDateValue || false);
            closeModal();
            this._showSimpleInfoModal(
                _t("Configuración guardada"),
                _t("La configuración de suscripción se aplicará al validar el ticket en POS.")
            );
        });

        setCounter();
        renderList();
    },

    _showDirectoryModal(rows) {
        const previous = document.getElementById(MODAL_ID);
        if (previous) {
            previous.remove();
        }

        const overlay = document.createElement("div");
        overlay.id = MODAL_ID;
        overlay.className = "wgs-status-modal-overlay";

        const modal = document.createElement("div");
        modal.className = "wgs-status-modal";

        const header = document.createElement("div");
        header.className = "wgs-status-modal-header";
        const title = document.createElement("h3");
        title.textContent = _t("Directorio de Vigencia de Clientes");
        header.appendChild(title);

        const toolbar = document.createElement("div");
        toolbar.className = "wgs-status-toolbar";
        toolbar.innerHTML = `
            <input type="text" class="wgs-filter-search" placeholder="${_t("Buscar por nombre, teléfono o email")}" />
            <select class="wgs-filter-state">
                <option value="all">${_t("Todos")}</option>
                <option value="valid">${_t("Vigentes")}</option>
                <option value="expired">${_t("Sin vigencia")}</option>
                <option value="none">${_t("Sin paquete")}</option>
            </select>
            <select class="wgs-sort">
                <option value="name_asc">${_t("Nombre A-Z")}</option>
                <option value="name_desc">${_t("Nombre Z-A")}</option>
                <option value="state">${_t("Estado")}</option>
                <option value="valid_until_asc">${_t("Vigencia cercana")}</option>
                <option value="valid_until_desc">${_t("Vigencia lejana")}</option>
            </select>
        `;

        const summary = document.createElement("div");
        summary.className = "wgs-status-summary";

        const body = document.createElement("div");
        body.className = "wgs-status-modal-body";

        const table = document.createElement("table");
        table.className = "wgs-status-table";
        table.innerHTML = `
            <thead>
                <tr>
                    <th>${_t("Cliente")}</th>
                    <th>${_t("Estado")}</th>
                    <th>${_t("Vigente hasta")}</th>
                    <th>${_t("Teléfono")}</th>
                    <th>${_t("Email")}</th>
                </tr>
            </thead>
            <tbody></tbody>
        `;
        body.appendChild(table);

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
        const sortSelect = toolbar.querySelector(".wgs-sort");
        const tbody = table.querySelector("tbody");

        const stateLabel = {
            valid: _t("Vigente"),
            expired: _t("Sin vigencia"),
            none: _t("Sin paquete"),
        };

        const stateRank = {
            valid: 0,
            expired: 1,
            none: 2,
        };

        const parseDate = (value) => {
            if (!value) {
                return null;
            }
            const ts = Date.parse(value);
            return Number.isNaN(ts) ? null : ts;
        };

        const render = () => {
            const query = (searchInput.value || "").trim().toLowerCase();
            const stateFilter = stateSelect.value;
            const sortMode = sortSelect.value;

            let filtered = rows.filter((row) => {
                if (stateFilter !== "all" && row.state !== stateFilter) {
                    return false;
                }
                if (!query) {
                    return true;
                }
                const haystack = `${row.name} ${row.phone} ${row.email}`.toLowerCase();
                return haystack.includes(query);
            });

            filtered = filtered.sort((a, b) => {
                if (sortMode === "name_desc") {
                    return (b.name || "").localeCompare(a.name || "", "es");
                }
                if (sortMode === "state") {
                    const diff = (stateRank[a.state] ?? 9) - (stateRank[b.state] ?? 9);
                    if (diff !== 0) {
                        return diff;
                    }
                    return (a.name || "").localeCompare(b.name || "", "es");
                }
                if (sortMode === "valid_until_asc") {
                    const av = parseDate(a.valid_until);
                    const bv = parseDate(b.valid_until);
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
                    const av = parseDate(a.valid_until);
                    const bv = parseDate(b.valid_until);
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

            const counts = rows.reduce(
                (acc, row) => {
                    acc.total += 1;
                    if (row.state === "valid") acc.valid += 1;
                    else if (row.state === "expired") acc.expired += 1;
                    else acc.none += 1;
                    return acc;
                },
                { total: 0, valid: 0, expired: 0, none: 0 }
            );

            summary.innerHTML = `
                <span class="wgs-summary-pill">${_t("Total")}: ${counts.total}</span>
                <span class="wgs-summary-pill wgs-summary-valid">${_t("Vigentes")}: ${counts.valid}</span>
                <span class="wgs-summary-pill wgs-summary-expired">${_t("Sin vigencia")}: ${counts.expired}</span>
                <span class="wgs-summary-pill wgs-summary-none">${_t("Sin paquete")}: ${counts.none}</span>
                <span class="wgs-summary-pill">${_t("Mostrando")}: ${filtered.length}</span>
            `;

            if (!filtered.length) {
                tbody.innerHTML = `<tr><td colspan="5">${_t("No hay resultados para el filtro actual.")}</td></tr>`;
                return;
            }

            tbody.innerHTML = filtered
                .map((row) => {
                    const badgeClass = row.state === "valid" ? "wgs-badge-valid" : row.state === "expired" ? "wgs-badge-expired" : "wgs-badge-none";
                    const badgeLabel = stateLabel[row.state] || stateLabel.none;
                    const untilLabel = row.valid_until || _t("N/D");
                    return `
                        <tr>
                            <td>${this._escapeHtml(row.name || "")}</td>
                            <td><span class="wgs-status-badge ${badgeClass}">${this._escapeHtml(badgeLabel)}</span></td>
                            <td>${this._escapeHtml(untilLabel)}</td>
                            <td>${this._escapeHtml(row.phone || "-")}</td>
                            <td>${this._escapeHtml(row.email || "-")}</td>
                        </tr>
                    `;
                })
                .join("");
        };

        searchInput.addEventListener("input", render);
        stateSelect.addEventListener("change", render);
        sortSelect.addEventListener("change", render);
        render();
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
                max-height: 92vh;
                overflow: hidden;
                background: #ffffff;
                border-radius: 0.75rem;
                box-shadow: 0 20px 50px rgba(0, 0, 0, 0.3);
                display: flex;
                flex-direction: column;
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
                grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
                gap: 0.6rem;
                border-bottom: 1px solid #e5e7eb;
                align-items: center;
            }
            .wgs-status-toolbar input,
            .wgs-status-toolbar select {
                width: 100%;
                border: 1px solid #d1d5db;
                border-radius: 0.45rem;
                padding: 0.45rem 0.55rem;
                font-size: 0.88rem;
                background: #fff;
                color: #111827;
            }
            .wgs-inline-note {
                color: #475569;
                font-size: 0.82rem;
                white-space: nowrap;
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
            .wgs-summary-valid {
                border-color: #8ad9b5;
                color: #0f7b4b;
                background: #daf5e8;
            }
            .wgs-summary-expired {
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
                overflow: auto;
                color: #1f2937;
            }
            .wgs-simple-message {
                padding: 1rem 1.2rem;
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
            .wgs-btn-muted {
                background: #64748b;
            }
            .wgs-status-table {
                width: 100%;
                border-collapse: collapse;
            }
            .wgs-status-table th,
            .wgs-status-table td {
                border-bottom: 1px solid #e5e7eb;
                padding: 0.55rem 0.6rem;
                text-align: left;
                vertical-align: top;
                font-size: 0.86rem;
            }
            .wgs-status-table th {
                position: sticky;
                top: 0;
                z-index: 1;
                background: #f8fafc;
                font-size: 0.76rem;
                color: #374151;
                text-transform: uppercase;
                letter-spacing: 0.03em;
            }
            .wgs-status-badge {
                border-radius: 999px;
                padding: 0.12rem 0.5rem;
                font-size: 0.72rem;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.03em;
                white-space: nowrap;
            }
            .wgs-badge-valid {
                background: #daf5e8;
                color: #0f7b4b;
                border: 1px solid #8ad9b5;
            }
            .wgs-badge-expired {
                background: #ffe4e6;
                color: #9f1239;
                border: 1px solid #fda4af;
            }
            .wgs-badge-none {
                background: #f1f5f9;
                color: #475569;
                border: 1px solid #cbd5e1;
            }
            .wgs-participant-list {
                padding: 0.75rem 1rem;
                display: flex;
                flex-direction: column;
                gap: 0.35rem;
                max-height: 58vh;
                overflow: auto;
            }
            .wgs-participant-row {
                display: grid;
                grid-template-columns: 24px 1fr auto;
                gap: 0.6rem;
                align-items: center;
                border: 1px solid #e2e8f0;
                border-radius: 0.55rem;
                padding: 0.45rem 0.65rem;
                background: #fff;
            }
            .wgs-participant-name {
                font-size: 0.88rem;
                color: #111827;
                font-weight: 600;
            }
            .wgs-participant-meta {
                font-size: 0.8rem;
                color: #64748b;
            }
            @media (max-width: 900px) {
                .wgs-status-toolbar {
                    grid-template-columns: 1fr;
                }
            }
        `;
        document.head.appendChild(style);
    },

    _getPartnerStatusEntry(statusMap, partnerId) {
        return statusMap[partnerId] || statusMap[String(partnerId)] || null;
    },
});
