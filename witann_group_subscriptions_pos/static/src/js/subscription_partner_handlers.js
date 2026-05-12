/** @odoo-module **/

function withUniqueImageUrl(imageUrl) {
    const raw = String(imageUrl || "").trim();
    if (!raw) {
        return "";
    }
    const separator = raw.includes("?") ? "&" : "?";
    return `${raw}${separator}unique=${Date.now()}`;
}

function openNewPartnerForm(state, {
    stopPartnerCamera,
    createNewSubscriptionForm,
    renderDetail,
}) {
    state.formMode = "new_partner";
    state.formError = "";
    state.formNotice = "";
    stopPartnerCamera();
    state.renewalForm = null;
    state.upsaleForm = null;
    state.pendingChargeForm = null;
    state.cancellationRefundForm = null;
    state.participantEditForm = null;
    state.newSubscriptionForm = createNewSubscriptionForm(state.selectedPartnerId);
    state.newPartnerForm = state.getDefaultNewPartnerForm();
    state.partnerPhotoForm = null;
    state.partnerEditForm = null;
    renderDetail(state.currentDetail);
}

function openPartnerPhotoForm(state, {
    stopPartnerCamera,
    renderDetail,
}) {
    if (!state.currentDetail || !state.currentDetail.partner_id) {
        return;
    }
    state.formMode = "partner_photo";
    state.formError = "";
    state.formNotice = "";
    stopPartnerCamera();
    state.renewalForm = null;
    state.upsaleForm = null;
    state.pendingChargeForm = null;
    state.cancellationRefundForm = null;
    state.participantEditForm = null;
    state.newPartnerForm = null;
    state.partnerEditForm = null;
    state.partnerPhotoForm = {
        partnerId: Number(state.currentDetail.partner_id || 0) || false,
        imageDataUrl: state.currentDetail.image_url || "",
        imageBase64: "",
        cameraActive: false,
    };
    renderDetail(state.currentDetail);
}

function openPartnerEditForm(state, {
    stopPartnerCamera,
    createPartnerEditForm,
    renderDetail,
}) {
    if (!state.currentDetail || !state.currentDetail.partner_id) {
        return;
    }
    state.formMode = "partner_edit";
    state.formError = "";
    state.formNotice = "";
    stopPartnerCamera();
    state.renewalForm = null;
    state.upsaleForm = null;
    state.pendingChargeForm = null;
    state.cancellationRefundForm = null;
    state.participantEditForm = null;
    state.newPartnerForm = null;
    state.partnerPhotoForm = null;
    state.partnerEditForm = createPartnerEditForm(state.currentDetail);
    renderDetail(state.currentDetail);
}

function buildListPartnerActionHandlers({
    state,
    clearFeedback,
    render,
    renderDetail,
    resetListPartnerForm,
    startPartnerCameraForForm,
    stopPartnerCameraForForm,
    capturePartnerCameraForForm,
    createPartner,
    stopPartnerCamera,
    reloadDirectoryRows,
    focusDirectoryPartner,
    loadDetail,
    createNewSubscriptionForm,
    openNewPartnerForm,
    overlayRoot,
    _t,
}) {
    return {
        "open-new-partner": async () => {
            openNewPartnerForm();
            render();
        },
        "cancel-new-partner": async () => {
            resetListPartnerForm();
            render();
        },
        "start-partner-camera": async () => {
            await startPartnerCameraForForm(state.newPartnerForm, render, "Error al abrir cámara para partner POS");
        },
        "stop-partner-camera": async () => {
            stopPartnerCameraForForm(state.newPartnerForm, render);
        },
        "capture-partner-camera": async () => {
            capturePartnerCameraForForm(state.newPartnerForm, overlayRoot, render);
        },
        "save-new-partner": async () => {
            clearFeedback();
            if (!state.newPartnerForm || !String(state.newPartnerForm.name || "").trim()) {
                state.formError = _t("Debes capturar el nombre del cliente.");
                render();
                return;
            }
            try {
                const result = await createPartner({
                    name: state.newPartnerForm.name || "",
                    phone: state.newPartnerForm.phone || "",
                    email: state.newPartnerForm.email || "",
                    curp: state.newPartnerForm.curp || "",
                    gender: state.newPartnerForm.gender || false,
                    birthday: state.newPartnerForm.birthday || false,
                    image_1920: state.newPartnerForm.imageBase64 || false,
                });
                if (!result || result.ok === false) {
                    state.formError = result && result.error_message
                        ? result.error_message
                        : _t("No se pudo crear el cliente.");
                    render();
                    return;
                }
                stopPartnerCamera();
                state.formMode = null;
                state.newPartnerForm = null;
                state.formError = "";
                state.formNotice = _t("Cliente creado correctamente.");
                if (result && result.partner_id) {
                    state.newSubscriptionForm = createNewSubscriptionForm(result.partner_id);
                    if (focusDirectoryPartner) {
                        await focusDirectoryPartner(result.partner_id);
                    } else {
                        await reloadDirectoryRows(result.partner_id);
                        await loadDetail(result.partner_id, { force: true });
                    }
                }
            } catch (error) {
                console.error("Error al crear cliente desde POS", error);
                state.formError = (error && error.message) ? error.message : _t("No se pudo crear el cliente.");
                render();
            }
        },
    };
}

function buildDetailPartnerActionHandlers({
    state,
    clearFeedback,
    render,
    renderDetail,
    resetListPartnerForm,
    startPartnerCameraForForm,
    stopPartnerCameraForForm,
    capturePartnerCameraForForm,
    createPartner,
    updatePartner,
    updatePartnerPhoto,
    stopPartnerCamera,
    reloadDirectoryRows,
    focusDirectoryPartner,
    loadDetail,
    createNewSubscriptionForm,
    createPartnerEditForm,
    openNewPartnerForm,
    openPartnerPhotoForm,
    openPartnerEditForm,
    overlayRoot,
    detailRoot,
    detailCache,
    _t,
}) {
    return {
        "open-new-partner": async () => {
            openNewPartnerForm();
        },
        "cancel-new-partner": async () => {
            resetListPartnerForm();
            render();
        },
        "start-partner-camera": async () => {
            await startPartnerCameraForForm(state.newPartnerForm, () => renderDetail(state.currentDetail), "Error al abrir cámara para partner POS");
        },
        "stop-partner-camera": async () => {
            stopPartnerCameraForForm(state.newPartnerForm, () => renderDetail(state.currentDetail));
        },
        "open-partner-photo": async () => {
            openPartnerPhotoForm();
        },
        "open-partner-edit": async () => {
            openPartnerEditForm();
        },
        "cancel-partner-edit": async () => {
            clearFeedback();
            stopPartnerCamera();
            state.formMode = null;
            state.partnerEditForm = null;
            renderDetail(state.currentDetail);
        },
        "cancel-partner-photo": async () => {
            clearFeedback();
            stopPartnerCamera();
            state.formMode = null;
            state.partnerPhotoForm = null;
            state.partnerEditForm = null;
            renderDetail(state.currentDetail);
        },
        "start-existing-partner-camera": async () => {
            await startPartnerCameraForForm(state.partnerPhotoForm, () => renderDetail(state.currentDetail), "Error al abrir cámara para editar foto POS");
        },
        "stop-existing-partner-camera": async () => {
            stopPartnerCameraForForm(state.partnerPhotoForm, () => renderDetail(state.currentDetail));
        },
        "capture-existing-partner-camera": async () => {
            capturePartnerCameraForForm(state.partnerPhotoForm, overlayRoot, () => renderDetail(state.currentDetail));
        },
        "capture-partner-camera": async () => {
            capturePartnerCameraForForm(state.newPartnerForm, detailRoot, () => renderDetail(state.currentDetail));
        },
        "save-new-partner": async () => {
            clearFeedback();
            if (!state.newPartnerForm || !String(state.newPartnerForm.name || "").trim()) {
                state.formError = _t("Debes capturar el nombre del cliente.");
                renderDetail(state.currentDetail);
                return;
            }
            try {
                const result = await createPartner({
                    name: state.newPartnerForm.name || "",
                    phone: state.newPartnerForm.phone || "",
                    email: state.newPartnerForm.email || "",
                    curp: state.newPartnerForm.curp || "",
                    gender: state.newPartnerForm.gender || false,
                    birthday: state.newPartnerForm.birthday || false,
                    image_1920: state.newPartnerForm.imageBase64 || false,
                });
                if (!result || result.ok === false) {
                    state.formError = result && result.error_message
                        ? result.error_message
                        : _t("No se pudo crear el cliente.");
                    renderDetail(state.currentDetail);
                    return;
                }
                stopPartnerCamera();
                state.formMode = null;
                state.newPartnerForm = null;
                state.formError = "";
                state.formNotice = _t("Cliente creado correctamente.");
                if (result && result.partner_id) {
                    state.newSubscriptionForm = createNewSubscriptionForm(result.partner_id);
                    if (focusDirectoryPartner) {
                        await focusDirectoryPartner(result.partner_id);
                    } else {
                        await reloadDirectoryRows(result.partner_id);
                        await loadDetail(result.partner_id, { force: true });
                    }
                }
            } catch (error) {
                console.error("Error al crear cliente desde POS", error);
                state.formError = (error && error.message) ? error.message : _t("No se pudo crear el cliente.");
                renderDetail(state.currentDetail);
            }
        },
        "save-partner-edit": async () => {
            clearFeedback();
            if (!state.partnerEditForm || !state.partnerEditForm.partnerId) {
                state.formError = _t("No se encontró el cliente a editar.");
                renderDetail(state.currentDetail);
                return;
            }
            if (!String(state.partnerEditForm.name || "").trim()) {
                state.formError = _t("Debes capturar el nombre del cliente.");
                renderDetail(state.currentDetail);
                return;
            }
            try {
                const result = await updatePartner(state.partnerEditForm.partnerId, {
                    name: state.partnerEditForm.name || "",
                    phone: state.partnerEditForm.phone || "",
                    email: state.partnerEditForm.email || "",
                    curp: state.partnerEditForm.curp || "",
                    gender: state.partnerEditForm.gender || false,
                    birthday: state.partnerEditForm.birthday || false,
                });
                if (!result || result.ok === false) {
                    state.formError = result && result.error_message
                        ? result.error_message
                        : _t("No se pudo actualizar el cliente.");
                    renderDetail(state.currentDetail);
                    return;
                }
                if (state.currentDetail && Number(state.currentDetail.partner_id || 0) === Number(result.partner_id || 0)) {
                    state.currentDetail = {
                        ...state.currentDetail,
                        partner_name: result.partner_name || state.currentDetail.partner_name,
                        phone: result.phone || false,
                        email: result.email || false,
                        curp: result.curp || false,
                        gender: result.gender || false,
                        birthday: result.birthday || false,
                    };
                }
                state.formMode = null;
                state.partnerEditForm = null;
                renderDetail(state.currentDetail);
                detailCache.delete(Number(result && result.partner_id ? result.partner_id : 0));
                await reloadDirectoryRows(result && result.partner_id ? result.partner_id : false);
                await loadDetail(state.selectedPartnerId, { force: true });
            } catch (error) {
                console.error("Error al actualizar cliente POS", error);
                state.formError = (error && error.message) ? error.message : _t("No se pudo actualizar el cliente.");
                renderDetail(state.currentDetail);
            }
        },
        "save-partner-photo": async () => {
            clearFeedback();
            if (!state.partnerPhotoForm || !state.partnerPhotoForm.partnerId || !state.partnerPhotoForm.imageBase64) {
                state.formError = _t("Debes seleccionar o capturar una foto antes de guardar.");
                renderDetail(state.currentDetail);
                return;
            }
            try {
                const result = await updatePartnerPhoto(state.partnerPhotoForm.partnerId, state.partnerPhotoForm.imageBase64);
                stopPartnerCamera();
                const freshImageUrl = withUniqueImageUrl(
                    result && result.image_url ? result.image_url : state.partnerPhotoForm.imageDataUrl
                );
                if (state.currentDetail && Number(state.currentDetail.partner_id || 0) === Number(state.partnerPhotoForm.partnerId || 0)) {
                    state.currentDetail = {
                        ...state.currentDetail,
                        image_url: freshImageUrl,
                    };
                }
                if (Array.isArray(state.rows)) {
                    state.rows = state.rows.map((row) => {
                        if (Number(row && row.id ? row.id : 0) !== Number(state.partnerPhotoForm.partnerId || 0)) {
                            return row;
                        }
                        return {
                            ...row,
                            image_url: freshImageUrl,
                        };
                    });
                }
                state.formMode = null;
                state.partnerPhotoForm = null;
                state.formNotice = _t("Foto actualizada correctamente.");
                renderDetail(state.currentDetail);
                detailCache.delete(Number(state.currentDetail && state.currentDetail.partner_id ? state.currentDetail.partner_id : 0));
                await reloadDirectoryRows(result && result.partner_id ? result.partner_id : false);
                await loadDetail(state.selectedPartnerId, { force: true });
            } catch (error) {
                console.error("Error al actualizar foto de cliente POS", error);
                state.formError = (error && error.message) ? error.message : _t("No se pudo actualizar la foto del cliente.");
                renderDetail(state.currentDetail);
            }
        },
    };
}

async function handleListPartnerFieldChange({ field, target }, {
    state,
    clearFeedback,
    readFileAsDataUrl,
    applyImageDataUrlToForm,
    render,
    _t,
}) {
    clearFeedback();
    if (state.formMode === "new_partner" && field === "partner_gender") {
        state.newPartnerForm.gender = target.value || "";
    } else if (state.formMode === "partner_edit" && field === "partner_gender") {
        state.partnerEditForm.gender = target.value || "";
    } else if (state.formMode === "new_partner" && field === "partner_birthday") {
        state.newPartnerForm.birthday = target.value || "";
    } else if (state.formMode === "partner_edit" && field === "partner_birthday") {
        state.partnerEditForm.birthday = target.value || "";
    } else if (state.formMode === "new_partner" && field === "partner_image_file") {
        const file = target.files && target.files[0];
        if (file) {
            try {
                const dataUrl = await readFileAsDataUrl(file);
                applyImageDataUrlToForm(state.newPartnerForm, dataUrl);
            } catch (error) {
                console.error("Error al leer foto de partner POS", error);
                state.formError = _t("No se pudo procesar la foto seleccionada.");
            }
        }
        render();
    }
}

function handleListPartnerFieldInput({ field, target }, { state }) {
    if (state.formMode === "new_partner" && field === "partner_name") {
        state.newPartnerForm.name = target.value || "";
    } else if (state.formMode === "partner_edit" && field === "partner_name") {
        state.partnerEditForm.name = target.value || "";
    } else if (state.formMode === "new_partner" && field === "partner_phone") {
        state.newPartnerForm.phone = target.value || "";
    } else if (state.formMode === "partner_edit" && field === "partner_phone") {
        state.partnerEditForm.phone = target.value || "";
    } else if (state.formMode === "new_partner" && field === "partner_email") {
        state.newPartnerForm.email = target.value || "";
    } else if (state.formMode === "partner_edit" && field === "partner_email") {
        state.partnerEditForm.email = target.value || "";
    } else if (state.formMode === "new_partner" && field === "partner_curp") {
        state.newPartnerForm.curp = target.value || "";
    } else if (state.formMode === "partner_edit" && field === "partner_curp") {
        state.partnerEditForm.curp = target.value || "";
    }
}

async function handleDetailPartnerFieldChange({ field, target }, {
    state,
    clearFeedback,
    readFileAsDataUrl,
    applyImageDataUrlToForm,
    renderDetail,
    _t,
}) {
    clearFeedback();
    if (state.formMode === "new_partner" && field === "partner_gender") {
        state.newPartnerForm.gender = target.value || "";
    } else if (state.formMode === "partner_edit" && field === "partner_gender") {
        state.partnerEditForm.gender = target.value || "";
    } else if (state.formMode === "new_partner" && field === "partner_birthday") {
        state.newPartnerForm.birthday = target.value || "";
    } else if (state.formMode === "partner_edit" && field === "partner_birthday") {
        state.partnerEditForm.birthday = target.value || "";
    } else if (state.formMode === "partner_photo" && field === "existing_partner_image_file") {
        const file = target.files && target.files[0];
        if (file) {
            try {
                const dataUrl = await readFileAsDataUrl(file);
                applyImageDataUrlToForm(state.partnerPhotoForm, dataUrl);
            } catch (error) {
                console.error("Error al leer foto existente de partner POS", error);
                state.formError = _t("No se pudo procesar la foto seleccionada.");
            }
        }
    } else {
        return false;
    }
    renderDetail(state.currentDetail);
    return true;
}

function handleDetailPartnerFieldInput({ field, target }, {
    state,
}) {
    if (state.formMode === "new_partner" && field === "partner_name") {
        state.newPartnerForm.name = target.value || "";
        return true;
    }
    if (state.formMode === "partner_edit" && field === "partner_name") {
        state.partnerEditForm.name = target.value || "";
        return true;
    }
    if (state.formMode === "new_partner" && field === "partner_phone") {
        state.newPartnerForm.phone = target.value || "";
        return true;
    }
    if (state.formMode === "partner_edit" && field === "partner_phone") {
        state.partnerEditForm.phone = target.value || "";
        return true;
    }
    if (state.formMode === "new_partner" && field === "partner_email") {
        state.newPartnerForm.email = target.value || "";
        return true;
    }
    if (state.formMode === "partner_edit" && field === "partner_email") {
        state.partnerEditForm.email = target.value || "";
        return true;
    }
    if (state.formMode === "new_partner" && field === "partner_curp") {
        state.newPartnerForm.curp = target.value || "";
        return true;
    }
    if (state.formMode === "partner_edit" && field === "partner_curp") {
        state.partnerEditForm.curp = target.value || "";
        return true;
    }
    return false;
}

export {
    buildDetailPartnerActionHandlers,
    buildListPartnerActionHandlers,
    handleDetailPartnerFieldChange,
    handleDetailPartnerFieldInput,
    handleListPartnerFieldChange,
    handleListPartnerFieldInput,
    openNewPartnerForm,
    openPartnerEditForm,
    openPartnerPhotoForm,
};
