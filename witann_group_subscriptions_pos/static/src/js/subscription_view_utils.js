/** @odoo-module **/

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
    const month = Number(match[2]) - 1;
    const day = Number(match[3]);
    const date = new Date(Date.UTC(year, month, day));
    return Number.isNaN(date.getTime()) ? null : date;
}

function formatTodayISO() {
    return new Date().toISOString().slice(0, 10);
}

function getStateRank(state) {
    return STATE_SORT_RANK[state || "other"] ?? STATE_SORT_RANK.other;
}

function getStateClass(state) {
    const value = state || "none";
    if (value === "progress") {
        return "wgs-state-positive";
    }
    if (value === "renew" || value === "paused" || value === "draft" || value === "upsell") {
        return "wgs-state-warning";
    }
    if (value === "cancel" || value === "closed") {
        return "wgs-state-negative";
    }
    return "wgs-state-neutral";
}

function toTimestamp(value) {
    if (!value) {
        return null;
    }
    const ts = Date.parse(String(value).trim());
    return Number.isNaN(ts) ? null : ts;
}

function getBirthdaySortRank(birthdayValue) {
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
}

function matchesBirthdayFilter(birthdayValue, filterMode) {
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
        return getBirthdaySortRank(birthdayValue) <= 7;
    }
    return true;
}

function canOpenNewSubscription(detail) {
    if (!detail || typeof detail !== "object") {
        return true;
    }
    const summaryState = String(detail.state || "").trim().toLowerCase();
    if (summaryState === "progress" || summaryState === "renew") {
        return false;
    }
    const items = Array.isArray(detail.items) ? detail.items : [];
    return !items.some((item) => {
        const state = String(item && item.native_state_key ? item.native_state_key : "").trim().toLowerCase();
        return state === "progress" || state === "renew";
    });
}

export {
    canOpenNewSubscription,
    formatTodayISO,
    getBirthdaySortRank,
    getStateClass,
    getStateRank,
    matchesBirthdayFilter,
    parseISODate,
    toTimestamp,
};
