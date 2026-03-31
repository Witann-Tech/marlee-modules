/** @odoo-module **/

function getDirectoryControls({ toolbar, table }) {
    return {
        searchInput: toolbar.querySelector(".wgs-filter-search"),
        stateSelect: toolbar.querySelector(".wgs-filter-state"),
        birthdaySelect: toolbar.querySelector(".wgs-filter-birthday"),
        sortSelect: toolbar.querySelector(".wgs-sort"),
        exportButton: toolbar.querySelector(".wgs-btn-export"),
        tbody: table.querySelector("tbody"),
    };
}

function bindDirectoryToolbarEvents({
    searchInput,
    stateSelect,
    birthdaySelect,
    sortSelect,
    exportButton,
    onSearchInput,
    onStateChange,
    onBirthdayChange,
    onSortChange,
    onExport,
}) {
    searchInput.addEventListener("input", onSearchInput);
    stateSelect.addEventListener("change", onStateChange);
    birthdaySelect.addEventListener("change", onBirthdayChange);
    sortSelect.addEventListener("change", onSortChange);
    exportButton.addEventListener("click", onExport);
}

function bindDirectoryRowSelection(tbody, onSelectPartner) {
    tbody.addEventListener("click", (event) => {
        const rowElement = event.target.closest("tr[data-partner-id]");
        if (!rowElement) {
            return;
        }
        const partnerId = Number(rowElement.dataset.partnerId || 0);
        onSelectPartner(partnerId);
    });
}

export {
    bindDirectoryRowSelection,
    bindDirectoryToolbarEvents,
    getDirectoryControls,
};
