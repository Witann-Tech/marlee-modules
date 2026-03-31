/** @odoo-module **/

import {
    addConfiguredProductLineToOrder,
    collectSubscriptionConfigsFromOrder,
    findPartnerInPos,
    findProductInPos,
    getAllLocalPosProducts,
    getCurrentOrder,
    getLineQty,
    getOrderLines,
    getOrderUid,
    getPartnerIdFromOrder,
    getPos,
    getProductIdFromLine,
    getSubscriptionPartnerIdsFromOrder,
    setPartnerOnCurrentOrder,
    waitForNextTick,
} from "./subscription_ticket";
import { createSubscriptionPosApi } from "./subscription_pos_api";
import {
    getDefaultNewPartnerForm,
    getDefaultNewSubscriptionForm,
    getDefaultParticipantEditForm,
    getDefaultUpsaleForm,
} from "./subscription_form_defaults";
import {
    formatTodayISO,
    getBirthdaySortRank,
    getStateClass,
    getStateRank,
    matchesBirthdayFilter,
    parseISODate,
    toTimestamp,
} from "./subscription_view_utils";
import {
    escapeHtml,
    formatDateDisplay,
    formatDateTimeDisplay,
    formatMoney,
} from "./subscription_format_utils";
import {
    readFileAsDataUrl,
    showSimpleInfoModal,
    stripDataUrlPrefix,
} from "./subscription_modal_helpers";
import {
    downloadDirectoryAsXls,
    renderDirectoryRows,
    renderDirectorySummary,
} from "./subscription_directory_render";
import {
    countDirectoryRows,
    filterDirectoryRows,
    sortDirectoryRows,
} from "./subscription_directory_state";
import {
    bindDirectoryRowSelection,
    bindDirectoryToolbarEvents,
    getDirectoryControls,
} from "./subscription_directory_controls";
import {
    bindActionMap,
    bindFieldChange,
    bindFieldInput,
} from "./subscription_event_bindings";
import {
    renderDetailEmpty as buildDetailEmptyHtml,
    renderDetailHeader,
    renderDetailLoading as buildDetailLoadingHtml,
} from "./subscription_detail_render";
import {
    renderPendingDocumentSummary,
    renderSubscriptionCard,
} from "./subscription_card_render";
import { renderPartnerDetailAvatar } from "./subscription_partner_render";
import { renderPendingChargeForm as buildPendingChargeFormHtml } from "./subscription_pending_render";
import { renderParticipantEditForm as buildParticipantEditFormHtml } from "./subscription_participants_render";
import { renderRenewalForm as buildRenewalFormHtml } from "./subscription_renewal_render";
import { renderUpsaleForm as buildUpsaleFormHtml } from "./subscription_upsale_render";
import {
    clearDirectorySelectionState,
    clearModalFeedback,
    resetDetailInlineForms,
    resetForSelectedPartner,
    resetListPartnerFormState,
} from "./subscription_modal_state";
import {
    buildDetailPartnerActionHandlers,
    buildListPartnerActionHandlers,
    handleDetailPartnerFieldChange,
    handleDetailPartnerFieldInput,
    handleListPartnerFieldChange,
    handleListPartnerFieldInput,
    openNewPartnerForm as openNewPartnerFormState,
    openPartnerPhotoForm as openPartnerPhotoFormState,
} from "./subscription_partner_handlers";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { onWillUnmount } from "@odoo/owl";

const MODAL_ID = "wgs-subscription-status-modal";
const STYLE_ID = "wgs-subscription-status-style";

function captureFocusState(root) {
    const active = document.activeElement;
    if (!root || !active || !root.contains(active)) {
        return null;
    }
    const field = active.dataset && active.dataset.field ? active.dataset.field : "";
    const selector = field
        ? `[data-field="${field}"]`
        : active.classList && active.classList.contains("wgs-filter-search")
            ? ".wgs-filter-search"
            : "";
    if (!selector) {
        return null;
    }
    return {
        selector,
        start: typeof active.selectionStart === "number" ? active.selectionStart : null,
        end: typeof active.selectionEnd === "number" ? active.selectionEnd : null,
    };
}

function restoreFocusState(root, state) {
    if (!root || !state || !state.selector) {
        return;
    }
    const target = root.querySelector(state.selector);
    if (!target || typeof target.focus !== "function") {
        return;
    }
    target.focus({ preventScroll: true });
    if (
        typeof state.start === "number"
        && typeof state.end === "number"
        && typeof target.setSelectionRange === "function"
    ) {
        target.setSelectionRange(state.start, state.end);
    }
}

function isInteractiveModalField(target) {
    if (!target || typeof target.closest !== "function") {
        return false;
    }
    return Boolean(
        target.closest("input, textarea, select, button, label, [contenteditable='true']")
    );
}

async function stageSubscriptionConfigsForOrder(orm, order) {
    const configs = collectSubscriptionConfigsFromOrder(order);
    if (!configs.length) {
        return { ok: true, skipped: true };
    }
    const rawIds = [getOrderUid(order), order && order.uid, order && order.uuid].filter(Boolean);
    const orderIds = [...new Set(rawIds.map((value) => String(value).trim()).filter(Boolean))];
    if (!orderIds.length) {
        return { ok: false, reason: "missing_uuid" };
    }
    let lastResult = { ok: true };
    for (const orderId of orderIds) {
        lastResult = await orm.call("pos.order", "wgs_stage_subscription_config_for_uuid", [orderId, configs]);
        if (!lastResult || !lastResult.ok) {
            return lastResult || { ok: false, reason: "unknown" };
        }
    }
    return lastResult;
}

function addPeriodToDate(dateValue, intervalValue, intervalUnit) {
    const parsed = parseISODate(String(dateValue || "").trim());
    if (!parsed) {
        return "";
    }
    const date = new Date(parsed.getUTCFullYear(), parsed.getUTCMonth(), parsed.getUTCDate());
    const value = Math.max(1, Number(intervalValue || 1));
    const unit = String(intervalUnit || "month").toLowerCase();
    if (unit.includes("day")) {
        date.setDate(date.getDate() + value);
    } else if (unit.includes("week")) {
        date.setDate(date.getDate() + (value * 7));
    } else if (unit.includes("year")) {
        date.setFullYear(date.getFullYear() + value);
    } else {
        date.setMonth(date.getMonth() + value);
    }
    return date.toISOString().slice(0, 10);
}

function addDaysToDate(dateValue, days) {
    const parsed = parseISODate(String(dateValue || "").trim());
    if (!parsed) {
        return "";
    }
    const date = new Date(parsed.getUTCFullYear(), parsed.getUTCMonth(), parsed.getUTCDate());
    date.setDate(date.getDate() + Number(days || 0));
    return date.toISOString().slice(0, 10);
}

function getPlanPeriodEndDate(dateValue, intervalValue, intervalUnit) {
    const periodNextDate = addPeriodToDate(dateValue, intervalValue, intervalUnit);
    if (!periodNextDate) {
        return "";
    }
    return addDaysToDate(periodNextDate, -1);
}

function buildChargeBreakdown(source, product, values = {}) {
    const baseAmount = Number(
        values.baseAmount !== undefined
            ? values.baseAmount
            : (values.amount !== undefined ? values.amount : 0)
    ) || 0;
    const displayAmount = Number(
        values.displayAmount !== undefined
            ? values.displayAmount
            : (values.display !== undefined
                ? values.display
                : (values.amount !== undefined ? values.amount : baseAmount))
    ) || 0;
    const ticketUnitPrice = Number(
        values.ticketUnitPrice !== undefined
            ? values.ticketUnitPrice
            : (values.unitPrice !== undefined
                ? values.unitPrice
                : (baseAmount || displayAmount))
    ) || 0;
    return {
        baseAmount,
        displayAmount,
        ticketUnitPrice,
    };
}

function getChargeDisplayAmount(charge) {
    if (!charge || typeof charge !== "object") {
        return 0;
    }
    return Number(
        charge.displayAmount !== undefined
            ? charge.displayAmount
            : (charge.baseAmount !== undefined ? charge.baseAmount : 0)
    ) || 0;
}

patch(ControlButtons.prototype, {
    setup() {
        super.setup(...arguments);
        this.orm = useService("orm");
        this.subscriptionPosApi = createSubscriptionPosApi(this.orm);
        this._ensureStatusStyles();

        onWillUnmount(() => {
            const modal = document.getElementById(MODAL_ID);
            if (modal) {
                modal.remove();
            }
        });
    },

    async onClickSubscriptionStatus() {
        this._showSubscriptionsModal([]);
    },

    async _fetchPartnerDirectoryRows() {
        const rows = [];
        const batchSize = 500;
        let offset = 0;

        while (true) {
            const batch = await this.subscriptionPosApi.fetchPartnerDirectoryBatch(offset, batchSize);
            if (!Array.isArray(batch) || !batch.length) {
                break;
            }
            rows.push(...batch);
            if (batch.length < batchSize) {
                break;
            }
            offset += batchSize;
        }

        return rows;
    },

    async _fetchPartnerSubscriptionDetail(partnerId) {
        return this.subscriptionPosApi.fetchPartnerSubscriptionDetail(partnerId);
    },

    async _createPartnerForPos(values) {
        return this.subscriptionPosApi.createPartner(values || {});
    },

    async _updatePartnerPhotoForPos(partnerId, imageBase64) {
        return this.subscriptionPosApi.updatePartnerPhoto(partnerId, imageBase64 || false);
    },

    async _fetchSubscriptionProductCatalog(searchTerm = "") {
        const backendCatalog = await this.subscriptionPosApi.fetchSubscriptionProductCatalog(searchTerm, 200);
        const localProducts = getAllLocalPosProducts(this);
        const localIds = new Set(
            (localProducts || [])
                .map((product) => Number(product && product.id ? product.id : 0))
                .filter((id) => id > 0)
        );
        return (Array.isArray(backendCatalog) ? backendCatalog : []).filter((item) => {
            return localIds.has(Number(item && item.id ? item.id : 0));
        });
    },

    async _fetchSubscriptionCharge(partnerId, productId, fallback = 0, planId = false, pricingId = false) {
        return this.subscriptionPosApi.fetchSubscriptionCharge(
            partnerId || false,
            productId,
            fallback || 0,
            planId || false,
            pricingId || false
        );
    },

    async _fetchSubscriptionRenewalCharge(subscriptionId, productId = false, planId = false, pricingId = false) {
        return this.subscriptionPosApi.fetchSubscriptionRenewalCharge(
            subscriptionId,
            productId || false,
            planId || false,
            pricingId || false
        );
    },

    async _fetchSubscriptionUpsaleCharge(subscriptionId, productId, fallback = 0, planId = false, pricingId = false) {
        return this.subscriptionPosApi.fetchSubscriptionUpsaleCharge(
            subscriptionId,
            productId,
            fallback || 0,
            planId || false,
            pricingId || false
        );
    },

    async _fetchSubscriptionPendingCharge(subscriptionId, pendingMoveId = false) {
        return this.subscriptionPosApi.fetchSubscriptionPendingCharge(subscriptionId, pendingMoveId || false);
    },

    async _fetchSubscriptionCancellationRefund(subscriptionId) {
        return this.subscriptionPosApi.fetchSubscriptionCancellationRefund(subscriptionId);
    },

    async _saveSubscriptionParticipants(subscriptionId, participantIds) {
        return this.subscriptionPosApi.saveSubscriptionParticipants(subscriptionId, participantIds || []);
    },

    async _resyncSubscriptionAccess(subscriptionId) {
        return this.subscriptionPosApi.resyncSubscriptionAccess(subscriptionId);
    },

    _showSubscriptionsModal(rows) {
        rows = Array.isArray(rows) ? [...rows] : [];
        const previous = document.getElementById(MODAL_ID);
        if (previous) {
            previous.remove();
        }

        const overlay = document.createElement("div");
        overlay.id = MODAL_ID;
        overlay.className = "wgs-status-modal-overlay";

        const modal = document.createElement("div");
        modal.className = "wgs-status-modal wgs-directory-modal";

        const header = document.createElement("div");
        header.className = "wgs-status-modal-header";
        header.innerHTML = `
            <h3>${this._escapeHtml(_t("Suscripciones"))}</h3>
            <p class="wgs-subtitle">${this._escapeHtml(_t("Directorio de clientes con detalle de suscripciones nativas, participantes y datos clave."))}</p>
        `;

        const toolbar = document.createElement("div");
        toolbar.className = "wgs-status-toolbar";
        toolbar.innerHTML = `
            <input type="text" class="wgs-filter-search" placeholder="${_t("Buscar por cliente, paquete, telefono o email")}" />
            <select class="wgs-filter-state">
                <option value="all">${_t("Estado: Todos")}</option>
                <option value="progress">${_t("Estado: En progreso")}</option>
                <option value="renew">${_t("Estado: Por renovar")}</option>
                <option value="paused">${_t("Estado: Pausada")}</option>
                <option value="draft">${_t("Estado: Borrador")}</option>
                <option value="cancel">${_t("Estado: Cancelada")}</option>
                <option value="closed">${_t("Estado: Cerrada")}</option>
                <option value="other">${_t("Estado: Otros")}</option>
                <option value="none">${_t("Estado: Sin suscripcion")}</option>
            </select>
            <select class="wgs-filter-birthday">
                <option value="all">${_t("Cumpleanos: Todos")}</option>
                <option value="today">${_t("Cumpleanos: Hoy")}</option>
                <option value="this_month">${_t("Cumpleanos: Este mes")}</option>
                <option value="next_7">${_t("Cumpleanos: Proximos 7 dias")}</option>
                <option value="missing">${_t("Cumpleanos: Sin dato")}</option>
            </select>
            <select class="wgs-sort">
                <option value="name_asc">${_t("Orden: Nombre A-Z")}</option>
                <option value="name_desc">${_t("Orden: Nombre Z-A")}</option>
                <option value="state">${_t("Orden: Estado")}</option>
                <option value="valid_until_asc">${_t("Orden: Vencimiento cercano")}</option>
                <option value="valid_until_desc">${_t("Orden: Vencimiento lejano")}</option>
                <option value="birthday_asc">${_t("Orden: Cumpleanos proximo")}</option>
                <option value="last_access_desc">${_t("Orden: Ultimo acceso reciente")}</option>
            </select>
            <button type="button" class="wgs-status-close-btn wgs-btn-export">${this._escapeHtml(_t("Descargar XLS"))}</button>
        `;

        const summary = document.createElement("div");
        summary.className = "wgs-status-summary";

        const body = document.createElement("div");
        body.className = "wgs-status-modal-body";

        const layout = document.createElement("div");
        layout.className = "wgs-subscription-layout";

        const listPane = document.createElement("div");
        listPane.className = "wgs-subscription-list-pane";
        const listActions = document.createElement("div");
        listActions.className = "wgs-list-actions-bar";
        listActions.innerHTML = `
            <button type="button" class="wgs-primary-action-btn" data-action="open-new-partner">${this._escapeHtml(_t("Nuevo cliente"))}</button>
        `;
        const listFormContainer = document.createElement("div");
        listFormContainer.className = "wgs-list-form-container";
        const table = document.createElement("table");
        table.className = "wgs-status-table wgs-subscription-table";
        table.innerHTML = `
            <thead>
                <tr>
                    <th>${_t("Foto")}</th>
                    <th>${_t("Cliente")}</th>
                    <th>${_t("Estado")}</th>
                    <th>${_t("Paquete")}</th>
                    <th>${_t("Plan")}</th>
                    <th>${_t("Vencimiento")}</th>
                    <th>${_t("Ultimo acceso")}</th>
                </tr>
            </thead>
            <tbody></tbody>
        `;
        listPane.appendChild(listActions);
        listPane.appendChild(listFormContainer);
        listPane.appendChild(table);

        const detailPane = document.createElement("div");
        detailPane.className = "wgs-subscription-detail-pane";
        detailPane.innerHTML = `
            <div class="wgs-detail-empty">
                <strong>${this._escapeHtml(_t("Selecciona un cliente"))}</strong>
                <p>${this._escapeHtml(_t("Aqui veras sus suscripciones nativas, participantes y acciones disponibles."))}</p>
            </div>
        `;

        layout.appendChild(listPane);
        layout.appendChild(detailPane);
        body.appendChild(layout);

        let activeCameraStream = null;
        const stopPartnerCamera = () => {
            if (activeCameraStream) {
                for (const track of activeCameraStream.getTracks()) {
                    track.stop();
                }
                activeCameraStream = null;
            }
        };
        const canUsePartnerCamera = () => Boolean(
            navigator.mediaDevices && navigator.mediaDevices.getUserMedia
        );
        const applyImageDataUrlToForm = (targetForm, dataUrl) => {
            if (!targetForm || !dataUrl) {
                return;
            }
            targetForm.imageDataUrl = dataUrl;
            targetForm.imageBase64 = this._stripDataUrlPrefix(dataUrl);
        };
        const startPartnerCameraForForm = async (targetForm, renderFn, logLabel) => {
            if (!targetForm || !canUsePartnerCamera()) {
                formError = _t("La cámara no está disponible en este equipo o navegador.");
                renderFn();
                return false;
            }
            try {
                stopPartnerCamera();
                activeCameraStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "user" }, audio: false });
                targetForm.cameraActive = true;
                formError = "";
                renderFn();
                return true;
            } catch (error) {
                console.error(logLabel, error);
                formError = _t("No se pudo acceder a la cámara del equipo.");
                renderFn();
                return false;
            }
        };
        const stopPartnerCameraForForm = (targetForm, renderFn) => {
            stopPartnerCamera();
            if (targetForm) {
                targetForm.cameraActive = false;
            }
            renderFn();
        };
        const capturePartnerCameraForForm = (targetForm, previewRoot, renderFn) => {
            if (!targetForm || !activeCameraStream) {
                return false;
            }
            const video = previewRoot.querySelector('[data-role="partner-camera-preview"]');
            if (!video) {
                formError = _t("No se pudo leer la vista previa de la cámara.");
                renderFn();
                return false;
            }
            const canvas = document.createElement("canvas");
            canvas.width = video.videoWidth || 480;
            canvas.height = video.videoHeight || 640;
            const context = canvas.getContext("2d");
            context.drawImage(video, 0, 0, canvas.width, canvas.height);
            applyImageDataUrlToForm(targetForm, canvas.toDataURL("image/jpeg", 0.9));
            targetForm.cameraActive = false;
            stopPartnerCamera();
            renderFn();
            return true;
        };

        const footer = document.createElement("div");
        footer.className = "wgs-status-modal-footer";
        const closeButton = document.createElement("button");
        closeButton.type = "button";
        closeButton.className = "wgs-status-close-btn";
        closeButton.textContent = _t("Cerrar");
        const closeModal = () => {
            stopPartnerCamera();
            overlay.remove();
        };
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
        for (const eventName of ["keydown", "keypress", "keyup"]) {
            modal.addEventListener(eventName, (event) => {
                if (!isInteractiveModalField(event.target)) {
                    return;
                }
                event.stopPropagation();
            }, true);
        }

        document.body.appendChild(overlay);

        const {
            searchInput,
            stateSelect,
            birthdaySelect,
            sortSelect,
            exportButton,
            tbody,
        } = getDirectoryControls({ toolbar, table });

        let filteredSnapshot = [...rows];
        let selectedPartnerId = rows[0] ? rows[0].id : false;
        let detailRequestToken = 0;
        let currentDetail = null;
        let directoryLoading = false;
        let directoryFullyLoaded = false;
        let directoryLoadError = "";
        let formMode = null;
        let formError = "";
        let formNotice = "";
        let catalogLoading = false;
        let productCatalog = [];
        let renewalForm = null;
        let upsaleForm = null;
        let pendingChargeForm = null;
        let cancellationRefundForm = null;
        let participantEditForm = null;
        let newPartnerForm = null;
        let partnerPhotoForm = null;
        const detailCache = new Map();
        let newSubscriptionForm = this._getDefaultNewSubscriptionForm(selectedPartnerId);
        const modalState = {
            get selectedPartnerId() { return selectedPartnerId; },
            set selectedPartnerId(value) { selectedPartnerId = value; },
            get currentDetail() { return currentDetail; },
            set currentDetail(value) { currentDetail = value; },
            get formMode() { return formMode; },
            set formMode(value) { formMode = value; },
            get formError() { return formError; },
            set formError(value) { formError = value; },
            get formNotice() { return formNotice; },
            set formNotice(value) { formNotice = value; },
            get renewalForm() { return renewalForm; },
            set renewalForm(value) { renewalForm = value; },
            get upsaleForm() { return upsaleForm; },
            set upsaleForm(value) { upsaleForm = value; },
            get pendingChargeForm() { return pendingChargeForm; },
            set pendingChargeForm(value) { pendingChargeForm = value; },
            get cancellationRefundForm() { return cancellationRefundForm; },
            set cancellationRefundForm(value) { cancellationRefundForm = value; },
            get participantEditForm() { return participantEditForm; },
            set participantEditForm(value) { participantEditForm = value; },
            get newPartnerForm() { return newPartnerForm; },
            set newPartnerForm(value) { newPartnerForm = value; },
            get partnerPhotoForm() { return partnerPhotoForm; },
            set partnerPhotoForm(value) { partnerPhotoForm = value; },
            get newSubscriptionForm() { return newSubscriptionForm; },
            set newSubscriptionForm(value) { newSubscriptionForm = value; },
            getDefaultNewPartnerForm: () => this._getDefaultNewPartnerForm(),
        };

        const syncPartnerCameraPreview = () => {
            if (!activeCameraStream) {
                return;
            }
            const videos = overlay.querySelectorAll('[data-role="partner-camera-preview"]');
            for (const video of videos) {
                if (video && video.srcObject !== activeCameraStream) {
                    video.srcObject = activeCameraStream;
                    video.play().catch(() => {});
                }
            }
        };

        const clearFeedback = () => {
            clearModalFeedback(modalState);
        };

        const resetListPartnerForm = () => {
            resetListPartnerFormState(modalState, { stopPartnerCamera });
        };

        const resetInlineForms = () => {
            resetDetailInlineForms(modalState, {
                stopPartnerCamera,
                selectedPartnerId,
                createNewSubscriptionForm: (partnerId) => this._getDefaultNewSubscriptionForm(partnerId),
            });
        };

        const resetForPartnerSelection = () => {
            resetForSelectedPartner(modalState, {
                stopPartnerCamera,
                selectedPartnerId,
                createNewSubscriptionForm: (partnerId) => this._getDefaultNewSubscriptionForm(partnerId),
            });
        };

        const clearDirectorySelection = () => {
            clearDirectorySelectionState(modalState, {
                stopPartnerCamera,
            });
        };

        const loadDirectoryRowsInBackground = async ({ reset = false, preferredPartnerId = false } = {}) => {
            if (directoryLoading) {
                return;
            }
            if (reset) {
                rows = [];
                filteredSnapshot = [];
                detailCache.clear();
                currentDetail = null;
                selectedPartnerId = Number(preferredPartnerId || 0) || false;
                directoryFullyLoaded = false;
                directoryLoadError = "";
            }
            directoryLoading = true;
            render();
            const batchSize = 250;
            let offset = rows.length;
            try {
                while (overlay.isConnected) {
                    const batch = await this.subscriptionPosApi.fetchPartnerDirectoryBatch(offset, batchSize);
                    if (!Array.isArray(batch) || !batch.length) {
                        directoryFullyLoaded = true;
                        break;
                    }
                    rows.push(...batch);
                    filteredSnapshot = [...rows];
                    if (!selectedPartnerId && rows[0]) {
                        selectedPartnerId = Number(preferredPartnerId || rows[0].id || 0) || false;
                    }
                    offset += batch.length;
                    render();
                    if (batch.length < batchSize) {
                        directoryFullyLoaded = true;
                        break;
                    }
                }
            } catch (error) {
                console.error("Error al consultar suscripciones en POS", error);
                directoryLoadError = _t("No se pudo cargar el directorio completo en este momento.");
            } finally {
                directoryLoading = false;
                render();
            }
        };

        const reloadDirectoryRows = async (preferredPartnerId = false) => {
            await loadDirectoryRowsInBackground({ reset: true, preferredPartnerId });
        };

        const renderDetailEmpty = (title, message) => {
            detailPane.innerHTML = buildDetailEmptyHtml({
                title,
                message,
                escapeHtml: (value) => this._escapeHtml(value),
            });
        };

        const renderDetailLoading = () => {
            detailPane.innerHTML = buildDetailLoadingHtml({
                title: _t("Cargando detalle"),
                message: _t("Estamos consultando las suscripciones del cliente seleccionado."),
                escapeHtml: (value) => this._escapeHtml(value),
            });
        };

        const getSelectedPlan = () => {
            const planKey = String(newSubscriptionForm.planChoice || "");
            return (newSubscriptionForm.plans || []).find((item) => {
                return `${Number(item.plan_id || 0)}:${Number(item.pricing_id || 0)}` === planKey;
            }) || null;
        };

        const getSelectedUpsalePlan = () => {
            const planKey = String(upsaleForm && upsaleForm.planChoice ? upsaleForm.planChoice : "");
            return (upsaleForm && Array.isArray(upsaleForm.plans) ? upsaleForm.plans : []).find((item) => {
                return `${Number(item.plan_id || 0)}:${Number(item.pricing_id || 0)}` === planKey;
            }) || null;
        };

        const clampParticipantIds = (participantIds, ownerId, maxTotal) => {
            const numericOwnerId = Number(ownerId || 0) || false;
            const limit = Math.max(1, Number(maxTotal || 1));
            const cleaned = [...new Set((participantIds || []).map((value) => Number(value || 0)).filter((value) => value > 0))];
            const withoutOwner = cleaned.filter((value) => value !== numericOwnerId);
            const result = [];
            if (numericOwnerId) {
                result.push(numericOwnerId);
            }
            for (const partnerId of withoutOwner) {
                if (result.length >= limit) {
                    break;
                }
                result.push(partnerId);
            }
            return result;
        };

        const openNewSubscriptionForm = async () => {
            if (!selectedPartnerId) {
                return;
            }
            formMode = "new";
            formError = "";
            formNotice = "";
            stopPartnerCamera();
            renewalForm = null;
            upsaleForm = null;
            pendingChargeForm = null;
            cancellationRefundForm = null;
            participantEditForm = null;
            newPartnerForm = null;
            partnerPhotoForm = null;
            newSubscriptionForm = this._getDefaultNewSubscriptionForm(selectedPartnerId);
            renderDetail(currentDetail);
            if (productCatalog.length || catalogLoading) {
                return;
            }
            catalogLoading = true;
            renderDetail(currentDetail);
            try {
                productCatalog = await this._fetchSubscriptionProductCatalog("");
                if (!Array.isArray(productCatalog)) {
                    productCatalog = [];
                }
                if (!productCatalog.length) {
                    formError = _t("No hay productos de suscripción cargados en esta sesión del POS.");
                }
            } catch (error) {
                console.error("Error al consultar catalogo de suscripciones en POS", error);
                formError = _t("No se pudo cargar el catalogo de productos de suscripcion.");
            } finally {
                catalogLoading = false;
                renderDetail(currentDetail);
            }
        };

        const openNewPartnerForm = () => {
            openNewPartnerFormState(modalState, {
                stopPartnerCamera,
                createNewSubscriptionForm: (partnerId) => this._getDefaultNewSubscriptionForm(partnerId),
                renderDetail,
            });
        };

        const openPartnerPhotoForm = () => {
            openPartnerPhotoFormState(modalState, {
                stopPartnerCamera,
                renderDetail,
            });
        };

        const openRenewalForm = async (item) => {
            if (!item || !item.subscription_id) {
                return;
            }
            formMode = "renewal";
            formError = "";
            formNotice = "";
            stopPartnerCamera();
            newPartnerForm = null;
            pendingChargeForm = null;
            cancellationRefundForm = null;
            participantEditForm = null;
            renewalForm = {
                subscriptionId: Number(item.subscription_id || 0) || false,
                subscriptionName: item.subscription_name || "",
                holderPartnerId: Number(item.holder_partner_id || 0) || false,
                holderPartnerName: item.holder_partner_name || "",
                productId: Number(item.renewal_product_id || 0) || false,
                productName: item.renewal_product_name || "",
                planId: Number(item.renewal_plan_id || 0) || false,
                pricingId: Number(item.renewal_pricing_id || 0) || false,
                charge: buildChargeBreakdown(this, null, { baseAmount: 0, displayAmount: 0 }),
                nextInvoiceDate: item.next_invoice_date || false,
                loading: true,
            };
            renderDetail(currentDetail);
            try {
                const charge = await this._fetchSubscriptionRenewalCharge(
                    renewalForm.subscriptionId,
                    renewalForm.productId,
                    renewalForm.planId,
                    renewalForm.pricingId
                );
                renewalForm = {
                    ...renewalForm,
                    loading: false,
                    charge: buildChargeBreakdown(this, null, {
                        baseAmount: Number(charge && charge.charge_now ? charge.charge_now : 0),
                        ticketUnitPrice: Number(
                            charge && charge.ticket_charge_now !== undefined
                                ? charge.ticket_charge_now
                                : (charge && charge.charge_now ? charge.charge_now : 0)
                        ),
                        displayAmount: Number(
                            charge && charge.display_charge_now !== undefined
                                ? charge.display_charge_now
                                : (charge && charge.charge_now ? charge.charge_now : 0)
                        ),
                    }),
                    planId: Number(charge && charge.plan_id ? charge.plan_id : renewalForm.planId) || false,
                    pricingId: Number(charge && charge.pricing_id ? charge.pricing_id : renewalForm.pricingId) || false,
                };
            } catch (error) {
                console.error("Error al consultar cobro de renovación POS", error);
                formError = _t("No se pudo consultar el cobro de renovación para esta suscripción.");
                renewalForm = {
                    ...renewalForm,
                    loading: false,
                };
            }
            renderDetail(currentDetail);
        };

        const openPendingChargeForm = async (item) => {
            if (!item || !item.subscription_id) {
                return;
            }
            const pendingDocuments = Array.isArray(item.pending_documents) ? item.pending_documents : [];
            if (!pendingDocuments.length) {
                formError = _t("Esta suscripción no tiene documentos pendientes por cobrar.");
                renderDetail(currentDetail);
                return;
            }
            const firstPending = pendingDocuments[0];
            formMode = "pending";
            formError = "";
            formNotice = "";
            stopPartnerCamera();
            newPartnerForm = null;
            renewalForm = null;
            upsaleForm = null;
            pendingChargeForm = {
                subscriptionId: Number(item.subscription_id || 0) || false,
                subscriptionName: item.subscription_name || "",
                holderPartnerId: Number(item.holder_partner_id || 0) || false,
                holderPartnerName: item.holder_partner_name || "",
                productId: Number(item.renewal_product_id || 0) || false,
                productName: item.renewal_product_name || "",
                pendingMoveId: Number(firstPending.document_id || 0) || false,
                pendingMoveName: firstPending.name || "",
                invoiceDate: firstPending.invoice_date || false,
                invoiceDateDue: firstPending.invoice_date_due || false,
                charge: buildChargeBreakdown(this, null, { baseAmount: 0, displayAmount: 0 }),
                totalCharge: buildChargeBreakdown(this, null, {
                    baseAmount: Number(firstPending.amount_total || 0),
                    displayAmount: Number(firstPending.amount_total || 0),
                }),
                loading: true,
            };
            renderDetail(currentDetail);
            try {
                const charge = await this._fetchSubscriptionPendingCharge(
                    pendingChargeForm.subscriptionId,
                    pendingChargeForm.pendingMoveId
                );
                pendingChargeForm = {
                    ...pendingChargeForm,
                    loading: false,
                    pendingMoveId: Number(charge && charge.pending_move_id ? charge.pending_move_id : pendingChargeForm.pendingMoveId) || false,
                    pendingMoveName: charge && charge.pending_move_name ? charge.pending_move_name : pendingChargeForm.pendingMoveName,
                    invoiceDate: charge && charge.invoice_date ? charge.invoice_date : pendingChargeForm.invoiceDate,
                    invoiceDateDue: charge && charge.invoice_date_due ? charge.invoice_date_due : pendingChargeForm.invoiceDateDue,
                    charge: buildChargeBreakdown(this, null, {
                        baseAmount: Number(charge && charge.charge_now ? charge.charge_now : 0),
                        ticketUnitPrice: Number(
                            charge && charge.ticket_charge_now !== undefined
                                ? charge.ticket_charge_now
                                : (charge && charge.charge_now ? charge.charge_now : 0)
                        ),
                        displayAmount: Number(
                            charge && charge.display_charge_now !== undefined
                                ? charge.display_charge_now
                                : (charge && charge.charge_now ? charge.charge_now : 0)
                        ),
                    }),
                    totalCharge: buildChargeBreakdown(this, null, {
                        baseAmount: Number(charge && charge.amount_total ? charge.amount_total : getChargeDisplayAmount(pendingChargeForm.totalCharge) || 0),
                        ticketUnitPrice: Number(
                            charge && charge.ticket_amount_total !== undefined
                                ? charge.ticket_amount_total
                                : (charge && charge.amount_total ? charge.amount_total : getChargeDisplayAmount(pendingChargeForm.totalCharge) || 0)
                        ),
                        displayAmount: Number(
                            charge && charge.display_amount_total !== undefined
                                ? charge.display_amount_total
                                : (charge && charge.amount_total ? charge.amount_total : getChargeDisplayAmount(pendingChargeForm.totalCharge) || 0)
                        ),
                    }),
                };
            } catch (error) {
                console.error("Error al consultar cobro pendiente POS", error);
                formError = _t("No se pudo consultar el documento pendiente para esta suscripción.");
                pendingChargeForm = {
                    ...pendingChargeForm,
                    loading: false,
                };
            }
            renderDetail(currentDetail);
        };

        const openCancellationRefundForm = async (item) => {
            if (!item || !item.subscription_id) {
                return;
            }
            formMode = "cancellation_refund";
            formError = "";
            formNotice = "";
            stopPartnerCamera();
            newPartnerForm = null;
            renewalForm = null;
            upsaleForm = null;
            pendingChargeForm = null;
            cancellationRefundForm = null;
            participantEditForm = null;
            cancellationRefundForm = {
                subscriptionId: Number(item.subscription_id || 0) || false,
                subscriptionName: item.subscription_name || "",
                holderPartnerId: Number(item.holder_partner_id || 0) || false,
                holderPartnerName: item.holder_partner_name || "",
                originPosLineId: false,
                originPosOrderName: "",
                originDate: false,
                productId: false,
                productName: "",
                qty: 1,
                priceUnit: 0,
                discount: 0,
                amountTotal: 0,
                loading: true,
            };
            renderDetail(currentDetail);
            try {
                const refund = await this._fetchSubscriptionCancellationRefund(cancellationRefundForm.subscriptionId);
                cancellationRefundForm = {
                    ...cancellationRefundForm,
                    loading: false,
                    originPosLineId: Number(refund && refund.origin_pos_line_id ? refund.origin_pos_line_id : 0) || false,
                    originPosOrderName: refund && refund.origin_pos_order_name ? refund.origin_pos_order_name : "",
                    originDate: refund && refund.origin_date ? refund.origin_date : false,
                    productId: Number(refund && refund.product_id ? refund.product_id : 0) || false,
                    productName: refund && refund.product_name ? refund.product_name : "",
                    qty: Number(refund && refund.qty ? refund.qty : 1) || 1,
                    priceUnit: Number(refund && refund.price_unit ? refund.price_unit : 0) || 0,
                    discount: Number(refund && refund.discount ? refund.discount : 0) || 0,
                    amountTotal: Number(refund && refund.amount_total ? refund.amount_total : 0) || 0,
                };
            } catch (error) {
                console.error("Error al consultar devolución por cancelación POS", error);
                formError = _t("No se pudo consultar la devolución exacta de esta suscripción.");
                cancellationRefundForm = {
                    ...cancellationRefundForm,
                    loading: false,
                };
            }
            renderDetail(currentDetail);
        };

        const recalculateNewSubscriptionCharge = async (product, preferredPlan = null) => {
            if (!newSubscriptionForm || !product || !selectedPartnerId) {
                return;
            }
            newSubscriptionForm.loading = true;
            renderDetail(currentDetail);
            try {
                const charge = await this._fetchSubscriptionCharge(
                    selectedPartnerId,
                    Number(product.id || 0),
                    Number(preferredPlan && preferredPlan.price ? preferredPlan.price : product.default_price || 0),
                    preferredPlan ? Number(preferredPlan.plan_id || 0) || false : false,
                    preferredPlan ? Number(preferredPlan.pricing_id || 0) || false : false
                );
                const displayRecurringPrice = Number(
                    charge && charge.display_recurring_price !== undefined
                        ? charge.display_recurring_price
                        : (charge && charge.recurring_price ? charge.recurring_price : 0)
                );
                newSubscriptionForm.charge = buildChargeBreakdown(this, null, {
                    baseAmount: Number(charge && charge.recurring_price ? charge.recurring_price : 0),
                    ticketUnitPrice: Number(
                        charge && charge.ticket_recurring_price !== undefined
                            ? charge.ticket_recurring_price
                            : (charge && charge.recurring_price ? charge.recurring_price : 0)
                    ),
                    displayAmount: displayRecurringPrice,
                });
                if (charge && (charge.plan_id || charge.pricing_id)) {
                    newSubscriptionForm.planChoice = `${Number(charge.plan_id || 0)}:${Number(charge.pricing_id || 0)}`;
                }
            } catch (error) {
                console.error("Error al recalcular cobro de suscripción POS", error);
                formError = _t("No se pudo recalcular el precio de la suscripción.");
            } finally {
                newSubscriptionForm.loading = false;
                renderDetail(currentDetail);
            }
        };

        const applySelectedUpsaleProduct = async (productId) => {
            if (!upsaleForm) {
                return;
            }
            const numericProductId = Number(productId || 0);
            const product = productCatalog.find((item) => Number(item.id) === numericProductId) || null;
            upsaleForm.productId = numericProductId;
            upsaleForm.productName = product ? product.name || "" : "";
            upsaleForm.maxParticipantsTotal = product ? Number(product.max_participants_total || 1) : 1;
            upsaleForm.plans = product ? [...(product.plans || [])] : [];
            upsaleForm.planChoice = "";
            upsaleForm.recurringCharge = buildChargeBreakdown(this, null, { baseAmount: 0, displayAmount: 0 });
            upsaleForm.creditCharge = buildChargeBreakdown(this, null, { baseAmount: 0, displayAmount: 0 });
            upsaleForm.charge = buildChargeBreakdown(this, null, { baseAmount: 0, displayAmount: 0 });
            upsaleForm.participantIds = clampParticipantIds(
                upsaleForm.participantIds,
                upsaleForm.holderPartnerId,
                upsaleForm.maxParticipantsTotal
            );

            if (!product || !upsaleForm.plans.length) {
                renderDetail(currentDetail);
                return;
            }

            const defaultPlanId = Number(product.default_plan_id || 0);
            const defaultPricingId = Number(product.default_pricing_id || 0);
            const defaultChoice = upsaleForm.plans.find((item) => {
                return Number(item.plan_id || 0) === defaultPlanId && Number(item.pricing_id || 0) === defaultPricingId;
            }) || upsaleForm.plans[0] || null;
            if (defaultChoice) {
                upsaleForm.planChoice = `${Number(defaultChoice.plan_id || 0)}:${Number(defaultChoice.pricing_id || 0)}`;
            }
            upsaleForm.loading = true;
            renderDetail(currentDetail);
            try {
                const selectedPlan = getSelectedUpsalePlan();
                const charge = await this._fetchSubscriptionUpsaleCharge(
                    upsaleForm.subscriptionId,
                    upsaleForm.productId,
                    Number(defaultChoice && defaultChoice.price ? defaultChoice.price : 0),
                    selectedPlan ? Number(selectedPlan.plan_id || 0) || false : false,
                    selectedPlan ? Number(selectedPlan.pricing_id || 0) || false : false
                );
                upsaleForm = {
                    ...upsaleForm,
                    loading: false,
                    recurringCharge: buildChargeBreakdown(this, null, {
                        baseAmount: Number(charge && charge.recurring_price ? charge.recurring_price : 0),
                        ticketUnitPrice: Number(
                            charge && charge.ticket_recurring_price !== undefined
                                ? charge.ticket_recurring_price
                                : (charge && charge.recurring_price ? charge.recurring_price : 0)
                        ),
                        displayAmount: Number(
                            charge && charge.display_recurring_price !== undefined
                                ? charge.display_recurring_price
                                : (charge && charge.recurring_price ? charge.recurring_price : 0)
                        ),
                    }),
                    creditCharge: buildChargeBreakdown(this, null, {
                        baseAmount: Number(charge && charge.credit_amount ? charge.credit_amount : 0),
                        ticketUnitPrice: Number(
                            charge && charge.ticket_credit_amount !== undefined
                                ? charge.ticket_credit_amount
                                : (charge && charge.credit_amount ? charge.credit_amount : 0)
                        ),
                        displayAmount: Number(
                            charge && charge.display_credit_amount !== undefined
                                ? charge.display_credit_amount
                                : (charge && charge.credit_amount ? charge.credit_amount : 0)
                        ),
                    }),
                    charge: buildChargeBreakdown(this, null, {
                        baseAmount: Number(charge && charge.charge_now ? charge.charge_now : 0),
                        ticketUnitPrice: Number(
                            charge && charge.ticket_charge_now !== undefined
                                ? charge.ticket_charge_now
                                : (charge && charge.charge_now ? charge.charge_now : 0)
                        ),
                        displayAmount: Number(
                            charge && charge.display_charge_now !== undefined
                                ? charge.display_charge_now
                                : (charge && charge.charge_now ? charge.charge_now : 0)
                        ),
                    }),
                    planChoice: `${Number(charge && charge.plan_id ? charge.plan_id : (selectedPlan && selectedPlan.plan_id) || 0)}:${Number(charge && charge.pricing_id ? charge.pricing_id : (selectedPlan && selectedPlan.pricing_id) || 0)}`,
                };
            } catch (error) {
                console.error("Error al consultar cobro de upsale POS", error);
                formError = _t("No se pudo calcular el cobro del upsale para esta suscripción.");
                upsaleForm = {
                    ...upsaleForm,
                    loading: false,
                    recurringCharge: buildChargeBreakdown(this, null, { baseAmount: 0, displayAmount: 0 }),
                    creditCharge: buildChargeBreakdown(this, null, { baseAmount: 0, displayAmount: 0 }),
                    charge: buildChargeBreakdown(this, null, { baseAmount: 0, displayAmount: 0 }),
                };
            }
            renderDetail(currentDetail);
        };

        const updateSelectedUpsalePlan = async (planChoice) => {
            if (!upsaleForm) {
                return;
            }
            upsaleForm.planChoice = String(planChoice || "");
            const selectedPlan = getSelectedUpsalePlan();
            if (!selectedPlan || !upsaleForm.productId || !upsaleForm.subscriptionId) {
                renderDetail(currentDetail);
                return;
            }
            upsaleForm.loading = true;
            renderDetail(currentDetail);
            try {
                const charge = await this._fetchSubscriptionUpsaleCharge(
                    upsaleForm.subscriptionId,
                    upsaleForm.productId,
                    Number(selectedPlan.price || 0),
                    Number(selectedPlan.plan_id || 0) || false,
                    Number(selectedPlan.pricing_id || 0) || false
                );
                upsaleForm = {
                    ...upsaleForm,
                    loading: false,
                    recurringCharge: buildChargeBreakdown(this, null, {
                        baseAmount: Number(charge && charge.recurring_price ? charge.recurring_price : 0),
                        ticketUnitPrice: Number(
                            charge && charge.ticket_recurring_price !== undefined
                                ? charge.ticket_recurring_price
                                : (charge && charge.recurring_price ? charge.recurring_price : 0)
                        ),
                        displayAmount: Number(
                            charge && charge.display_recurring_price !== undefined
                                ? charge.display_recurring_price
                                : (charge && charge.recurring_price ? charge.recurring_price : 0)
                        ),
                    }),
                    creditCharge: buildChargeBreakdown(this, null, {
                        baseAmount: Number(charge && charge.credit_amount ? charge.credit_amount : 0),
                        ticketUnitPrice: Number(
                            charge && charge.ticket_credit_amount !== undefined
                                ? charge.ticket_credit_amount
                                : (charge && charge.credit_amount ? charge.credit_amount : 0)
                        ),
                        displayAmount: Number(
                            charge && charge.display_credit_amount !== undefined
                                ? charge.display_credit_amount
                                : (charge && charge.credit_amount ? charge.credit_amount : 0)
                        ),
                    }),
                    charge: buildChargeBreakdown(this, null, {
                        baseAmount: Number(charge && charge.charge_now ? charge.charge_now : 0),
                        ticketUnitPrice: Number(
                            charge && charge.ticket_charge_now !== undefined
                                ? charge.ticket_charge_now
                                : (charge && charge.charge_now ? charge.charge_now : 0)
                        ),
                        displayAmount: Number(
                            charge && charge.display_charge_now !== undefined
                                ? charge.display_charge_now
                                : (charge && charge.charge_now ? charge.charge_now : 0)
                        ),
                    }),
                    planChoice: `${Number(charge && charge.plan_id ? charge.plan_id : selectedPlan.plan_id || 0)}:${Number(charge && charge.pricing_id ? charge.pricing_id : selectedPlan.pricing_id || 0)}`,
                };
            } catch (error) {
                console.error("Error al actualizar cobro de upsale POS", error);
                formError = _t("No se pudo recalcular el cobro del upsale.");
                upsaleForm = {
                    ...upsaleForm,
                    loading: false,
                };
            }
            renderDetail(currentDetail);
        };

        const toggleUpsaleParticipant = (partnerId, checked) => {
            if (!upsaleForm) {
                return;
            }
            const numericPartnerId = Number(partnerId || 0);
            const holderPartnerId = Number(upsaleForm.holderPartnerId || 0);
            let values = [...(upsaleForm.participantIds || [])].map((item) => Number(item));
            values = values.filter((item) => item > 0 && item !== holderPartnerId && item !== numericPartnerId);
            if (checked && numericPartnerId > 0 && numericPartnerId !== holderPartnerId) {
                values.push(numericPartnerId);
            }
            upsaleForm.participantIds = clampParticipantIds(
                holderPartnerId ? [holderPartnerId, ...new Set(values)] : [...new Set(values)],
                holderPartnerId,
                upsaleForm.maxParticipantsTotal
            );
        };

        const openUpsaleForm = async (item) => {
            if (!item || !item.subscription_id) {
                return;
            }
            formMode = "upsale";
            formError = "";
            formNotice = "";
            stopPartnerCamera();
            newPartnerForm = null;
            renewalForm = null;
            upsaleForm = this._getDefaultUpsaleForm(item);
            pendingChargeForm = null;
            cancellationRefundForm = null;
            participantEditForm = null;
            renderDetail(currentDetail);
            if (!productCatalog.length && !catalogLoading) {
                catalogLoading = true;
                renderDetail(currentDetail);
                try {
                    productCatalog = await this._fetchSubscriptionProductCatalog("");
                    if (!Array.isArray(productCatalog)) {
                        productCatalog = [];
                    }
                    if (!productCatalog.length) {
                        formError = _t("No hay productos de suscripción cargados en esta sesión del POS.");
                    }
                } catch (error) {
                    console.error("Error al consultar catalogo de upsale en POS", error);
                    formError = _t("No se pudo cargar el catalogo de productos para upsale.");
                } finally {
                    catalogLoading = false;
                }
            }
            renderDetail(currentDetail);
        };

        const toggleEditedParticipant = (partnerId, checked) => {
            if (!participantEditForm) {
                return;
            }
            const numericPartnerId = Number(partnerId || 0);
            const holderPartnerId = Number(participantEditForm.holderPartnerId || 0);
            let values = [...(participantEditForm.participantIds || [])].map((item) => Number(item));
            values = values.filter((item) => item > 0 && item !== holderPartnerId && item !== numericPartnerId);
            if (checked && numericPartnerId > 0 && numericPartnerId !== holderPartnerId) {
                values.push(numericPartnerId);
            }
            participantEditForm.participantIds = clampParticipantIds(
                holderPartnerId ? [holderPartnerId, ...new Set(values)] : [...new Set(values)],
                holderPartnerId,
                participantEditForm.maxParticipantsTotal
            );
        };

        const openParticipantEditForm = async (item) => {
            if (!item || !item.subscription_id) {
                return;
            }
            formMode = "participants";
            formError = "";
            formNotice = "";
            stopPartnerCamera();
            newPartnerForm = null;
            renewalForm = null;
            upsaleForm = null;
            pendingChargeForm = null;
            participantEditForm = this._getDefaultParticipantEditForm(item);
            renderDetail(currentDetail);
        };

        const applySelectedProduct = async (productId) => {
            const numericProductId = Number(productId || 0);
            const product = productCatalog.find((item) => Number(item.id) === numericProductId) || null;
            newSubscriptionForm.productId = numericProductId;
            newSubscriptionForm.productName = product ? product.name || "" : "";
            newSubscriptionForm.maxParticipantsTotal = product ? Number(product.max_participants_total || 1) : 1;
            newSubscriptionForm.plans = product ? [...(product.plans || [])] : [];
            const defaultPlanId = product ? Number(product.default_plan_id || 0) : 0;
            const defaultPricingId = product ? Number(product.default_pricing_id || 0) : 0;
            const defaultChoice = newSubscriptionForm.plans.find((item) => {
                return Number(item.plan_id || 0) === defaultPlanId && Number(item.pricing_id || 0) === defaultPricingId;
            }) || newSubscriptionForm.plans[0] || null;
            if (defaultChoice) {
                newSubscriptionForm.planChoice = `${Number(defaultChoice.plan_id || 0)}:${Number(defaultChoice.pricing_id || 0)}`;
            } else {
                newSubscriptionForm.planChoice = "";
                newSubscriptionForm.charge = buildChargeBreakdown(this, null, {
                    baseAmount: Number(product ? (product.default_price || 0) : 0),
                    displayAmount: Number(
                        product ? (product.default_display_price !== undefined ? product.default_display_price : (product.default_price || 0)) : 0
                    ),
                });
            }
            newSubscriptionForm.participantIds = clampParticipantIds(
                newSubscriptionForm.participantIds,
                selectedPartnerId,
                newSubscriptionForm.maxParticipantsTotal
            );
            if (product) {
                await recalculateNewSubscriptionCharge(product, defaultChoice);
                return;
            }
            renderDetail(currentDetail);
        };

        const updateSelectedPlan = async (planChoice) => {
            newSubscriptionForm.planChoice = String(planChoice || "");
            const plan = getSelectedPlan();
            const product = productCatalog.find((item) => Number(item.id) === Number(newSubscriptionForm.productId || 0)) || null;
            if (plan) {
                newSubscriptionForm.charge = buildChargeBreakdown(this, null, {
                    baseAmount: Number(plan.price || 0),
                    displayAmount: Number(
                        plan.display_price !== undefined ? plan.display_price : (plan.price || 0)
                    ),
                });
            }
            if (product && plan) {
                await recalculateNewSubscriptionCharge(product, plan);
                return;
            }
            renderDetail(currentDetail);
        };

        const toggleParticipant = (partnerId, checked) => {
            const numericPartnerId = Number(partnerId || 0);
            let values = [...(newSubscriptionForm.participantIds || [])].map((item) => Number(item));
            values = values.filter((item) => item > 0 && item !== selectedPartnerId && item !== numericPartnerId);
            if (checked && numericPartnerId > 0 && numericPartnerId !== selectedPartnerId) {
                values.push(numericPartnerId);
            }
            newSubscriptionForm.participantIds = clampParticipantIds(
                [selectedPartnerId, ...new Set(values)],
                selectedPartnerId,
                newSubscriptionForm.maxParticipantsTotal
            );
        };

        const filterParticipantRows = (searchTerm = "") => {
            const query = String(searchTerm || "").trim().toLowerCase();
            const sourceRows = rows
                .slice()
                .sort((a, b) => (a.name || "").localeCompare(b.name || "", "es"));
            if (!query) {
                return sourceRows;
            }
            return sourceRows.filter((row) => {
                const haystack = `${row.name || ""} ${row.phone || ""} ${row.email || ""}`.toLowerCase();
                return haystack.includes(query);
            });
        };

        const renderNewSubscriptionForm = () => {
            if (formMode !== "new") {
                return "";
            }
            const plan = getSelectedPlan();
            const automaticEndDate = plan
                ? getPlanPeriodEndDate(newSubscriptionForm.startDate, plan.interval_value, plan.interval_unit)
                : "";
            const filteredParticipants = filterParticipantRows(newSubscriptionForm.participantSearch);
            const participantOptions = Number(newSubscriptionForm.maxParticipantsTotal || 1) > 1
                ? filteredParticipants
                    .map((row) => {
                        const rowId = Number(row.id || 0);
                        const selected = (newSubscriptionForm.participantIds || []).includes(rowId);
                        const isOwner = rowId === selectedPartnerId;
                        return `
                            <label class="wgs-checkbox-option ${isOwner ? "wgs-checkbox-owner" : ""}">
                                <input type="checkbox" data-field="participant_toggle" value="${this._escapeHtml(String(rowId))}" ${selected ? "checked" : ""} ${isOwner ? "disabled" : ""} />
                                <span>${this._escapeHtml(row.name || "-")}${isOwner ? ` ${this._escapeHtml(_t("(Titular)"))}` : ""}</span>
                            </label>
                        `;
                    }).join("")
                : "";
            const productOptions = productCatalog.map((product) => {
                const selected = Number(product.id) === Number(newSubscriptionForm.productId) ? "selected" : "";
                return `<option value="${this._escapeHtml(String(product.id))}" ${selected}>${this._escapeHtml(product.name || "-")}</option>`;
            }).join("");
            const planOptions = (newSubscriptionForm.plans || []).map((item) => {
                const value = `${Number(item.plan_id || 0)}:${Number(item.pricing_id || 0)}`;
                const selected = value === String(newSubscriptionForm.planChoice || "") ? "selected" : "";
                const label = `${item.plan_name || _t("Plan recurrente")} | ${this._formatMoney(item.display_price !== undefined ? item.display_price : (item.price || 0))}${item.interval_label ? ` | ${item.interval_label}` : ""}`;
                return `<option value="${this._escapeHtml(value)}" ${selected}>${this._escapeHtml(label)}</option>`;
            }).join("");

            return `
                <div class="wgs-inline-form-card">
                    <div class="wgs-inline-form-header">
                        <strong>${this._escapeHtml(_t("Nueva suscripcion"))}</strong>
                        <button type="button" class="wgs-inline-close-btn" data-action="cancel-new">${this._escapeHtml(_t("Cancelar"))}</button>
                    </div>
                    ${formError ? `<div class="wgs-inline-error">${this._escapeHtml(formError)}</div>` : ""}
                    ${formNotice ? `<div class="wgs-inline-notice">${this._escapeHtml(formNotice)}</div>` : ""}
                    ${catalogLoading ? `<div class="wgs-inline-loading">${this._escapeHtml(_t("Cargando productos de suscripcion..."))}</div>` : ""}
                    ${newSubscriptionForm.loading ? `<div class="wgs-inline-loading">${this._escapeHtml(_t("Recalculando precio con IVA..."))}</div>` : ""}
                    <div class="wgs-inline-form-grid">
                        <label>
                            <span>${this._escapeHtml(_t("Producto"))}</span>
                            <select data-field="product_id">
                                <option value="">${this._escapeHtml(_t("Selecciona un producto"))}</option>
                                ${productOptions}
                            </select>
                        </label>
                        <label>
                            <span>${this._escapeHtml(_t("Plan recurrente"))}</span>
                            <select data-field="plan_choice" ${newSubscriptionForm.plans.length ? "" : "disabled"}>
                                <option value="">${this._escapeHtml(_t("Selecciona un plan"))}</option>
                                ${planOptions}
                            </select>
                        </label>
                        <label>
                            <span>${this._escapeHtml(_t("Fecha de inicio"))}</span>
                            <input type="date" data-field="start_date" value="${this._escapeHtml(newSubscriptionForm.startDate || formatTodayISO())}" />
                        </label>
                        <div>
                            <span>${this._escapeHtml(_t("Fecha de fin"))}</span>
                            <strong class="wgs-inline-static-value">${this._escapeHtml(this._formatDateDisplay(automaticEndDate) || "-")}</strong>
                        </div>
                    </div>
                    <div class="wgs-inline-form-meta">
                        <div><span>${this._escapeHtml(_t("Precio"))}</span><strong>${this._escapeHtml(this._formatMoney(getChargeDisplayAmount(newSubscriptionForm.charge)))}</strong></div>
                        <div><span>${this._escapeHtml(_t("Cupo total"))}</span><strong>${this._escapeHtml(String(newSubscriptionForm.maxParticipantsTotal || 1))}</strong></div>
                        ${Number(newSubscriptionForm.maxParticipantsTotal || 1) > 1 ? `<div><span>${this._escapeHtml(_t("Participantes seleccionados"))}</span><strong>${this._escapeHtml(String((newSubscriptionForm.participantIds || []).length || 0))}</strong></div>` : ""}
                        <div><span>${this._escapeHtml(_t("Cobertura del plan"))}</span><strong>${this._escapeHtml(this._formatDateDisplay(automaticEndDate) || "-")}</strong></div>
                    </div>
                    ${Number(newSubscriptionForm.maxParticipantsTotal || 1) > 1 ? `
                        <div class="wgs-inline-participants">
                            <span class="wgs-inline-section-title">${this._escapeHtml(_t("Participantes permitidos"))}</span>
                            <input type="text" class="wgs-inline-search" data-field="participant_search" placeholder="${this._escapeHtml(_t("Buscar participante"))}" value="${this._escapeHtml(newSubscriptionForm.participantSearch || "")}" />
                            <div class="wgs-inline-participant-list">${participantOptions}</div>
                        </div>
                    ` : ""}
                    <div class="wgs-inline-actions">
                        <button type="button" class="wgs-primary-action-btn" data-action="save-new" ${newSubscriptionForm.loading ? "disabled" : ""}>${this._escapeHtml(_t("Agregar al ticket"))}</button>
                        <button type="button" class="wgs-secondary-action-btn" data-action="cancel-new">${this._escapeHtml(_t("Cancelar"))}</button>
                    </div>
                </div>
            `;
        };

        const renderNewPartnerForm = () => {
            if (formMode !== "new_partner" || !newPartnerForm) {
                return "";
            }
            return `
                <div class="wgs-inline-form-card">
                    <div class="wgs-inline-form-header">
                        <strong>${this._escapeHtml(_t("Nuevo cliente"))}</strong>
                        <button type="button" class="wgs-inline-close-btn" data-action="cancel-new-partner">${this._escapeHtml(_t("Cancelar"))}</button>
                    </div>
                    ${formError ? `<div class="wgs-inline-error">${this._escapeHtml(formError)}</div>` : ""}
                    ${formNotice ? `<div class="wgs-inline-notice">${this._escapeHtml(formNotice)}</div>` : ""}
                    <div class="wgs-new-partner-layout">
                        <div class="wgs-new-partner-photo">
                            <div class="wgs-new-partner-preview">
                                ${newPartnerForm.cameraActive
                                    ? `<video class="wgs-camera-preview" data-role="partner-camera-preview" autoplay playsinline muted></video>`
                                    : newPartnerForm.imageDataUrl
                                    ? `<img src="${this._escapeHtml(newPartnerForm.imageDataUrl)}" alt="${this._escapeHtml(_t("Foto del cliente"))}" />`
                                    : `<div class="wgs-new-partner-empty-photo">${this._escapeHtml(_t("Sin foto"))}</div>`
                                }
                            </div>
                            <div class="wgs-inline-actions wgs-photo-actions-grid">
                                <label class="wgs-secondary-action-btn wgs-file-action-btn">
                                    <span>${this._escapeHtml(_t("Subir foto"))}</span>
                                    <input type="file" accept="image/*" data-field="partner_image_file" hidden />
                                </label>
                                ${!newPartnerForm.cameraActive
                                    ? `<button type="button" class="wgs-secondary-action-btn" data-action="start-partner-camera">${this._escapeHtml(_t("Usar cámara"))}</button>`
                                    : `
                                        <button type="button" class="wgs-primary-action-btn" data-action="capture-partner-camera">${this._escapeHtml(_t("Capturar"))}</button>
                                        <button type="button" class="wgs-secondary-action-btn" data-action="stop-partner-camera">${this._escapeHtml(_t("Apagar cámara"))}</button>
                                    `
                                }
                            </div>
                        </div>
                        <div class="wgs-inline-form-grid">
                            <label>
                                <span>${this._escapeHtml(_t("Nombre"))}</span>
                                <input type="text" data-field="partner_name" value="${this._escapeHtml(newPartnerForm.name || "")}" />
                            </label>
                            <label>
                                <span>${this._escapeHtml(_t("Teléfono"))}</span>
                                <input type="text" data-field="partner_phone" value="${this._escapeHtml(newPartnerForm.phone || "")}" />
                            </label>
                            <label>
                                <span>${this._escapeHtml(_t("Email"))}</span>
                                <input type="email" data-field="partner_email" value="${this._escapeHtml(newPartnerForm.email || "")}" />
                            </label>
                            <label>
                                <span>${this._escapeHtml(_t("Género"))}</span>
                                <select data-field="partner_gender">
                                    <option value="">${this._escapeHtml(_t("Selecciona"))}</option>
                                    <option value="male" ${newPartnerForm.gender === "male" ? "selected" : ""}>${this._escapeHtml(_t("Masculino"))}</option>
                                    <option value="female" ${newPartnerForm.gender === "female" ? "selected" : ""}>${this._escapeHtml(_t("Femenino"))}</option>
                                    <option value="other" ${newPartnerForm.gender === "other" ? "selected" : ""}>${this._escapeHtml(_t("Otro"))}</option>
                                </select>
                            </label>
                            <label>
                                <span>${this._escapeHtml(_t("Cumpleaños"))}</span>
                                <input type="date" data-field="partner_birthday" value="${this._escapeHtml(newPartnerForm.birthday || "")}" />
                            </label>
                        </div>
                    </div>
                    <div class="wgs-inline-actions">
                        <button type="button" class="wgs-primary-action-btn" data-action="save-new-partner">${this._escapeHtml(_t("Crear cliente"))}</button>
                        <button type="button" class="wgs-secondary-action-btn" data-action="cancel-new-partner">${this._escapeHtml(_t("Cancelar"))}</button>
                    </div>
                </div>
            `;
        };

        const renderRenewalForm = (item) => {
            return buildRenewalFormHtml({
                item,
                formMode,
                renewalForm,
                formError,
                formNotice,
                escapeHtml: (value) => this._escapeHtml(value),
                formatDateDisplay: (value) => this._formatDateDisplay(value),
                formatMoney: (value) => this._formatMoney(value),
                getChargeDisplayAmount,
                _t,
            });
        };

        const renderPendingChargeForm = (item) => {
            return buildPendingChargeFormHtml({
                item,
                formMode,
                pendingChargeForm,
                formError,
                formNotice,
                escapeHtml: (value) => this._escapeHtml(value),
                formatDateDisplay: (value) => this._formatDateDisplay(value),
                formatMoney: (value) => this._formatMoney(value),
                getChargeDisplayAmount,
                _t,
            });
        };

        const renderCancellationRefundForm = (item) => {
            if (
                formMode !== "cancellation_refund"
                || !cancellationRefundForm
                || Number(cancellationRefundForm.subscriptionId || 0) !== Number(item.subscription_id || 0)
            ) {
                return "";
            }
            const canRefund = Boolean(cancellationRefundForm.originPosLineId) && !cancellationRefundForm.loading;
            return `
                <div class="wgs-inline-form-card">
                    <div class="wgs-inline-form-header">
                        <strong>${this._escapeHtml(_t("Cancelar suscripción"))}</strong>
                    </div>
                    ${formError ? `<div class="wgs-inline-error">${this._escapeHtml(formError)}</div>` : ""}
                    ${formNotice ? `<div class="wgs-inline-notice">${this._escapeHtml(formNotice)}</div>` : ""}
                    ${cancellationRefundForm.loading ? `<div class="wgs-inline-loading">${this._escapeHtml(_t("Consultando cobro POS exacto de esta suscripción..."))}</div>` : ""}
                    <div class="wgs-inline-form-meta">
                        <div><span>${this._escapeHtml(_t("Suscripción"))}</span><strong>${this._escapeHtml(cancellationRefundForm.subscriptionName || "-")}</strong></div>
                        <div><span>${this._escapeHtml(_t("Titular"))}</span><strong>${this._escapeHtml(cancellationRefundForm.holderPartnerName || "-")}</strong></div>
                        <div><span>${this._escapeHtml(_t("Ticket origen"))}</span><strong>${this._escapeHtml(cancellationRefundForm.originPosOrderName || "-")}</strong></div>
                        <div><span>${this._escapeHtml(_t("Fecha cobro"))}</span><strong>${this._escapeHtml(this._formatDateTimeDisplay(cancellationRefundForm.originDate) || "-")}</strong></div>
                        <div><span>${this._escapeHtml(_t("Producto"))}</span><strong>${this._escapeHtml(cancellationRefundForm.productName || "-")}</strong></div>
                        <div><span>${this._escapeHtml(_t("Monto a devolver"))}</span><strong>${this._escapeHtml(this._formatMoney(cancellationRefundForm.amountTotal || 0))}</strong></div>
                    </div>
                    <div class="wgs-inline-notice">${this._escapeHtml(_t("La devolución solo se generará si corresponde exactamente a esta suscripción."))}</div>
                    <div class="wgs-inline-actions">
                        <button type="button" class="wgs-primary-action-btn" data-action="save-cancellation-refund" ${canRefund ? "" : "disabled"}>${this._escapeHtml(_t("Agregar devolución al ticket"))}</button>
                        <button type="button" class="wgs-secondary-action-btn" data-action="cancel-cancellation-refund">${this._escapeHtml(_t("Cancelar"))}</button>
                    </div>
                </div>
            `;
        };

        const renderParticipantEditForm = (item) => {
            if (
                formMode !== "participants"
                || !participantEditForm
                || Number(participantEditForm.subscriptionId || 0) !== Number(item.subscription_id || 0)
            ) {
                return "";
            }
            const filteredParticipants = filterParticipantRows(participantEditForm.participantSearch);
            return buildParticipantEditFormHtml({
                item,
                formMode,
                participantEditForm,
                filteredParticipants,
                formError,
                formNotice,
                escapeHtml: (value) => this._escapeHtml(value),
                _t,
            });
        };

        const renderUpsaleForm = (item) => {
            if (
                formMode !== "upsale"
                || !upsaleForm
                || Number(upsaleForm.subscriptionId || 0) !== Number(item.subscription_id || 0)
            ) {
                return "";
            }
            const filteredParticipants = filterParticipantRows(upsaleForm.participantSearch);
            return buildUpsaleFormHtml({
                item,
                formMode,
                upsaleForm,
                productCatalog,
                filteredParticipants,
                formError,
                formNotice,
                catalogLoading,
                escapeHtml: (value) => this._escapeHtml(value),
                formatMoney: (value) => this._formatMoney(value),
                getChargeDisplayAmount,
                _t,
            });
        };

        const renderDetail = (detail) => {
            currentDetail = detail || null;
            if (!detail || !detail.partner_id) {
                renderDetailEmpty(
                    _t("Sin detalle"),
                    _t("No se pudo cargar la informacion del cliente seleccionado.")
                );
                return;
            }

            const subscriptions = Array.isArray(detail.items) ? detail.items : [];
            const summaryStateClass = this._getStateClass(detail.state);
            const isEditingPartnerPhoto = formMode === "partner_photo" && partnerPhotoForm && Number(partnerPhotoForm.partnerId || 0) === Number(detail.partner_id || 0);
            const detailAvatarHtml = renderPartnerDetailAvatar({
                detail,
                partnerPhotoForm,
                isEditingPartnerPhoto,
                formError,
                formNotice,
                escapeHtml: (value) => this._escapeHtml(value),
                _t,
            });
            const subscriptionsHtml = subscriptions.length
                ? subscriptions.map((item) => {
                    const stateClass = this._getStateClass(item.native_state_key);
                    const nativeStateKey = String(item.native_state_key || "").toLowerCase();
                    const canOperateSubscription = Boolean(
                        item.subscription_id
                        && (item.access_state === "enabled" || ["progress", "renew"].includes(nativeStateKey))
                    );
                    const participantNames = (item.participant_names || []).length
                        ? item.participant_names.map((name) => this._escapeHtml(name)).join(", ")
                        : this._escapeHtml(_t("Sin participantes"));
                    const accessSummary = item.access_people_summary || {};
                    const accessSiteLabel = (accessSummary.site_names || []).length
                        ? this._escapeHtml((accessSummary.site_names || []).join(", "))
                        : this._escapeHtml(_t("Sin sitios"));
                    const pendingDocumentHtml = renderPendingDocumentSummary({
                        item,
                        escapeHtml: (value) => this._escapeHtml(value),
                        formatMoney: (value) => this._formatMoney(value),
                        _t,
                    });
                    const inlineFormsHtml = [
                        renderParticipantEditForm(item),
                        renderPendingChargeForm(item),
                        renderCancellationRefundForm(item),
                        renderRenewalForm(item),
                        renderUpsaleForm(item),
                    ].join("");
                    return renderSubscriptionCard({
                        item,
                        canOperateSubscription,
                        stateClass,
                        participantNames,
                        accessSummary,
                        accessSiteLabel,
                        pendingDocumentHtml,
                        inlineFormsHtml,
                        escapeHtml: (value) => this._escapeHtml(value),
                        formatDateDisplay: (value) => this._formatDateDisplay(value),
                        formatMoney: (value) => this._formatMoney(value),
                        _t,
                    });
                }).join("")
                : `
                    <div class="wgs-detail-empty wgs-detail-empty-inline">
                        <strong>${this._escapeHtml(_t("Sin suscripciones relacionadas"))}</strong>
                        <p>${this._escapeHtml(_t("Este cliente no tiene suscripciones nativas vigentes o historicas visibles para POS."))}</p>
                    </div>
                `;

            detailPane.innerHTML = `
                ${renderDetailHeader({
                    detail,
                    isEditingPartnerPhoto,
                    detailAvatarHtml,
                    summaryStateClass,
                    escapeHtml: (value) => this._escapeHtml(value),
                    formatDateDisplay: (value) => this._formatDateDisplay(value),
                    formatDateTimeDisplay: (value) => this._formatDateTimeDisplay(value),
                    _t,
                })}
                <div class="wgs-detail-actions-bar">
                    <button type="button" class="wgs-primary-action-btn" data-action="open-new">${this._escapeHtml(_t("Nueva suscripcion"))}</button>
                </div>
                ${renderNewSubscriptionForm()}
                <div class="wgs-detail-note">${this._escapeHtml(_t("Renovación, upsale, cobro pendiente y participantes se operan desde cada tarjeta de suscripción."))}</div>
                <div class="wgs-detail-section">
                    <div class="wgs-detail-section-title">${this._escapeHtml(_t("Suscripciones del cliente"))}</div>
                    <div class="wgs-subscription-cards">${subscriptionsHtml}</div>
                </div>
            `;
            syncPartnerCameraPreview();
        };

        const renderDetailPreservingFocus = (detail) => {
            const focusState = captureFocusState(overlay);
            renderDetail(detail);
            restoreFocusState(overlay, focusState);
        };

        const loadDetail = async (partnerId, options = {}) => {
            const force = Boolean(options && options.force);
            if (!partnerId) {
                renderDetailEmpty(
                    _t("Selecciona un cliente"),
                    _t("Aqui veras sus suscripciones nativas, participantes y acciones disponibles.")
                );
                return;
            }
            if (!force && detailCache.has(partnerId)) {
                renderDetail(detailCache.get(partnerId));
                return;
            }

            renderDetailLoading();
            const requestId = ++detailRequestToken;
            try {
                const detail = await this._fetchPartnerSubscriptionDetail(partnerId);
                if (requestId !== detailRequestToken) {
                    return;
                }
                detailCache.set(partnerId, detail);
                if (selectedPartnerId === partnerId) {
                    renderDetail(detail);
                }
            } catch (error) {
                if (requestId !== detailRequestToken) {
                    return;
                }
                detailPane.innerHTML = `
                    <div class="wgs-detail-empty">
                        <strong>${this._escapeHtml(_t("Error al cargar detalle"))}</strong>
                        <p>${this._escapeHtml(_t("No se pudo consultar el detalle de suscripciones para este cliente."))}</p>
                    </div>
                `;
                console.error("Error al consultar detalle de suscripciones en POS", error);
            }
        };

        const render = () => {
            listFormContainer.innerHTML = renderNewPartnerForm();
            syncPartnerCameraPreview();
            const query = searchInput.value || "";
            const stateFilter = stateSelect.value;
            const birthdayFilter = birthdaySelect.value;
            const sortMode = sortSelect.value;

            let filtered = filterDirectoryRows(rows, {
                query,
                stateFilter,
                birthdayFilter,
                matchesBirthdayFilter: (birthdayValue, filterMode) =>
                    this._matchesBirthdayFilter(birthdayValue, filterMode),
            });
            filtered = sortDirectoryRows(filtered, {
                sortMode,
                getStateRank: (state) => this._getStateRank(state),
                toTimestamp: (value) => this._toTimestamp(value),
                getBirthdaySortRank: (value) => this._birthdaySortRank(value),
            });

            filteredSnapshot = filtered;

            const counts = countDirectoryRows(rows);

            summary.innerHTML = renderDirectorySummary({
                counts,
                filteredCount: filtered.length,
                directoryLoading,
                directoryLoadError,
                _t,
                escapeHtml: (value) => this._escapeHtml(value),
            });

            if (!filtered.length) {
                const emptyMessage = directoryLoading && !rows.length
                    ? _t("Cargando clientes...")
                    : _t("No hay resultados para el filtro actual.");
                tbody.innerHTML = `<tr><td colspan="7">${emptyMessage}</td></tr>`;
                clearDirectorySelection();
                renderDetailEmpty(
                    directoryLoading && !rows.length ? _t("Cargando directorio") : _t("Sin resultados"),
                    directoryLoading && !rows.length
                        ? _t("Estamos cargando el directorio de clientes en segundo plano.")
                        : _t("Ajusta los filtros para volver a cargar clientes en el directorio.")
                );
                return;
            }

            const filteredIds = filtered.map((row) => row.id);
            if (!selectedPartnerId || !filteredIds.includes(selectedPartnerId)) {
                selectedPartnerId = filtered[0].id;
                resetForPartnerSelection();
            }

            tbody.innerHTML = renderDirectoryRows({
                rows: filtered,
                selectedPartnerId,
                getStateClass: (state) => this._getStateClass(state),
                escapeHtml: (value) => this._escapeHtml(value),
                formatDateDisplay: (value) => this._formatDateDisplay(value),
                formatDateTimeDisplay: (value) => this._formatDateTimeDisplay(value),
                _t,
            });

            loadDetail(selectedPartnerId);
        };

        const renderPreservingFocus = () => {
            const focusState = captureFocusState(overlay);
            render();
            restoreFocusState(overlay, focusState);
        };

        bindDirectoryRowSelection(tbody, (partnerId) => {
            if (!partnerId || partnerId === selectedPartnerId) {
                return;
            }
            selectedPartnerId = partnerId;
            resetForPartnerSelection();
            render();
        });

        const listPaneActions = {
            ...buildListPartnerActionHandlers({
                state: modalState,
                clearFeedback,
                render,
                renderDetail,
                resetListPartnerForm,
                startPartnerCameraForForm,
                stopPartnerCameraForForm,
                capturePartnerCameraForForm,
                createPartner: (values) => this._createPartnerForPos(values),
                stopPartnerCamera,
                reloadDirectoryRows,
                loadDetail,
                createNewSubscriptionForm: (partnerId) => this._getDefaultNewSubscriptionForm(partnerId),
                openNewPartnerForm,
                overlayRoot: overlay,
                _t,
            }),
        };
        bindActionMap(listPane, listPaneActions);

        const getCurrentSubscriptionItem = (actionButton) => {
            const subscriptionId = Number(actionButton.dataset.subscriptionId || 0);
            return (currentDetail && Array.isArray(currentDetail.items) ? currentDetail.items : []).find(
                (row) => Number(row.subscription_id || 0) === subscriptionId
            );
        };

        const detailPaneActions = {
            "open-new": async () => {
                await openNewSubscriptionForm();
            },
            "cancel-new": async () => {
                resetInlineForms();
                renderDetail(currentDetail);
            },
            ...buildDetailPartnerActionHandlers({
                state: modalState,
                clearFeedback,
                render,
                renderDetail,
                resetListPartnerForm,
                startPartnerCameraForForm,
                stopPartnerCameraForForm,
                capturePartnerCameraForForm,
                createPartner: (values) => this._createPartnerForPos(values),
                updatePartnerPhoto: (partnerId, imageBase64) => this._updatePartnerPhotoForPos(partnerId, imageBase64),
                stopPartnerCamera,
                reloadDirectoryRows,
                loadDetail,
                createNewSubscriptionForm: (partnerId) => this._getDefaultNewSubscriptionForm(partnerId),
                openNewPartnerForm,
                openPartnerPhotoForm,
                overlayRoot: overlay,
                detailRoot: detailPane,
                detailCache,
                _t,
            }),
            "open-renewal": async ({ actionButton }) => {
                await openRenewalForm(getCurrentSubscriptionItem(actionButton));
            },
            "open-upsale": async ({ actionButton }) => {
                await openUpsaleForm(getCurrentSubscriptionItem(actionButton));
            },
            "open-participants": async ({ actionButton }) => {
                await openParticipantEditForm(getCurrentSubscriptionItem(actionButton));
            },
            "resync-access": async ({ actionButton }) => {
                const subscriptionId = Number(actionButton.dataset.subscriptionId || 0);
                if (!subscriptionId) {
                    return;
                }
                clearFeedback();
                try {
                    const result = await this._resyncSubscriptionAccess(subscriptionId);
                    const summary = result && result.access_summary ? result.access_summary : {};
                    formNotice = _t("Acceso resincronizado. Personas activas: %s. Personas sin registro: %s.").replace("%s", String(summary.active_count || 0)).replace("%s", String(summary.missing_count || 0));
                    if (currentDetail && currentDetail.partner_id) {
                        detailCache.delete(Number(currentDetail.partner_id || 0));
                    }
                    await loadDetail(selectedPartnerId, { force: true });
                } catch (error) {
                    console.error("Error al resincronizar acceso desde POS", error);
                    formError = (error && error.message) ? error.message : _t("No se pudo resincronizar el acceso de esta suscripción.");
                    renderDetail(currentDetail);
                }
            },
            "open-pending": async ({ actionButton }) => {
                await openPendingChargeForm(getCurrentSubscriptionItem(actionButton));
            },
            "open-cancellation-refund": async ({ actionButton }) => {
                await openCancellationRefundForm(getCurrentSubscriptionItem(actionButton));
            },
            "cancel-renewal": async () => {
                resetInlineForms();
                renderDetail(currentDetail);
            },
            "cancel-upsale": async () => {
                resetInlineForms();
                renderDetail(currentDetail);
            },
            "cancel-pending": async () => {
                resetInlineForms();
                renderDetail(currentDetail);
            },
            "cancel-cancellation-refund": async () => {
                resetInlineForms();
                renderDetail(currentDetail);
            },
            "cancel-participants": async () => {
                resetInlineForms();
                renderDetail(currentDetail);
            },
            "save-new": async () => {
                formError = "";
                formNotice = "";
                const selectedPlan = getSelectedPlan();
                if (!selectedPartnerId) {
                    formError = _t("Selecciona un cliente para agregar la suscripcion al ticket.");
                    renderDetail(currentDetail);
                    return;
                }
                if (!newSubscriptionForm.productId) {
                    formError = _t("Selecciona un producto de suscripcion.");
                    renderDetail(currentDetail);
                    return;
                }
                if (!selectedPlan) {
                    formError = _t("Selecciona un plan recurrente.");
                    renderDetail(currentDetail);
                    return;
                }
                const existingSubscriptionPartnerIds = getSubscriptionPartnerIdsFromOrder(getCurrentOrder(this));
                if (existingSubscriptionPartnerIds.length && !existingSubscriptionPartnerIds.includes(selectedPartnerId)) {
                    formError = _t("La orden actual ya contiene suscripciones configuradas para otro cliente. Usa un solo titular por ticket.");
                    renderDetail(currentDetail);
                    return;
                }
                const participantIds = [...new Set((newSubscriptionForm.participantIds || []).map((value) => Number(value || 0)).filter((value) => value > 0))];
                if (!participantIds.includes(selectedPartnerId)) {
                    participantIds.unshift(selectedPartnerId);
                }
                const posCharge = buildChargeBreakdown(this, null, newSubscriptionForm.charge || {});
                if (participantIds.length > Number(newSubscriptionForm.maxParticipantsTotal || 1)) {
                    formError = _t("Estas excediendo el cupo maximo de participantes para este paquete.");
                    renderDetail(currentDetail);
                    return;
                }
                const automaticEndDate = getPlanPeriodEndDate(
                    newSubscriptionForm.startDate,
                    selectedPlan.interval_value,
                    selectedPlan.interval_unit
                );
                if (!automaticEndDate) {
                    formError = _t("No se pudo calcular la fecha de fin automática para el plan seleccionado.");
                    renderDetail(currentDetail);
                    return;
                }

                const order = getCurrentOrder(this);
                if (!order) {
                    formError = _t("No hay una orden POS activa para agregar la suscripcion.");
                    renderDetail(currentDetail);
                    return;
                }
                const partnerOnOrderId = getPartnerIdFromOrder(order);
                if (partnerOnOrderId !== selectedPartnerId) {
                    const partnerRecord = findPartnerInPos(this, selectedPartnerId);
                    if (partnerRecord && setPartnerOnCurrentOrder(this, partnerRecord)) {
                        // Partner aligned locally in POS.
                    } else if (partnerOnOrderId) {
                        formError = _t("La orden actual ya tiene otro cliente y no se pudo reemplazar desde esta sesion. Usa un solo cliente por ticket.");
                        renderDetail(currentDetail);
                        return;
                    } else {
                        formNotice = _t("El cliente no esta cargado en la sesion local del POS. La suscripcion se vinculara al titular al confirmar el pago.");
                    }
                }

                const productRecord = findProductInPos(this, newSubscriptionForm.productId);
                if (!productRecord) {
                    formError = _t("El producto seleccionado no está cargado en la sesión actual del POS.");
                    renderDetail(currentDetail);
                    return;
                }

                let targetLine = null;
                try {
                    const lineResult = await addConfiguredProductLineToOrder(this, order, productRecord, {
                        quantity: 1,
                        merge: false,
                        charge: posCharge,
                        metadata: {
                            flow: "new",
                            partner_id: selectedPartnerId,
                            participant_ids: participantIds,
                            plan_id: Number(selectedPlan.plan_id || 0) || false,
                            pricing_id: Number(selectedPlan.pricing_id || 0) || false,
                            start_date: newSubscriptionForm.startDate || formatTodayISO(),
                            end_date: automaticEndDate || false,
                            product_id: Number(newSubscriptionForm.productId || 0) || false,
                            product_name: newSubscriptionForm.productName || false,
                        },
                    });
                    targetLine = lineResult && lineResult.line ? lineResult.line : null;
                    if (!targetLine && lineResult && lineResult.reason === "not_added") {
                        formError = _t("No se pudo agregar el producto al ticket actual.");
                        renderDetail(currentDetail);
                        return;
                    }
                } catch (error) {
                    console.error("Error al agregar producto de suscripcion al ticket POS", error);
                    formError = _t("No se pudo agregar el producto al ticket actual.");
                    renderDetail(currentDetail);
                    return;
                }
                if (!targetLine) {
                    formError = _t("No se pudo identificar la linea agregada al ticket.");
                    renderDetail(currentDetail);
                    return;
                }

                formMode = null;
                formError = "";
                formNotice = _t("Suscripcion agregada al ticket. Puedes continuar al cobro normal del POS.");
                renderDetail(currentDetail);
            },
            "save-pending": async () => {
                formError = "";
                formNotice = "";
                if (!pendingChargeForm || !pendingChargeForm.subscriptionId || !pendingChargeForm.pendingMoveId || !pendingChargeForm.productId) {
                    formError = _t("El documento pendiente seleccionado no tiene datos suficientes para agregarse al ticket.");
                    renderDetail(currentDetail);
                    return;
                }

                const order = getCurrentOrder(this);
                if (!order) {
                    formError = _t("No hay una orden POS activa para agregar el cobro pendiente.");
                    renderDetail(currentDetail);
                    return;
                }

                const holderPartnerId = Number(pendingChargeForm.holderPartnerId || 0) || false;
                const partnerOnOrderId = getPartnerIdFromOrder(order);
                if (partnerOnOrderId !== holderPartnerId) {
                    const partnerRecord = findPartnerInPos(this, holderPartnerId);
                    if (partnerRecord && setPartnerOnCurrentOrder(this, partnerRecord)) {
                        // Partner aligned locally in POS.
                    } else if (partnerOnOrderId) {
                        formError = _t("La orden actual ya tiene otro cliente y no se pudo reemplazar desde esta sesión. Usa un solo cliente por ticket.");
                        renderDetail(currentDetail);
                        return;
                    } else {
                        formNotice = _t("El titular no está cargado en la sesión local del POS. El cobro pendiente se vinculará al confirmar el pago.");
                    }
                }

                const productRecord = findProductInPos(this, pendingChargeForm.productId);
                if (!productRecord) {
                    formError = _t("El producto recurrente de esta suscripción no está cargado en la sesión actual del POS.");
                    renderDetail(currentDetail);
                    return;
                }

                let targetLine = null;
                try {
                    const lineResult = await addConfiguredProductLineToOrder(this, order, productRecord, {
                        quantity: 1,
                        merge: false,
                        charge: pendingChargeForm.charge,
                        metadata: {
                            flow: "pending_charge",
                            partner_id: holderPartnerId || false,
                            participant_ids: [],
                            plan_id: false,
                            pricing_id: false,
                            start_date: false,
                            end_date: false,
                            product_id: Number(pendingChargeForm.productId || 0) || false,
                            product_name: pendingChargeForm.productName || false,
                            source_subscription_id: Number(pendingChargeForm.subscriptionId || 0) || false,
                            pending_move_id: Number(pendingChargeForm.pendingMoveId || 0) || false,
                        },
                    });
                    targetLine = lineResult && lineResult.line ? lineResult.line : null;
                    if (!targetLine && lineResult && lineResult.reason === "not_added") {
                        formError = _t("No se pudo agregar el cobro pendiente al ticket actual.");
                        renderDetail(currentDetail);
                        return;
                    }
                } catch (error) {
                    console.error("Error al agregar cobro pendiente al ticket POS", error);
                    formError = _t("No se pudo agregar el cobro pendiente al ticket actual.");
                    renderDetail(currentDetail);
                    return;
                }

                if (!targetLine) {
                    formError = _t("No se pudo identificar la línea de cobro pendiente agregada al ticket.");
                    renderDetail(currentDetail);
                    return;
                }

                formMode = null;
                formError = "";
                formNotice = _t("Cobro pendiente agregado al ticket. Puedes continuar al cobro normal del POS.");
                renewalForm = null;
                upsaleForm = null;
                pendingChargeForm = null;
                participantEditForm = null;
                renderDetail(currentDetail);
            },
            "save-cancellation-refund": async () => {
                formError = "";
                formNotice = "";
                if (!cancellationRefundForm || !cancellationRefundForm.subscriptionId || !cancellationRefundForm.originPosLineId || !cancellationRefundForm.productId) {
                    formError = _t("No se encontró un cobro POS exacto para devolver esta suscripción.");
                    renderDetail(currentDetail);
                    return;
                }

                const order = getCurrentOrder(this);
                if (!order) {
                    formError = _t("No hay una orden POS activa para agregar la devolución.");
                    renderDetail(currentDetail);
                    return;
                }

                const holderPartnerId = Number(cancellationRefundForm.holderPartnerId || 0) || false;
                const partnerOnOrderId = getPartnerIdFromOrder(order);
                if (partnerOnOrderId !== holderPartnerId) {
                    const partnerRecord = findPartnerInPos(this, holderPartnerId);
                    if (partnerRecord && setPartnerOnCurrentOrder(this, partnerRecord)) {
                        // Partner aligned locally in POS.
                    } else if (partnerOnOrderId) {
                        formError = _t("La orden actual ya tiene otro cliente y no se pudo reemplazar desde esta sesión. Usa un solo cliente por ticket.");
                        renderDetail(currentDetail);
                        return;
                    } else {
                        formNotice = _t("El titular no está cargado en la sesión local del POS. La devolución se vinculará al confirmar el pago.");
                    }
                }

                const productRecord = findProductInPos(this, cancellationRefundForm.productId);
                if (!productRecord) {
                    formError = _t("El producto original de esta suscripción no está cargado en la sesión actual del POS.");
                    renderDetail(currentDetail);
                    return;
                }

                let targetLine = null;
                try {
                    const lineResult = await addConfiguredProductLineToOrder(this, order, productRecord, {
                        quantity: -Math.max(1, Number(cancellationRefundForm.qty || 1)),
                        merge: false,
                        lineUnitPrice: Number(cancellationRefundForm.priceUnit || 0),
                        discount: Number(cancellationRefundForm.discount || 0),
                        metadata: {
                            flow: "cancellation_refund",
                            partner_id: holderPartnerId || false,
                            participant_ids: [],
                            plan_id: false,
                            pricing_id: false,
                            start_date: false,
                            end_date: false,
                            product_id: Number(cancellationRefundForm.productId || 0) || false,
                            product_name: cancellationRefundForm.productName || false,
                            source_subscription_id: Number(cancellationRefundForm.subscriptionId || 0) || false,
                            refund_origin_line_id: Number(cancellationRefundForm.originPosLineId || 0) || false,
                        },
                    });
                    targetLine = lineResult && lineResult.line ? lineResult.line : null;
                    if (!targetLine && lineResult && lineResult.reason === "not_added") {
                        formError = _t("No se pudo agregar la devolución al ticket actual.");
                        renderDetail(currentDetail);
                        return;
                    }
                } catch (error) {
                    console.error("Error al agregar devolución por cancelación al ticket POS", error);
                    formError = _t("No se pudo agregar la devolución al ticket actual.");
                    renderDetail(currentDetail);
                    return;
                }

                if (!targetLine) {
                    formError = _t("No se pudo identificar la línea de devolución agregada al ticket.");
                    renderDetail(currentDetail);
                    return;
                }

                formMode = null;
                formError = "";
                formNotice = _t("Devolución agregada al ticket. Al cobrarla, la suscripción se cancelará.");
                renewalForm = null;
                upsaleForm = null;
                pendingChargeForm = null;
                cancellationRefundForm = null;
                participantEditForm = null;
                renderDetail(currentDetail);
            },
            "save-participants": async () => {
                formError = "";
                formNotice = "";
                if (!participantEditForm || !participantEditForm.subscriptionId) {
                    formError = _t("La suscripción seleccionada no tiene datos suficientes para editar participantes.");
                    renderDetail(currentDetail);
                    return;
                }
                const participantIds = [...new Set((participantEditForm.participantIds || []).map((value) => Number(value || 0)).filter((value) => value > 0))];
                const holderPartnerId = Number(participantEditForm.holderPartnerId || 0) || false;
                if (holderPartnerId && !participantIds.includes(holderPartnerId)) {
                    participantIds.unshift(holderPartnerId);
                }
                if (participantIds.length > Number(participantEditForm.maxParticipantsTotal || 1)) {
                    formError = _t("Estas excediendo el cupo máximo de participantes para este paquete.");
                    renderDetail(currentDetail);
                    return;
                }
                try {
                    const result = await this._saveSubscriptionParticipants(
                        participantEditForm.subscriptionId,
                        participantIds
                    );
                    formMode = null;
                    participantEditForm = null;
                    renewalForm = null;
                    upsaleForm = null;
                    pendingChargeForm = null;
                    formNotice = _t("Participantes actualizados correctamente.");
                    if (currentDetail && Array.isArray(currentDetail.items)) {
                        detailCache.delete(Number(currentDetail.partner_id || 0));
                    }
                    await loadDetail(selectedPartnerId, { force: true });
                    if (result && result.ok) {
                        return;
                    }
                } catch (error) {
                    console.error("Error al actualizar participantes de suscripción POS", error);
                    formError = (error && error.message) ? error.message : _t("No se pudieron guardar los participantes de la suscripción.");
                    renderDetail(currentDetail);
                    return;
                }
            },
            "save-upsale": async () => {
                formError = "";
                formNotice = "";
                if (!upsaleForm || !upsaleForm.subscriptionId || !upsaleForm.productId) {
                    formError = _t("Selecciona el paquete destino para agregar el upsale al ticket.");
                    renderDetail(currentDetail);
                    return;
                }
                const selectedUpsalePlan = getSelectedUpsalePlan();
                if (!selectedUpsalePlan) {
                    formError = _t("Selecciona el plan destino para el upsale.");
                    renderDetail(currentDetail);
                    return;
                }
                const participantIds = [...new Set((upsaleForm.participantIds || []).map((value) => Number(value || 0)).filter((value) => value > 0))];
                const holderPartnerId = Number(upsaleForm.holderPartnerId || 0) || false;
                if (holderPartnerId && !participantIds.includes(holderPartnerId)) {
                    participantIds.unshift(holderPartnerId);
                }
                if (participantIds.length > Number(upsaleForm.maxParticipantsTotal || 1)) {
                    formError = _t("Estas excediendo el cupo maximo permitido para el paquete destino.");
                    renderDetail(currentDetail);
                    return;
                }

                const order = getCurrentOrder(this);
                if (!order) {
                    formError = _t("No hay una orden POS activa para agregar el upsale.");
                    renderDetail(currentDetail);
                    return;
                }
                const existingSubscriptionPartnerIds = getSubscriptionPartnerIdsFromOrder(order);
                if (existingSubscriptionPartnerIds.length && !existingSubscriptionPartnerIds.includes(holderPartnerId)) {
                    formError = _t("La orden actual ya contiene suscripciones configuradas para otro cliente. Usa un solo titular por ticket.");
                    renderDetail(currentDetail);
                    return;
                }
                const partnerOnOrderId = getPartnerIdFromOrder(order);
                if (partnerOnOrderId !== holderPartnerId) {
                    const partnerRecord = findPartnerInPos(this, holderPartnerId);
                    if (partnerRecord && setPartnerOnCurrentOrder(this, partnerRecord)) {
                        // Partner aligned locally in POS.
                    } else if (partnerOnOrderId) {
                        formError = _t("La orden actual ya tiene otro cliente y no se pudo reemplazar desde esta sesión. Usa un solo cliente por ticket.");
                        renderDetail(currentDetail);
                        return;
                    } else {
                        formNotice = _t("El titular no está cargado en la sesión local del POS. El upsale se vinculará al confirmar el pago.");
                    }
                }

                const productRecord = findProductInPos(this, upsaleForm.productId);
                if (!productRecord) {
                    formError = _t("El producto destino no está cargado en la sesión actual del POS.");
                    renderDetail(currentDetail);
                    return;
                }

                let targetLine = null;
                try {
                    const lineResult = await addConfiguredProductLineToOrder(this, order, productRecord, {
                        quantity: 1,
                        merge: false,
                        charge: upsaleForm.charge,
                        metadata: {
                            flow: "upsale",
                            partner_id: holderPartnerId || false,
                            participant_ids: participantIds,
                            plan_id: Number(selectedUpsalePlan.plan_id || 0) || false,
                            pricing_id: Number(selectedUpsalePlan.pricing_id || 0) || false,
                            start_date: formatTodayISO(),
                            end_date: false,
                            product_id: Number(upsaleForm.productId || 0) || false,
                            product_name: upsaleForm.productName || false,
                            source_subscription_id: Number(upsaleForm.subscriptionId || 0) || false,
                        },
                    });
                    targetLine = lineResult && lineResult.line ? lineResult.line : null;
                    if (!targetLine && lineResult && lineResult.reason === "not_added") {
                        formError = _t("No se pudo agregar el upsale al ticket actual.");
                        renderDetail(currentDetail);
                        return;
                    }
                } catch (error) {
                    console.error("Error al agregar upsale al ticket POS", error);
                    formError = _t("No se pudo agregar el upsale al ticket actual.");
                    renderDetail(currentDetail);
                    return;
                }

                if (!targetLine) {
                    formError = _t("No se pudo identificar la línea de upsale agregada al ticket.");
                    renderDetail(currentDetail);
                    return;
                }

                formMode = null;
                formError = "";
                formNotice = _t("Upsale agregado al ticket. Puedes continuar al cobro normal del POS.");
                renewalForm = null;
                upsaleForm = null;
                pendingChargeForm = null;
                participantEditForm = null;
                renderDetail(currentDetail);
            },
            "save-renewal": async () => {
                formError = "";
                formNotice = "";
                if (!renewalForm || !renewalForm.subscriptionId || !renewalForm.productId) {
                    formError = _t("La renovación seleccionada no tiene datos suficientes para agregarse al ticket.");
                    renderDetail(currentDetail);
                    return;
                }

                const order = getCurrentOrder(this);
                if (!order) {
                    formError = _t("No hay una orden POS activa para agregar la renovación.");
                    renderDetail(currentDetail);
                    return;
                }

                const holderPartnerId = Number(renewalForm.holderPartnerId || 0) || false;
                const partnerOnOrderId = getPartnerIdFromOrder(order);
                if (partnerOnOrderId !== holderPartnerId) {
                    const partnerRecord = findPartnerInPos(this, holderPartnerId);
                    if (partnerRecord && setPartnerOnCurrentOrder(this, partnerRecord)) {
                        // Partner aligned locally in POS.
                    } else if (partnerOnOrderId) {
                        formError = _t("La orden actual ya tiene otro cliente y no se pudo reemplazar desde esta sesión. Usa un solo cliente por ticket.");
                        renderDetail(currentDetail);
                        return;
                    } else {
                        formNotice = _t("El titular no está cargado en la sesión local del POS. La renovación se vinculará al confirmar el pago.");
                    }
                }

                const productRecord = findProductInPos(this, renewalForm.productId);
                if (!productRecord) {
                    formError = _t("El producto recurrente de esta suscripción no está cargado en la sesión actual del POS.");
                    renderDetail(currentDetail);
                    return;
                }

                let targetLine = null;
                try {
                    const lineResult = await addConfiguredProductLineToOrder(this, order, productRecord, {
                        quantity: 1,
                        merge: false,
                        charge: renewalForm.charge,
                        metadata: {
                            flow: "renewal",
                            partner_id: holderPartnerId || false,
                            participant_ids: [],
                            plan_id: Number(renewalForm.planId || 0) || false,
                            pricing_id: Number(renewalForm.pricingId || 0) || false,
                            start_date: false,
                            end_date: false,
                            product_id: Number(renewalForm.productId || 0) || false,
                            product_name: renewalForm.productName || false,
                            source_subscription_id: Number(renewalForm.subscriptionId || 0) || false,
                        },
                    });
                    targetLine = lineResult && lineResult.line ? lineResult.line : null;
                    if (!targetLine && lineResult && lineResult.reason === "not_added") {
                        formError = _t("No se pudo agregar la renovación al ticket actual.");
                        renderDetail(currentDetail);
                        return;
                    }
                } catch (error) {
                    console.error("Error al agregar renovación al ticket POS", error);
                    formError = _t("No se pudo agregar la renovación al ticket actual.");
                    renderDetail(currentDetail);
                    return;
                }

                if (!targetLine) {
                    formError = _t("No se pudo identificar la línea de renovación agregada al ticket.");
                    renderDetail(currentDetail);
                    return;
                }

                formMode = null;
                formError = "";
                formNotice = _t("Renovación agregada al ticket. Puedes continuar al cobro normal del POS.");
                renewalForm = null;
                upsaleForm = null;
                pendingChargeForm = null;
                participantEditForm = null;
                renderDetail(currentDetail);
            },
        };
        bindActionMap(detailPane, detailPaneActions);

        bindFieldChange(detailPane, async ({ field, target }) => {
            const handledPartnerField = await handleDetailPartnerFieldChange(
                { field, target },
                {
                    state: modalState,
                    clearFeedback,
                    readFileAsDataUrl: (file) => this._readFileAsDataUrl(file),
                    applyImageDataUrlToForm,
                    renderDetail,
                    _t,
                }
            );
            if (handledPartnerField) {
                return;
            }
            clearFeedback();
            if (formMode === "new" && field === "product_id") {
                await applySelectedProduct(target.value);
            } else if (formMode === "new" && field === "plan_choice") {
                await updateSelectedPlan(target.value);
            } else if (formMode === "new" && field === "start_date") {
                newSubscriptionForm.startDate = target.value || formatTodayISO();
            } else if (formMode === "new" && field === "participant_toggle") {
                toggleParticipant(target.value, target.checked);
            } else if (formMode === "upsale" && field === "upsale_product_id") {
                await applySelectedUpsaleProduct(target.value);
            } else if (formMode === "upsale" && field === "upsale_plan_choice") {
                await updateSelectedUpsalePlan(target.value);
            } else if (formMode === "upsale" && field === "upsale_participant_toggle") {
                toggleUpsaleParticipant(target.value, target.checked);
            } else if (formMode === "participants" && field === "edit_participant_toggle") {
                toggleEditedParticipant(target.value, target.checked);
            }
            renderDetail(currentDetail);
        });

        bindFieldChange(listPane, async ({ field, target }) => {
            await handleListPartnerFieldChange(
                { field, target },
                {
                    state: modalState,
                    clearFeedback,
                    readFileAsDataUrl: (file) => this._readFileAsDataUrl(file),
                    applyImageDataUrlToForm,
                    render,
                    _t,
                }
            );
        });

        bindFieldInput(listPane, ({ field, target }) => {
            handleListPartnerFieldInput({ field, target }, { state: modalState });
        });

        bindFieldInput(detailPane, ({ field, target }) => {
            let shouldRender = false;
            if (formMode === "new" && field === "participant_search") {
                newSubscriptionForm.participantSearch = target.value || "";
                shouldRender = true;
            } else if (formMode === "upsale" && field === "upsale_participant_search") {
                upsaleForm.participantSearch = target.value || "";
                shouldRender = true;
            } else if (formMode === "participants" && field === "edit_participant_search") {
                participantEditForm.participantSearch = target.value || "";
                shouldRender = true;
            } else if (!handleDetailPartnerFieldInput({ field, target }, { state: modalState })) {
                return;
            }
            if (shouldRender) {
                renderDetailPreservingFocus(currentDetail);
            }
        });

        bindDirectoryToolbarEvents({
            searchInput,
            stateSelect,
            birthdaySelect,
            sortSelect,
            exportButton,
            onSearchInput: renderPreservingFocus,
            onStateChange: render,
            onBirthdayChange: render,
            onSortChange: render,
            onExport: () => {
                this._downloadDirectoryAsXls(filteredSnapshot);
            },
        });

        render();
        loadDirectoryRowsInBackground({ reset: !rows.length, preferredPartnerId: selectedPartnerId });
    },

    _getDefaultNewSubscriptionForm(partnerId) {
        return getDefaultNewSubscriptionForm(partnerId, {
            buildChargeBreakdown,
            formatTodayISO,
        });
    },

    _getDefaultNewPartnerForm() {
        return getDefaultNewPartnerForm();
    },

    _getDefaultUpsaleForm(item = null) {
        return getDefaultUpsaleForm(item, { buildChargeBreakdown });
    },

    _getDefaultParticipantEditForm(item = null) {
        return getDefaultParticipantEditForm(item);
    },

    _getStateRank(state) {
        return getStateRank(state);
    },

    _getStateClass(state) {
        return getStateClass(state);
    },

    _formatMoney(value) {
        return formatMoney(value);
    },

    _toTimestamp(value) {
        return toTimestamp(value);
    },

    _birthdaySortRank(birthdayValue) {
        return getBirthdaySortRank(birthdayValue);
    },

    _matchesBirthdayFilter(birthdayValue, filterMode) {
        return matchesBirthdayFilter(birthdayValue, filterMode);
    },

    _formatDateDisplay(value) {
        return formatDateDisplay(value);
    },

    _formatDateTimeDisplay(value) {
        return formatDateTimeDisplay(value);
    },

    _downloadDirectoryAsXls(rows) {
        downloadDirectoryAsXls({
            rows,
            escapeHtml: (value) => this._escapeHtml(value),
            formatDateDisplay: (value) => this._formatDateDisplay(value),
            formatDateTimeDisplay: (value) => this._formatDateTimeDisplay(value),
            _t,
        });
    },

    _readFileAsDataUrl(file) {
        return readFileAsDataUrl(file);
    },

    _stripDataUrlPrefix(value) {
        return stripDataUrlPrefix(value);
    },

    _showSimpleInfoModal(title, message) {
        showSimpleInfoModal({
            modalId: MODAL_ID,
            title,
            message,
            closeLabel: _t("Cerrar"),
            escapeHtml: (value) => this._escapeHtml(value),
        });
    },

    _escapeHtml(value) {
        return escapeHtml(value);
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
                height: min(92vh, 980px);
                max-height: 92vh;
                overflow: hidden;
                background: #ffffff;
                border-radius: 0.75rem;
                box-shadow: 0 20px 50px rgba(0, 0, 0, 0.3);
                display: flex;
                flex-direction: column;
            }
            .wgs-directory-modal {
                width: min(1580px, 99vw);
            }
            .control-buttons {
                flex-wrap: wrap !important;
                align-content: flex-start;
            }
            .wgs-control-buttons-row {
                width: 100%;
                flex: 0 0 100%;
                order: 999;
                display: flex;
                gap: 0.35rem;
                margin-top: 0.35rem;
            }
            .wgs-control-button {
                flex: 1 1 auto;
                min-width: 0;
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
                grid-template-columns: 2fr repeat(4, minmax(160px, 1fr));
                gap: 0.6rem;
                border-bottom: 1px solid #e5e7eb;
                align-items: center;
            }
            .wgs-status-toolbar input,
            .wgs-status-toolbar select,
            .wgs-status-toolbar button,
            .wgs-inline-form-grid input,
            .wgs-inline-form-grid select {
                width: 100%;
                border: 1px solid #d1d5db;
                border-radius: 0.45rem;
                padding: 0.45rem 0.55rem;
                font-size: 0.88rem;
                background: #fff;
                color: #111827;
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
            .wgs-summary-positive {
                border-color: #8ad9b5;
                color: #0f7b4b;
                background: #daf5e8;
            }
            .wgs-summary-warning {
                border-color: #fcd34d;
                color: #92400e;
                background: #fef3c7;
            }
            .wgs-summary-negative {
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
                overflow: hidden;
                color: #1f2937;
                flex: 1 1 auto;
                min-height: 0;
            }
            .wgs-subscription-layout {
                display: grid;
                grid-template-columns: minmax(620px, 1.2fr) minmax(420px, 0.8fr);
                height: 100%;
                min-height: 0;
            }
            .wgs-subscription-list-pane {
                border-right: 1px solid #e5e7eb;
                overflow: auto;
                min-height: 0;
            }
            .wgs-list-actions-bar,
            .wgs-list-form-container {
                padding: 0.85rem 1rem 0;
            }
            .wgs-list-form-container {
                padding-top: 0.7rem;
            }
            .wgs-subscription-detail-pane {
                overflow: auto;
                background: #f8fafc;
                padding: 1rem;
                min-height: 0;
            }
            .wgs-detail-empty {
                border: 1px dashed #cbd5e1;
                border-radius: 0.75rem;
                background: #ffffff;
                padding: 1rem;
                color: #475569;
            }
            .wgs-detail-empty strong {
                display: block;
                color: #0f172a;
                margin-bottom: 0.3rem;
            }
            .wgs-detail-empty-inline {
                margin-top: 0.4rem;
            }
            .wgs-detail-header-card {
                display: grid;
                grid-template-columns: 72px 1fr;
                gap: 0.9rem;
                background: #ffffff;
                border: 1px solid #e5e7eb;
                border-radius: 0.85rem;
                padding: 1rem;
                margin-bottom: 0.85rem;
            }
            .wgs-detail-header-card-editing {
                grid-template-columns: minmax(168px, 196px) 1fr;
                align-items: start;
            }
            .wgs-detail-avatar {
                width: 72px;
                height: 72px;
                border-radius: 16px;
                object-fit: cover;
                background: #e2e8f0;
                border: 1px solid #d1d5db;
            }
            .wgs-detail-avatar-stack {
                display: flex;
                flex-direction: column;
                gap: 0.5rem;
                align-items: flex-start;
            }
            .wgs-detail-avatar-stack-editing {
                width: 100%;
            }
            .wgs-detail-avatar-editor {
                width: 100%;
                max-width: 168px;
                aspect-ratio: 1 / 1;
                border-radius: 0.7rem;
                border: 1px solid #d7deea;
                background: #eff6ff;
                overflow: hidden;
            }
            .wgs-detail-avatar-editor .wgs-detail-avatar {
                width: 100%;
                height: 100%;
                max-width: none;
                border: none;
                border-radius: 0;
            }
            .wgs-avatar-edit-btn {
                width: 100%;
                white-space: normal;
                text-align: center;
                line-height: 1.2;
            }
            .wgs-detail-photo-actions {
                width: 100%;
            }
            .wgs-detail-title-row {
                display: flex;
                justify-content: space-between;
                gap: 0.6rem;
                align-items: center;
                margin-bottom: 0.75rem;
            }
            .wgs-detail-title-row h4 {
                margin: 0;
                color: #0f172a;
                font-size: 1.05rem;
            }
            .wgs-detail-contact-grid {
                display: grid;
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 0.75rem;
            }
            .wgs-detail-contact-grid div,
            .wgs-subscription-grid div,
            .wgs-inline-form-meta div {
                display: flex;
                flex-direction: column;
                gap: 0.18rem;
            }
            .wgs-detail-contact-grid span,
            .wgs-subscription-grid span,
            .wgs-subscription-participants span,
            .wgs-inline-form-grid label span,
            .wgs-inline-form-meta span,
            .wgs-inline-section-title {
                font-size: 0.72rem;
                text-transform: uppercase;
                letter-spacing: 0.04em;
                color: #64748b;
                font-weight: 700;
            }
            .wgs-detail-contact-grid strong,
            .wgs-subscription-grid strong,
            .wgs-inline-form-meta strong {
                color: #0f172a;
                font-size: 0.9rem;
            }
            .wgs-detail-actions-bar,
            .wgs-subscription-actions,
            .wgs-inline-actions {
                display: grid;
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 0.55rem;
            }
            .wgs-primary-action-btn,
            .wgs-secondary-action-btn,
            .wgs-action-btn,
            .wgs-inline-close-btn {
                border-radius: 0.65rem;
                padding: 0.65rem 0.8rem;
                font-weight: 700;
                font-size: 0.84rem;
                border: 1px solid #cbd5e1;
                background: #ffffff;
                color: #334155;
            }
            .wgs-primary-action-btn {
                background: #0f766e;
                color: #ffffff;
                border-color: #0f766e;
            }
            .wgs-primary-action-btn:disabled,
            .wgs-secondary-action-btn:disabled,
            .wgs-action-btn:disabled {
                opacity: 0.7;
                cursor: not-allowed;
            }
            .wgs-detail-note {
                font-size: 0.8rem;
                color: #475569;
                margin-bottom: 0.9rem;
            }
            .wgs-detail-section {
                display: flex;
                flex-direction: column;
                gap: 0.6rem;
            }
            .wgs-detail-section-title {
                font-size: 0.84rem;
                font-weight: 800;
                text-transform: uppercase;
                letter-spacing: 0.05em;
                color: #334155;
            }
            .wgs-subscription-cards {
                display: flex;
                flex-direction: column;
                gap: 0.75rem;
            }
            .wgs-subscription-card,
            .wgs-inline-form-card {
                background: #ffffff;
                border: 1px solid #e5e7eb;
                border-radius: 0.85rem;
                padding: 0.9rem;
                display: flex;
                flex-direction: column;
                gap: 0.75rem;
                margin-bottom: 0.85rem;
            }
            .wgs-subscription-card-header,
            .wgs-inline-form-header {
                display: flex;
                justify-content: space-between;
                gap: 0.6rem;
                align-items: flex-start;
            }
            .wgs-subscription-card-meta {
                margin-top: 0.2rem;
                color: #64748b;
                font-size: 0.78rem;
            }
            .wgs-subscription-grid,
            .wgs-inline-form-grid,
            .wgs-inline-form-meta {
                display: grid;
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 0.7rem;
            }
            .wgs-subscription-participants p {
                margin: 0.25rem 0 0;
                color: #0f172a;
                line-height: 1.45;
            }
            .wgs-inline-error {
                border: 1px solid #fda4af;
                background: #fff1f2;
                color: #9f1239;
                border-radius: 0.65rem;
                padding: 0.65rem 0.75rem;
                font-size: 0.84rem;
                font-weight: 600;
            }
            .wgs-inline-notice {
                border: 1px solid #8ad9b5;
                background: #ecfdf5;
                color: #0f7b4b;
                border-radius: 0.65rem;
                padding: 0.65rem 0.75rem;
                font-size: 0.84rem;
                font-weight: 600;
            }
            .wgs-inline-error-compact,
            .wgs-inline-notice-compact {
                width: 100%;
                padding: 0.45rem 0.55rem;
                font-size: 0.76rem;
            }
            .wgs-inline-loading {
                color: #475569;
                font-size: 0.84rem;
            }
            .wgs-inline-search {
                width: 100%;
                border: 1px solid #d1d5db;
                border-radius: 0.45rem;
                padding: 0.45rem 0.55rem;
                font-size: 0.88rem;
                background: #fff;
                color: #111827;
            }
            .wgs-inline-participant-list {
                max-height: 220px;
                overflow: auto;
                display: grid;
                grid-template-columns: 1fr;
                gap: 0.35rem;
                border: 1px solid #e5e7eb;
                border-radius: 0.65rem;
                padding: 0.55rem;
                background: #f8fafc;
            }
            .wgs-checkbox-option {
                display: flex;
                gap: 0.55rem;
                align-items: center;
                color: #0f172a;
                font-size: 0.84rem;
            }
            .wgs-checkbox-owner {
                font-weight: 700;
            }
            .wgs-new-partner-layout {
                display: grid;
                grid-template-columns: minmax(136px, 168px) minmax(0, 1fr);
                gap: 0.8rem;
                align-items: start;
            }
            .wgs-new-partner-photo {
                display: flex;
                flex-direction: column;
                gap: 0.45rem;
            }
            .wgs-new-partner-preview {
                width: 100%;
                max-width: 168px;
                aspect-ratio: 1 / 1;
                border-radius: 0.7rem;
                border: 1px solid #d7deea;
                background: #eff6ff;
                overflow: hidden;
            }
            .wgs-new-partner-preview img,
            .wgs-camera-preview {
                width: 100%;
                height: 100%;
                object-fit: cover;
                display: block;
            }
            .wgs-camera-preview {
                max-width: none;
                aspect-ratio: auto;
                border: none;
                border-radius: 0;
                background: transparent;
            }
            .wgs-new-partner-empty-photo {
                width: 100%;
                height: 100%;
                display: flex;
                align-items: center;
                justify-content: center;
                color: #64748b;
                font-weight: 700;
            }
            .wgs-inline-actions-stacked {
                grid-template-columns: 1fr;
            }
            .wgs-photo-actions-grid {
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 0.4rem;
            }
            .wgs-new-partner-photo .wgs-primary-action-btn,
            .wgs-new-partner-photo .wgs-secondary-action-btn,
            .wgs-photo-actions-grid .wgs-primary-action-btn,
            .wgs-photo-actions-grid .wgs-secondary-action-btn,
            .wgs-photo-actions-grid .wgs-file-action-btn {
                min-height: 36px;
                padding: 0.45rem 0.55rem;
                font-size: 0.8rem;
            }
            .wgs-file-action-btn {
                display: inline-flex;
                align-items: center;
                justify-content: center;
                cursor: pointer;
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
            .wgs-btn-export {
                background: #0369a1;
                white-space: nowrap;
            }
            .wgs-status-table {
                width: 100%;
                border-collapse: collapse;
            }
            .wgs-status-table th,
            .wgs-status-table td {
                border-bottom: 1px solid #e5e7eb;
                padding: 0.6rem 0.65rem;
                text-align: left;
                vertical-align: middle;
                font-size: 0.84rem;
            }
            .wgs-status-table tbody tr {
                cursor: pointer;
            }
            .wgs-status-table tbody tr:hover {
                background: #f8fafc;
            }
            .wgs-selected-row {
                background: #ecfeff !important;
            }
            .wgs-status-table th {
                position: sticky;
                top: 0;
                z-index: 1;
                background: #f8fafc;
                font-size: 0.74rem;
                color: #374151;
                text-transform: uppercase;
                letter-spacing: 0.03em;
            }
            .wgs-partner-avatar {
                width: 38px;
                height: 38px;
                border-radius: 50%;
                object-fit: cover;
                border: 1px solid #d1d5db;
                display: block;
                background: #f1f5f9;
            }
            .wgs-cell-name {
                font-weight: 700;
                color: #0f172a;
                min-width: 190px;
            }
            .wgs-state-badge {
                display: inline-flex;
                align-items: center;
                justify-content: center;
                border-radius: 999px;
                padding: 0.18rem 0.55rem;
                font-size: 0.74rem;
                font-weight: 700;
                border: 1px solid #d1d5db;
                white-space: nowrap;
            }
            .wgs-state-positive {
                border-color: #8ad9b5;
                color: #0f7b4b;
                background: #daf5e8;
            }
            .wgs-state-warning {
                border-color: #fcd34d;
                color: #92400e;
                background: #fef3c7;
            }
            .wgs-state-negative {
                border-color: #fda4af;
                color: #9f1239;
                background: #ffe4e6;
            }
            .wgs-state-neutral {
                border-color: #cbd5e1;
                color: #475569;
                background: #f1f5f9;
            }
            .wgs-simple-message {
                padding: 1rem 1.2rem;
            }
            @media (max-width: 1250px) {
                .wgs-subscription-layout {
                    grid-template-columns: 1fr;
                    height: auto;
                }
                .wgs-subscription-list-pane {
                    border-right: none;
                    border-bottom: 1px solid #e5e7eb;
                    max-height: 42vh;
                }
            }
            @media (max-width: 900px) {
                .wgs-status-toolbar,
                .wgs-detail-contact-grid,
                .wgs-subscription-grid,
                .wgs-detail-actions-bar,
                .wgs-subscription-actions,
                .wgs-inline-form-grid,
                .wgs-inline-form-meta,
                .wgs-inline-actions {
                    grid-template-columns: 1fr;
                }
                .wgs-detail-header-card {
                    grid-template-columns: 1fr;
                }
                .wgs-detail-header-card-editing {
                    grid-template-columns: 1fr;
                }
                .wgs-new-partner-layout {
                    grid-template-columns: 1fr;
                }
                .wgs-new-partner-preview,
                .wgs-camera-preview {
                    max-width: 100%;
                }
                .wgs-detail-avatar-editor {
                    max-width: 100%;
                }
                .wgs-photo-actions-grid {
                    grid-template-columns: 1fr;
                }
                .wgs-detail-avatar {
                    width: 64px;
                    height: 64px;
                }
            }
        `;
        document.head.appendChild(style);
    },
});

patch(PaymentScreen.prototype, {
    setup() {
        super.setup(...arguments);
        this.orm = this.orm || useService("orm");
    },

    async validateOrder(isForceValidate) {
        const order = getCurrentOrder(this.pos);
        try {
            const result = await stageSubscriptionConfigsForOrder(this.orm, order);
            if (result && result.ok === false) {
                window.alert(_t("No se pudo preparar la configuracion de suscripcion para esta venta. Actualiza el modulo y vuelve a intentar."));
                return;
            }
        } catch (error) {
            console.error("Error al preparar configuracion de suscripcion antes del cobro POS", error);
            window.alert(_t("No se pudo preparar la configuracion de suscripcion antes del cobro."));
            return;
        }
        return super.validateOrder(...arguments);
    },
});
