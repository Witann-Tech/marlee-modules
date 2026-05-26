/** @odoo-module **/

import { parseISODate, toTimestamp } from "./subscription_view_utils";

const WGS_POS_DISPLAY_TIME_ZONE = "America/Mexico_City";

function formatMoney(value) {
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
}

function formatDateDisplay(value) {
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
}

function formatDateTimeDisplay(value) {
    if (!value) {
        return "";
    }
    const ts = toTimestamp(value);
    if (ts === null) {
        return String(value);
    }
    return new Date(ts).toLocaleString("es-MX", {
        timeZone: WGS_POS_DISPLAY_TIME_ZONE,
        day: "2-digit",
        month: "short",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
    });
}

function escapeHtml(value) {
    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
}

export {
    escapeHtml,
    formatDateDisplay,
    formatDateTimeDisplay,
    formatMoney,
};
