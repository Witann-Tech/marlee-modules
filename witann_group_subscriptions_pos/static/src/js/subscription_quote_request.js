/** @odoo-module **/

// A replaced/closed form or a newer selection invalidates all older responses.
export function beginPricingRequest(state, key) {
    const token = {};
    const partnerId = state.selectedPartnerId;
    const mode = state.formMode;
    if (state[key]) {
        state[key].pricingRequest = token;
        state[key].pricingSnapshot = null;
    }
    return {
        isCurrent: () => state[key]?.pricingRequest === token
            && state.selectedPartnerId === partnerId && state.formMode === mode,
    };
}

export function capturePricingSelection(state, key) {
    const form = state[key];
    const partnerId = state.selectedPartnerId;
    const mode = state.formMode;
    const snapshot = form?.pricingSnapshot;
    const selectedValues = () => JSON.stringify([
        state[key]?.productId, state[key]?.startDate,
        state[key]?.participantIds, state[key]?.authorizedDiscount,
    ]);
    const values = selectedValues();
    return {
        isCurrent: () => Boolean(form) && state[key] === form
            && state.selectedPartnerId === partnerId && state.formMode === mode
            && state[key].pricingSnapshot === snapshot && selectedValues() === values,
    };
}
