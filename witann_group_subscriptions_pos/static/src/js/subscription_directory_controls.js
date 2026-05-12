/** @odoo-module **/

function getDirectoryControls({ toolbar, table }) {
    return {
        searchInput: toolbar.querySelector(".wgs-filter-search"),
        stateSelect: toolbar.querySelector(".wgs-filter-state"),
        birthdaySelect: toolbar.querySelector(".wgs-filter-birthday"),
        sortSelect: toolbar.querySelector(".wgs-sort"),
        exportButton: toolbar.querySelector(".wgs-btn-export"),
        prevPageButton: toolbar.querySelector(".wgs-btn-page-prev"),
        nextPageButton: toolbar.querySelector(".wgs-btn-page-next"),
        pageLabel: toolbar.querySelector(".wgs-directory-page-label"),
        tbody: table.querySelector("tbody"),
    };
}

function bindDirectoryToolbarEvents({
    searchInput,
    stateSelect,
    birthdaySelect,
    sortSelect,
    exportButton,
    prevPageButton,
    nextPageButton,
    onSearchInput,
    onStateChange,
    onBirthdayChange,
    onSortChange,
    onExport,
    onPrevPage,
    onNextPage,
}) {
    searchInput.addEventListener("input", onSearchInput);
    stateSelect.addEventListener("change", onStateChange);
    birthdaySelect.addEventListener("change", onBirthdayChange);
    sortSelect.addEventListener("change", onSortChange);
    exportButton.addEventListener("click", onExport);
    prevPageButton.addEventListener("click", onPrevPage);
    nextPageButton.addEventListener("click", onNextPage);
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
