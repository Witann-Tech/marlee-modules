/** @odoo-module **/

function clearModalFeedback(state) {
    state.formError = "";
    state.formNotice = "";
}

function resetListPartnerFormState(state, { stopPartnerCamera }) {
    clearModalFeedback(state);
    stopPartnerCamera();
    state.formMode = null;
    state.newPartnerForm = null;
    state.partnerEditForm = null;
}

function resetDetailInlineForms(state, {
    stopPartnerCamera,
    selectedPartnerId,
    createNewSubscriptionForm,
}) {
    clearModalFeedback(state);
    stopPartnerCamera();
    state.formMode = null;
    state.renewalForm = null;
    state.upsaleForm = null;
    state.participantEditForm = null;
    state.newPartnerForm = null;
    state.partnerPhotoForm = null;
    state.partnerEditForm = null;
    state.newSubscriptionForm = createNewSubscriptionForm(selectedPartnerId);
}

function resetForSelectedPartner(state, {
    stopPartnerCamera,
    selectedPartnerId,
    createNewSubscriptionForm,
}) {
    resetDetailInlineForms(state, {
        stopPartnerCamera,
        selectedPartnerId,
        createNewSubscriptionForm,
    });
}

function clearDirectorySelectionState(state, {
    stopPartnerCamera,
}) {
    state.selectedPartnerId = false;
    state.currentDetail = null;
    clearModalFeedback(state);
    stopPartnerCamera();
    state.formMode = null;
    state.renewalForm = null;
    state.upsaleForm = null;
    state.participantEditForm = null;
    state.newPartnerForm = null;
    state.partnerPhotoForm = null;
    state.partnerEditForm = null;
}

export {
    clearDirectorySelectionState,
    clearModalFeedback,
    resetDetailInlineForms,
    resetForSelectedPartner,
    resetListPartnerFormState,
};
