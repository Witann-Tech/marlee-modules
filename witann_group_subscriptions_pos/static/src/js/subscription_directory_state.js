/** @odoo-module **/

function filterDirectoryRows(rows, { query, stateFilter, birthdayFilter, matchesBirthdayFilter }) {
    const normalizedQuery = String(query || "").trim().toLowerCase();
    return (Array.isArray(rows) ? rows : []).filter((row) => {
        if (stateFilter !== "all" && (row.state || "none") !== stateFilter) {
            return false;
        }
        if (!matchesBirthdayFilter(row.birthday, birthdayFilter)) {
            return false;
        }
        if (!normalizedQuery) {
            return true;
        }
        const haystack = `${row.name || ""} ${row.phone || ""} ${row.email || ""} ${row.package_label || ""} ${row.plan_name || ""} ${row.state_label || ""}`.toLowerCase();
        return haystack.includes(normalizedQuery);
    });
}

function sortDirectoryRows(rows, { sortMode, getStateRank, toTimestamp, getBirthdaySortRank }) {
    const orderedRows = Array.isArray(rows) ? [...rows] : [];
    orderedRows.sort((a, b) => {
        if (sortMode === "name_desc") {
            return (b.name || "").localeCompare(a.name || "", "es");
        }
        if (sortMode === "state") {
            const diff = getStateRank(a.state) - getStateRank(b.state);
            if (diff !== 0) {
                return diff;
            }
            return (a.name || "").localeCompare(b.name || "", "es");
        }
        if (sortMode === "valid_until_asc") {
            const av = toTimestamp(a.valid_until);
            const bv = toTimestamp(b.valid_until);
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
            const av = toTimestamp(a.valid_until);
            const bv = toTimestamp(b.valid_until);
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
            const av = getBirthdaySortRank(a.birthday);
            const bv = getBirthdaySortRank(b.birthday);
            if (av !== bv) {
                return av - bv;
            }
            return (a.name || "").localeCompare(b.name || "", "es");
        }
        if (sortMode === "last_access_desc") {
            const av = toTimestamp(a.last_access);
            const bv = toTimestamp(b.last_access);
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
    return orderedRows;
}

function countDirectoryRows(rows) {
    return (Array.isArray(rows) ? rows : []).reduce(
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
}

export {
    countDirectoryRows,
    filterDirectoryRows,
    sortDirectoryRows,
};
