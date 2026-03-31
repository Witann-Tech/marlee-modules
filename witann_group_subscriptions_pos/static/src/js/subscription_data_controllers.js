/** @odoo-module **/

async function loadDirectoryRowsInBackground(state, {
    overlay,
    render,
    fetchPartnerDirectoryBatch,
    preferredPartnerId = false,
    reset = false,
    batchSize = 250,
    _t,
}) {
    if (state.directoryLoading) {
        return;
    }
    if (reset) {
        state.rows = [];
        state.filteredSnapshot = [];
        state.detailCache.clear();
        state.currentDetail = null;
        state.selectedPartnerId = Number(preferredPartnerId || 0) || false;
        state.directoryFullyLoaded = false;
        state.directoryLoadError = "";
    }
    state.directoryLoading = true;
    render();
    let offset = state.rows.length;
    try {
        while (overlay.isConnected) {
            const batch = await fetchPartnerDirectoryBatch(offset, batchSize);
            if (!Array.isArray(batch) || !batch.length) {
                state.directoryFullyLoaded = true;
                break;
            }
            state.rows = [...state.rows, ...batch];
            state.filteredSnapshot = [...state.rows];
            if (!state.selectedPartnerId && state.rows[0]) {
                state.selectedPartnerId = Number(preferredPartnerId || state.rows[0].id || 0) || false;
            }
            offset += batch.length;
            render();
            if (batch.length < batchSize) {
                state.directoryFullyLoaded = true;
                break;
            }
        }
    } catch (error) {
        console.error("Error al consultar suscripciones en POS", error);
        state.directoryLoadError = _t("No se pudo cargar el directorio completo en este momento.");
    } finally {
        state.directoryLoading = false;
        render();
    }
}

async function reloadDirectoryRows(state, deps, preferredPartnerId = false) {
    await loadDirectoryRowsInBackground(state, {
        ...deps,
        reset: true,
        preferredPartnerId,
    });
}

async function loadDetail(state, partnerId, {
    force = false,
    renderDetail,
    renderDetailEmpty,
    renderDetailLoading,
    fetchPartnerSubscriptionDetail,
    _t,
}) {
    if (!partnerId) {
        renderDetailEmpty(
            _t("Selecciona un cliente"),
            _t("Aqui veras sus suscripciones nativas, participantes y acciones disponibles.")
        );
        return;
    }
    if (!force && state.detailCache.has(partnerId)) {
        renderDetail(state.detailCache.get(partnerId));
        return;
    }

    renderDetailLoading();
    const requestId = Number(state.detailRequestToken || 0) + 1;
    state.detailRequestToken = requestId;
    try {
        const detail = await fetchPartnerSubscriptionDetail(partnerId);
        if (requestId !== state.detailRequestToken) {
            return;
        }
        state.detailCache.set(partnerId, detail);
        if (state.selectedPartnerId === partnerId) {
            renderDetail(detail);
        }
    } catch (error) {
        if (requestId !== state.detailRequestToken) {
            return;
        }
        console.error("Error al consultar detalle de suscripciones en POS", error);
        renderDetailEmpty(
            _t("Error al cargar detalle"),
            _t("No se pudo consultar el detalle de suscripciones para este cliente.")
        );
    }
}

function selectDirectoryPartner(state, partnerId, {
    resetForPartnerSelection,
    render,
}) {
    if (!partnerId || partnerId === state.selectedPartnerId) {
        return;
    }
    state.selectedPartnerId = partnerId;
    resetForPartnerSelection();
    render();
}

function getCurrentSubscriptionItem(detail, actionButton) {
    const subscriptionId = Number(actionButton.dataset.subscriptionId || 0);
    return (detail && Array.isArray(detail.items) ? detail.items : []).find(
        (row) => Number(row.subscription_id || 0) === subscriptionId
    );
}

export {
    getCurrentSubscriptionItem,
    loadDetail,
    loadDirectoryRowsInBackground,
    reloadDirectoryRows,
    selectDirectoryPartner,
};
