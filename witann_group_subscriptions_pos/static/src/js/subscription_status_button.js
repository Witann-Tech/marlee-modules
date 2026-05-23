/** @odoo-module **/

import {
    addConfiguredProductLineToOrder,
    collectSubscriptionConfigsFromOrder,
    convertTaxExcludedPriceToDisplay,
    ensureProductLoadedInPos,
    ensurePartnerLoadedInPos,
    getCurrentOrder,
    getCurrentCompanyId,
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
import { buildChargeFromSnapshot, getCurrentPlanChoice } from "./subscription_pricing_snapshot";
import {
    getDefaultExistingPartnerForm,
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
    getDiscountedDisplayAmount,
    renderDiscountAuthorizationSection,
} from "./subscription_discount_render";
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
    getTodayAccessLogRange,
    localDateTimeInputToUtcString,
    renderAccessLogContent,
    renderAccessLogToolbar,
} from "./subscription_access_log_render";
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
    getCurrentSubscriptionItem as getCurrentSubscriptionItemFromDetail,
    loadDetail as loadDetailController,
    loadDirectoryRowsInBackground as loadDirectoryRowsInBackgroundController,
    reloadDirectoryRows as reloadDirectoryRowsController,
    selectDirectoryPartner as selectDirectoryPartnerController,
} from "./subscription_data_controllers";
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
import { renderDetailContent } from "./subscription_detail_composer";
import {
    renderSubscriptionCard,
} from "./subscription_card_render";
import { renderPartnerDetailAvatar } from "./subscription_partner_render";
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
    openPartnerEditForm as openPartnerEditFormState,
    openPartnerPhotoForm as openPartnerPhotoFormState,
} from "./subscription_partner_handlers";
import {
    buildSubscriptionInlineActionHandlers,
    handleSubscriptionInlineFieldChange,
    handleSubscriptionInlineFieldInput,
} from "./subscription_inline_form_handlers";
import {
    applySelectedProduct as applySelectedProductFlow,
    applySelectedUpsaleProduct as applySelectedUpsaleProductFlow,
    clampParticipantIds,
    filterParticipantRows as filterParticipantRowsFlow,
    openNewSubscriptionForm as openNewSubscriptionFlow,
    openParticipantEditForm as openParticipantEditFlow,
    openReenrollForm as openReenrollFlow,
    openRenewalForm as openRenewalFlow,
    openUpsaleForm as openUpsaleFlow,
    recalculateNewSubscriptionCharge as recalculateNewSubscriptionChargeFlow,
    toggleEditedParticipant as toggleEditedParticipantFlow,
    toggleParticipant as toggleParticipantFlow,
    toggleUpsaleParticipant as toggleUpsaleParticipantFlow,
    updateSelectedPlan as updateSelectedPlanFlow,
    updateSelectedUpsalePlan as updateSelectedUpsalePlanFlow,
} from "./subscription_flow_controllers";
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
            const batch = await this.subscriptionPosApi.fetchPartnerDirectoryBatch(offset, batchSize, {
                stateFilter: "all",
                searchTerm: "",
            });
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

    async _fetchPartnerDirectorySummary() {
        return this.subscriptionPosApi.fetchPartnerDirectorySummary();
    },

    async _fetchPartnerSubscriptionDetail(partnerId) {
        return this.subscriptionPosApi.fetchPartnerSubscriptionDetail(partnerId);
    },

    async _createPartnerForPos(values) {
        return this.subscriptionPosApi.createPartner(values || {});
    },

    async _updatePartnerCurpForPos(partnerId, curp) {
        return this.subscriptionPosApi.updatePartnerCurp(partnerId, curp || false);
    },

    async _updatePartnerForPos(partnerId, values) {
        return this.subscriptionPosApi.updatePartner(partnerId, values || {});
    },

    async _validateSubscriptionProductEligibilityForPos(partnerId, productId, flow = "new", sourceSubscriptionId = false) {
        return this.subscriptionPosApi.validateSubscriptionProductEligibility(
            partnerId,
            productId,
            flow || "new",
            sourceSubscriptionId || false
        );
    },

    async _authorizeSubscriptionDiscountForPos(partnerId, productId, flow = "new", discountCode = false, supervisorPin = false, sourceSubscriptionId = false) {
        return this.subscriptionPosApi.authorizeSubscriptionDiscount(
            partnerId,
            productId,
            flow || "new",
            discountCode || false,
            supervisorPin || false,
            sourceSubscriptionId || false
        );
    },

    async _updatePartnerPhotoForPos(partnerId, imageBase64) {
        return this.subscriptionPosApi.updatePartnerPhoto(partnerId, imageBase64 || false);
    },

    async _fetchSubscriptionProductCatalog(searchTerm = "") {
        const backendCatalog = await this.subscriptionPosApi.fetchSubscriptionProductCatalog(
            searchTerm,
            200,
            getCurrentCompanyId(this) || false
        );
        return Array.isArray(backendCatalog) ? backendCatalog : [];
    },

    async _fetchSubscriptionPricing(partnerId = false, productId = false, flow = "new", sourceSubscriptionId = false, pendingMoveId = false, fallback = 0, planId = false, pricingId = false, startDate = false) {
        return this.subscriptionPosApi.fetchSubscriptionPricing(
            partnerId || false,
            productId || false,
            flow || "new",
            sourceSubscriptionId || false,
            pendingMoveId || false,
            fallback || 0,
            planId || false,
            pricingId || false,
            startDate || false
        );
    },

    async _fetchSubscriptionQuote(partnerId = false, productId = false, flow = "new", sourceSubscriptionId = false, pendingMoveId = false, fallback = 0, planId = false, pricingId = false, startDate = false) {
        return this.subscriptionPosApi.fetchSubscriptionQuote(
            partnerId || false,
            productId || false,
            flow || "new",
            sourceSubscriptionId || false,
            pendingMoveId || false,
            fallback || 0,
            planId || false,
            pricingId || false,
            startDate || false
        );
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

        const tabs = document.createElement("div");
        tabs.className = "wgs-status-tabs";
        tabs.innerHTML = `
            <button type="button" class="wgs-status-tab wgs-status-tab-active" data-tab="directory">${this._escapeHtml(_t("Directorio"))}</button>
            <button type="button" class="wgs-status-tab" data-tab="access_log">${this._escapeHtml(_t("Bitacora de accesos"))}</button>
        `;

        const toolbar = document.createElement("div");
        toolbar.className = "wgs-status-toolbar";
        toolbar.innerHTML = `
            <input type="text" class="wgs-filter-search" placeholder="${_t("Buscar por cliente, paquete, telefono o email")}" />
            <select class="wgs-filter-state">
                <option value="actionable">${_t("Estado: En progreso y por renovar")}</option>
                <option value="all">${_t("Estado: Todos")}</option>
                <option value="progress">${_t("Estado: En progreso")}</option>
                <option value="renew">${_t("Estado: Por renovar")}</option>
                <option value="cancel">${_t("Estado: Cancelada / churned")}</option>
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

        const accessLogToolbar = document.createElement("div");
        accessLogToolbar.className = "wgs-access-log-toolbar-shell";

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
        const listPager = document.createElement("div");
        listPager.className = "wgs-directory-pagination";
        listPager.innerHTML = `
            <span class="wgs-directory-page-label"></span>
            <div class="wgs-directory-page-actions">
                <button type="button" class="wgs-directory-page-btn wgs-btn-page-prev">${this._escapeHtml(_t("Anterior"))}</button>
                <button type="button" class="wgs-directory-page-btn wgs-btn-page-next">${this._escapeHtml(_t("Siguiente"))}</button>
            </div>
        `;
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
        listPane.appendChild(listPager);
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

        const accessLogBody = document.createElement("div");
        accessLogBody.className = "wgs-access-log-body";

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
            if (resyncAccessCooldownTimer) {
                window.clearInterval(resyncAccessCooldownTimer);
                resyncAccessCooldownTimer = null;
            }
            overlay.remove();
        };
        closeButton.addEventListener("click", closeModal);
        footer.appendChild(closeButton);

        modal.appendChild(header);
        modal.appendChild(tabs);
        modal.appendChild(toolbar);
        modal.appendChild(accessLogToolbar);
        modal.appendChild(summary);
        modal.appendChild(body);
        modal.appendChild(accessLogBody);
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
            prevPageButton,
            nextPageButton,
            pageLabel,
            tbody,
        } = getDirectoryControls({ toolbar, table, pager: listPager });

        let filteredSnapshot = [...rows];
        let selectedPartnerId = rows[0] ? rows[0].id : false;
        let activeTab = "directory";
        let detailRequestToken = 0;
        let currentDetail = null;
        let directoryLoading = false;
        let directoryFullyLoaded = false;
        let directoryLoadError = "";
        let directorySummary = null;
        let directoryLoadToken = 0;
        let directoryPageOffset = 0;
        let directoryPageSize = 50;
        let directoryHasNextPage = false;
        let formMode = null;
        let formError = "";
        let formNotice = "";
        let catalogLoading = false;
        let productCatalog = [];
        let participantRows = [];
        let participantRowsLoading = false;
        let participantRowsLoadToken = 0;
        let participantRowsSearchTimer = null;
        let renewalForm = null;
        let upsaleForm = null;
        let participantEditForm = null;
        let newPartnerForm = null;
        let partnerPhotoForm = null;
        let partnerEditForm = null;
        let accessLogFilters = {
            ...getTodayAccessLogRange(),
            result: "all",
            deviceId: "",
        };
        let accessLogRows = [];
        let accessLogDevices = [];
        let accessLogSiteNames = [];
        let accessLogTotal = 0;
        let accessLogLoading = false;
        let accessLogError = "";
        let accessLogNotice = "";
        let accessLogOpeningDoorId = 0;
        let accessLogLoaded = false;
        let resyncAccessCooldownTimer = null;
        const resyncAccessLoadingIds = new Set();
        const resyncAccessCooldowns = new Map();
        const detailCache = new Map();
        let newSubscriptionForm = this._getDefaultNewSubscriptionForm(selectedPartnerId);
        const modalState = {
            get rows() { return rows; },
            set rows(value) { rows = Array.isArray(value) ? value : []; },
            get filteredSnapshot() { return filteredSnapshot; },
            set filteredSnapshot(value) { filteredSnapshot = Array.isArray(value) ? value : []; },
            get selectedPartnerId() { return selectedPartnerId; },
            set selectedPartnerId(value) { selectedPartnerId = value; },
            get detailRequestToken() { return detailRequestToken; },
            set detailRequestToken(value) { detailRequestToken = Number(value || 0); },
            get detailCache() { return detailCache; },
            get currentDetail() { return currentDetail; },
            set currentDetail(value) { currentDetail = value; },
            get directoryLoading() { return directoryLoading; },
            set directoryLoading(value) { directoryLoading = Boolean(value); },
            get directoryFullyLoaded() { return directoryFullyLoaded; },
            set directoryFullyLoaded(value) { directoryFullyLoaded = Boolean(value); },
            get directoryLoadError() { return directoryLoadError; },
            set directoryLoadError(value) { directoryLoadError = String(value || ""); },
            get directorySummary() { return directorySummary; },
            set directorySummary(value) { directorySummary = value && typeof value === "object" ? value : null; },
            get directoryLoadToken() { return directoryLoadToken; },
            set directoryLoadToken(value) { directoryLoadToken = Number(value || 0); },
            get directoryPageOffset() { return directoryPageOffset; },
            set directoryPageOffset(value) { directoryPageOffset = Math.max(0, Number(value || 0)); },
            get directoryPageSize() { return directoryPageSize; },
            set directoryPageSize(value) { directoryPageSize = Math.max(1, Number(value || 50)); },
            get directoryHasNextPage() { return directoryHasNextPage; },
            set directoryHasNextPage(value) { directoryHasNextPage = Boolean(value); },
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
            get participantEditForm() { return participantEditForm; },
            set participantEditForm(value) { participantEditForm = value; },
            get newPartnerForm() { return newPartnerForm; },
            set newPartnerForm(value) { newPartnerForm = value; },
            get partnerPhotoForm() { return partnerPhotoForm; },
            set partnerPhotoForm(value) { partnerPhotoForm = value; },
            get partnerEditForm() { return partnerEditForm; },
            set partnerEditForm(value) { partnerEditForm = value; },
            get newSubscriptionForm() { return newSubscriptionForm; },
            set newSubscriptionForm(value) { newSubscriptionForm = value; },
            get productCatalog() { return productCatalog; },
            set productCatalog(value) { productCatalog = value; },
            get catalogLoading() { return catalogLoading; },
            set catalogLoading(value) { catalogLoading = value; },
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

        const renderAccessLog = () => {
            accessLogToolbar.innerHTML = renderAccessLogToolbar({
                filters: accessLogFilters,
                devices: accessLogDevices,
                escapeHtml: (value) => this._escapeHtml(value),
                _t,
            });
            accessLogBody.innerHTML = renderAccessLogContent({
                rows: accessLogRows,
                loading: accessLogLoading,
                error: accessLogError,
                notice: accessLogNotice,
                devices: accessLogDevices,
                openingDoorId: accessLogOpeningDoorId,
                total: accessLogTotal,
                siteNames: accessLogSiteNames,
                escapeHtml: (value) => this._escapeHtml(value),
                formatDateTimeDisplay: (value) => this._formatDateTimeDisplay(value),
                _t,
            });
        };

        const renderActiveTabChrome = () => {
            const showDirectory = activeTab === "directory";
            toolbar.style.display = showDirectory ? "" : "none";
            summary.style.display = showDirectory ? "" : "none";
            body.style.display = showDirectory ? "" : "none";
            accessLogToolbar.style.display = showDirectory ? "none" : "";
            accessLogBody.style.display = showDirectory ? "none" : "";
            for (const button of tabs.querySelectorAll("[data-tab]")) {
                button.classList.toggle("wgs-status-tab-active", button.dataset.tab === activeTab);
            }
            if (!showDirectory) {
                renderAccessLog();
            }
        };

        const cleanupResyncAccessCooldowns = () => {
            const now = Date.now();
            for (const [subscriptionId, expiresAt] of resyncAccessCooldowns.entries()) {
                if (!expiresAt || expiresAt <= now) {
                    resyncAccessCooldowns.delete(subscriptionId);
                }
            }
        };

        const getResyncAccessState = (subscriptionId) => {
            const numericId = Number(subscriptionId || 0);
            cleanupResyncAccessCooldowns();
            const expiresAt = resyncAccessCooldowns.get(numericId) || 0;
            return {
                loading: resyncAccessLoadingIds.has(numericId),
                remainingSeconds: expiresAt > Date.now() ? Math.ceil((expiresAt - Date.now()) / 1000) : 0,
            };
        };

        const ensureResyncAccessCooldownTicker = () => {
            if (resyncAccessCooldownTimer) {
                return;
            }
            resyncAccessCooldownTimer = window.setInterval(() => {
                cleanupResyncAccessCooldowns();
                if (!resyncAccessCooldowns.size) {
                    window.clearInterval(resyncAccessCooldownTimer);
                    resyncAccessCooldownTimer = null;
                }
                if (currentDetail && activeTab === "directory") {
                    renderDetailPreservingFocus(currentDetail);
                }
            }, 1000);
        };

        const setResyncAccessLoading = (subscriptionId, loading) => {
            const numericId = Number(subscriptionId || 0);
            if (!numericId) {
                return;
            }
            if (loading) {
                resyncAccessLoadingIds.add(numericId);
            } else {
                resyncAccessLoadingIds.delete(numericId);
            }
        };

        const startResyncAccessCooldown = (subscriptionId, cooldownSeconds) => {
            const numericId = Number(subscriptionId || 0);
            const seconds = Math.max(1, Number(cooldownSeconds || 60));
            if (!numericId) {
                return;
            }
            resyncAccessCooldowns.set(numericId, Date.now() + seconds * 1000);
            ensureResyncAccessCooldownTicker();
        };

        const getDirectoryCriteria = () => ({
            stateFilter: (searchInput.value || "").trim() ? "all" : (stateSelect.value || "actionable"),
            searchTerm: searchInput.value || "",
        });

        const loadDirectoryRowsInBackground = async ({
            reset = false,
            preferredPartnerId = false,
            stateFilter = false,
            searchTerm = false,
            preserveFocus = false,
            batchSize = directoryPageSize,
            pageOffset = directoryPageOffset,
        } = {}) => {
            const criteria = {
                ...getDirectoryCriteria(),
                ...(stateFilter !== false ? { stateFilter } : {}),
                ...(searchTerm !== false ? { searchTerm } : {}),
            };
            await loadDirectoryRowsInBackgroundController(modalState, {
                overlay,
                reset,
                preferredPartnerId,
                render: preserveFocus ? renderPreservingFocus : render,
                fetchPartnerDirectoryBatch: (offset, limit) =>
                    this.subscriptionPosApi.fetchPartnerDirectoryBatch(offset, limit, criteria),
                stateFilter: criteria.stateFilter,
                searchTerm: criteria.searchTerm,
                batchSize,
                pageOffset,
                _t,
            });
        };

        const reloadDirectoryRows = async (preferredPartnerId = false) => {
            const criteria = getDirectoryCriteria();
            await reloadDirectoryRowsController(modalState, {
                overlay,
                render: renderPreservingFocus,
                fetchPartnerDirectoryBatch: (offset, limit) =>
                    this.subscriptionPosApi.fetchPartnerDirectoryBatch(offset, limit, criteria),
                stateFilter: criteria.stateFilter,
                searchTerm: criteria.searchTerm,
                batchSize: directoryPageSize,
                pageOffset: directoryPageOffset,
                _t,
            }, preferredPartnerId);
        };

        const loadAccessLog = async () => {
            accessLogLoading = true;
            accessLogError = "";
            accessLogNotice = "";
            renderActiveTabChrome();
            try {
                const result = await this.subscriptionPosApi.fetchAccessEventLog({
                    company_id: getCurrentCompanyId(this) || false,
                    from: localDateTimeInputToUtcString(accessLogFilters.from),
                    to: localDateTimeInputToUtcString(accessLogFilters.to),
                    result: accessLogFilters.result || "all",
                    device_id: accessLogFilters.deviceId || false,
                    limit: 150,
                });
                accessLogRows = Array.isArray(result && result.rows) ? result.rows : [];
                accessLogDevices = Array.isArray(result && result.devices) ? result.devices : [];
                accessLogSiteNames = Array.isArray(result && result.site_names) ? result.site_names : [];
                accessLogTotal = Number(result && result.total ? result.total : accessLogRows.length);
                accessLogLoaded = true;
            } catch (error) {
                console.error("Error al consultar bitacora de accesos POS", error);
                accessLogRows = [];
                accessLogError = (error && error.message) ? error.message : _t("No se pudo consultar la bitacora de accesos.");
            } finally {
                accessLogLoading = false;
                renderActiveTabChrome();
            }
        };

        const openAccessDoor = async (deviceId) => {
            const numericDeviceId = Number(deviceId || 0);
            if (!numericDeviceId || accessLogOpeningDoorId) {
                return;
            }
            accessLogOpeningDoorId = numericDeviceId;
            accessLogError = "";
            accessLogNotice = "";
            renderAccessLog();
            try {
                const result = await this.subscriptionPosApi.openAccessDoor(numericDeviceId, {
                    company_id: getCurrentCompanyId(this) || false,
                    door_id: 1,
                    open_time_seconds: 5,
                    reason: "subscription_access_log_button",
                });
                const deviceLabel = result && (result.device_name || result.device_serial)
                    ? (result.device_name || result.device_serial)
                    : _t("puerta seleccionada");
                accessLogNotice = _t("Comando enviado a %s.").replace("%s", deviceLabel);
            } catch (error) {
                console.error("Error al abrir puerta desde POS", error);
                accessLogError = (
                    error && error.data && (error.data.message || error.data.debug)
                ) || (error && error.message) || _t("No se pudo abrir la puerta.");
            } finally {
                accessLogOpeningDoorId = 0;
                renderAccessLog();
            }
        };

        const focusDirectoryPartner = async (partnerId) => {
            const numericPartnerId = Number(partnerId || 0);
            if (!numericPartnerId) {
                return;
            }
            const row = await this.subscriptionPosApi.fetchPartnerDirectoryRow(numericPartnerId);
            if (!row || !row.id) {
                await reloadDirectoryRows(numericPartnerId);
                await loadDetail(numericPartnerId, { force: true });
                return;
            }
            searchInput.value = "";
            stateSelect.value = row.state === "none" ? "none" : "all";
            directoryPageOffset = 0;
            selectedPartnerId = numericPartnerId;
            rows = [
                row,
                ...rows.filter((item) => Number(item && item.id ? item.id : 0) !== numericPartnerId),
            ];
            filteredSnapshot = [...rows];
            detailCache.delete(numericPartnerId);
            resetForPartnerSelection();
            formNotice = _t("Cliente creado correctamente.");
            renderPreservingFocus();
            await loadDetail(numericPartnerId, { force: true });
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
            const planKey = String(getCurrentPlanChoice(newSubscriptionForm) || "");
            return (newSubscriptionForm.plans || []).find((item) => {
                return `${Number(item.plan_id || 0)}:${Number(item.pricing_id || 0)}` === planKey;
            }) || null;
        };

        const getSelectedUpsalePlan = () => {
            const planKey = String(getCurrentPlanChoice(upsaleForm) || "");
            return (upsaleForm && Array.isArray(upsaleForm.plans) ? upsaleForm.plans : []).find((item) => {
                return `${Number(item.plan_id || 0)}:${Number(item.pricing_id || 0)}` === planKey;
            }) || null;
        };

        const openNewSubscriptionForm = async () => {
            await openNewSubscriptionFlow(modalState, {
                stopPartnerCamera,
                createNewSubscriptionForm: (partnerId) => this._getDefaultNewSubscriptionForm(partnerId),
                renderDetail,
                loadDetail,
                fetchSubscriptionProductCatalog: (searchTerm) => this._fetchSubscriptionProductCatalog(searchTerm),
                _t,
            });
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

        const openPartnerEditForm = () => {
            openPartnerEditFormState(modalState, {
                stopPartnerCamera,
                createPartnerEditForm: (detail) => this._getDefaultExistingPartnerForm(detail),
                renderDetail,
            });
        };

        const openRenewalForm = async (item) => {
            await openRenewalFlow(modalState, item, {
                stopPartnerCamera,
                renderDetail,
                fetchSubscriptionQuote: (...args) => this._fetchSubscriptionQuote(...args),
                _t,
            });
        };

        const openReenrollForm = async (item) => {
            await openReenrollFlow(modalState, item, {
                stopPartnerCamera,
                renderDetail,
                fetchSubscriptionQuote: (...args) => this._fetchSubscriptionQuote(...args),
                _t,
            });
        };

        const recalculateNewSubscriptionCharge = async (product, preferredPlan = null) => {
            await recalculateNewSubscriptionChargeFlow(modalState, product, preferredPlan, {
                renderDetail,
                fetchSubscriptionPricing: (...args) => this._fetchSubscriptionPricing(...args),
                _t,
            });
        };

        const applySelectedUpsaleProduct = async (productId) => {
            await applySelectedUpsaleProductFlow(modalState, productId, {
                renderDetail,
                fetchSubscriptionQuote: (...args) => this._fetchSubscriptionQuote(...args),
                _t,
            });
            if (upsaleForm && Number(upsaleForm.maxParticipantsTotal || 1) > 1) {
                void loadParticipantRows(upsaleForm.participantSearch || "");
            }
        };

        const updateSelectedUpsalePlan = async (planChoice) => {
            await updateSelectedUpsalePlanFlow(modalState, planChoice, {
                renderDetail,
                fetchSubscriptionQuote: (...args) => this._fetchSubscriptionQuote(...args),
                _t,
            });
        };

        const toggleUpsaleParticipantHandler = (partnerId, checked) => {
            toggleUpsaleParticipantFlow(modalState, partnerId, checked);
        };

        const openUpsaleForm = async (item) => {
            await openUpsaleFlow(modalState, item, {
                stopPartnerCamera,
                renderDetail,
                createDefaultUpsaleForm: (payload) => this._getDefaultUpsaleForm(payload),
                fetchSubscriptionProductCatalog: (searchTerm) => this._fetchSubscriptionProductCatalog(searchTerm),
                _t,
            });
            if (upsaleForm && Number(upsaleForm.maxParticipantsTotal || 1) > 1) {
                void loadParticipantRows(upsaleForm.participantSearch || "");
            }
        };

        const toggleEditedParticipantHandler = (partnerId, checked) => {
            toggleEditedParticipantFlow(modalState, partnerId, checked);
        };

        const openParticipantEditForm = async (item) => {
            await openParticipantEditFlow(modalState, item, {
                stopPartnerCamera,
                renderDetail,
                createDefaultParticipantEditForm: (payload) => this._getDefaultParticipantEditForm(payload),
            });
            if (participantEditForm && Number(participantEditForm.maxParticipantsTotal || 1) > 1) {
                void loadParticipantRows(participantEditForm.participantSearch || "");
            }
        };

        const applySelectedProduct = async (productId) => {
            await applySelectedProductFlow(modalState, productId, {
                renderDetail,
                fetchSubscriptionQuote: (...args) => this._fetchSubscriptionQuote(...args),
                _t,
            });
            if (newSubscriptionForm && Number(newSubscriptionForm.maxParticipantsTotal || 1) > 1) {
                void loadParticipantRows(newSubscriptionForm.participantSearch || "");
            }
        };

        const updateSelectedPlanHandler = async (planChoice) => {
            await updateSelectedPlanFlow(modalState, planChoice, {
                renderDetail,
                recalculateNewSubscriptionCharge,
            });
        };

        const toggleParticipantHandler = (partnerId, checked) => {
            toggleParticipantFlow(modalState, partnerId, checked);
        };

        const getParticipantSourceRows = () => {
            const byId = new Map();
            for (const row of [...participantRows, ...rows]) {
                const rowId = Number(row && row.id ? row.id : 0) || false;
                if (rowId && !byId.has(rowId)) {
                    byId.set(rowId, row);
                }
            }
            if (currentDetail && currentDetail.partner_id && !byId.has(Number(currentDetail.partner_id))) {
                byId.set(Number(currentDetail.partner_id), {
                    id: Number(currentDetail.partner_id),
                    name: currentDetail.partner_name || "",
                    email: currentDetail.email || false,
                    phone: currentDetail.phone || false,
                    image_url: currentDetail.image_url || false,
                });
            }
            return [...byId.values()];
        };

        const filterParticipantRowsByTerm = (searchTerm = "") => filterParticipantRowsFlow(
            getParticipantSourceRows(),
            searchTerm
        );

        const loadParticipantRows = async (searchTerm = "") => {
            const requestToken = Number(participantRowsLoadToken || 0) + 1;
            participantRowsLoadToken = requestToken;
            participantRowsLoading = true;
            renderDetailPreservingFocus(currentDetail);
            try {
                const normalizedSearch = String(searchTerm || "").trim();
                const result = await this.subscriptionPosApi.searchSubscriptionParticipants(
                    normalizedSearch,
                    normalizedSearch ? 300 : 3000
                );
                if (participantRowsLoadToken !== requestToken) {
                    return;
                }
                participantRows = Array.isArray(result) ? result : [];
            } catch (error) {
                console.error("Error al buscar participantes de suscripción POS", error);
            } finally {
                if (participantRowsLoadToken === requestToken) {
                    participantRowsLoading = false;
                    renderDetailPreservingFocus(currentDetail);
                }
            }
        };

        const scheduleParticipantRowsLoad = (searchTerm = "") => {
            if (participantRowsSearchTimer) {
                clearTimeout(participantRowsSearchTimer);
            }
            participantRowsSearchTimer = setTimeout(() => {
                participantRowsSearchTimer = null;
                void loadParticipantRows(searchTerm || "");
            }, 250);
        };

        const renderNewSubscriptionForm = () => {
            if (formMode !== "new") {
                return "";
            }
            const plan = getSelectedPlan();
            const pricingSnapshot = newSubscriptionForm.pricingSnapshot || {};
            const automaticEndDate = pricingSnapshot.subscription_end_date
                ? pricingSnapshot.subscription_end_date
                : (plan ? getPlanPeriodEndDate(newSubscriptionForm.startDate, plan.interval_value, plan.interval_unit) : "");
            const nextBillingDate = pricingSnapshot.next_billing_date || "";
            const firstPeriodNote = pricingSnapshot.first_period_alignment
                ? `
                    <div class="wgs-inline-notice">
                        ${this._escapeHtml(_t("Primer periodo proporcional"))}: ${this._escapeHtml(this._formatDateDisplay(pricingSnapshot.subscription_start_date || newSubscriptionForm.startDate) || "-")} - ${this._escapeHtml(this._formatDateDisplay(automaticEndDate) || "-")}
                        ${pricingSnapshot.first_period_access_start_date ? ` · ${this._escapeHtml(_t("Acceso desde"))}: ${this._escapeHtml(this._formatDateDisplay(pricingSnapshot.first_period_access_start_date) || "-")}` : ""}
                        ${nextBillingDate ? ` · ${this._escapeHtml(_t("Siguiente cobro"))}: ${this._escapeHtml(this._formatDateDisplay(nextBillingDate) || "-")}` : ""}
                    </div>
                `
                : "";
            const partnerCurp = String(currentDetail && currentDetail.curp ? currentDetail.curp : "").trim();
            const requiresCurp = Boolean(newSubscriptionForm.requiresCurp);
            const needsCurpCapture = requiresCurp && !partnerCurp;
            const snapshotCharge = buildChargeFromSnapshot(newSubscriptionForm, "charge_now");
            const resolvedDisplayAmount = getChargeDisplayAmount(snapshotCharge);
            const discountPercent = Number(
                newSubscriptionForm
                && newSubscriptionForm.authorizedDiscount
                && newSubscriptionForm.authorizedDiscount.discountPercent !== undefined
                    ? newSubscriptionForm.authorizedDiscount.discountPercent
                    : 0
            ) || 0;
            const discountedChargeDisplay = discountPercent
                ? resolvedDisplayAmount * (1 - (discountPercent / 100))
                : resolvedDisplayAmount;
            const filteredParticipants = filterParticipantRowsByTerm(newSubscriptionForm.participantSearch);
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
                const selected = value === String(getCurrentPlanChoice(newSubscriptionForm) || "") ? "selected" : "";
                const planDisplayPrice = Number(
                    item.display_price !== undefined
                        ? item.display_price
                        : (item.price || 0)
                ) || 0;
                const label = `${item.plan_name || _t("Plan recurrente")} | ${this._formatMoney(planDisplayPrice)}${item.interval_label ? ` | ${item.interval_label}` : ""}`;
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
                    ${needsCurpCapture ? `
                        <div class="wgs-inline-form-grid">
                            <label>
                                <span>${this._escapeHtml(_t("CURP"))}</span>
                                <input type="text" data-field="subscription_curp" value="${this._escapeHtml(newSubscriptionForm.curp || "")}" placeholder="${this._escapeHtml(_t("Captura la CURP del cliente"))}" />
                            </label>
                        </div>
                        <div class="wgs-inline-notice">${this._escapeHtml(_t("Este producto requiere CURP para continuar con la venta."))}</div>
                    ` : ""}
                    <div class="wgs-inline-form-meta">
                        <div><span>${this._escapeHtml(_t("Precio"))}</span><strong>${this._escapeHtml(this._formatMoney(discountedChargeDisplay))}</strong></div>
                        <div><span>${this._escapeHtml(_t("Cupo total"))}</span><strong>${this._escapeHtml(String(newSubscriptionForm.maxParticipantsTotal || 1))}</strong></div>
                        ${Number(newSubscriptionForm.maxParticipantsTotal || 1) > 1 ? `<div><span>${this._escapeHtml(_t("Participantes seleccionados"))}</span><strong>${this._escapeHtml(String((newSubscriptionForm.participantIds || []).length || 0))}</strong></div>` : ""}
                        <div><span>${this._escapeHtml(_t("Cobertura del plan"))}</span><strong>${this._escapeHtml(this._formatDateDisplay(automaticEndDate) || "-")}</strong></div>
                    </div>
                    ${firstPeriodNote}
                    ${renderDiscountAuthorizationSection({
                        form: newSubscriptionForm,
                        formError,
                        escapeHtml: (value) => this._escapeHtml(value),
                        formatMoney: (value) => this._formatMoney(value),
                        authorizeAction: "authorize-new-discount",
                        codeField: "new_discount_code",
                        pinField: "new_supervisor_pin",
                        _t,
                    })}
                    ${Number(newSubscriptionForm.maxParticipantsTotal || 1) > 1 ? `
                        <div class="wgs-inline-participants">
                            <span class="wgs-inline-section-title">${this._escapeHtml(_t("Participantes permitidos"))}</span>
                            <input type="text" class="wgs-inline-search" data-field="participant_search" placeholder="${this._escapeHtml(_t("Buscar participante"))}" value="${this._escapeHtml(newSubscriptionForm.participantSearch || "")}" />
                            ${participantRowsLoading ? `<div class="wgs-inline-loading">${this._escapeHtml(_t("Buscando participantes..."))}</div>` : ""}
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
                                <span>${this._escapeHtml(_t("CURP"))}</span>
                                <input type="text" data-field="partner_curp" value="${this._escapeHtml(newPartnerForm.curp || "")}" />
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

        const renderParticipantEditForm = (item) => {
            if (
                formMode !== "participants"
                || !participantEditForm
                || Number(participantEditForm.subscriptionId || 0) !== Number(item.subscription_id || 0)
            ) {
                return "";
            }
            const filteredParticipants = filterParticipantRowsByTerm(participantEditForm.participantSearch);
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
            const filteredParticipants = filterParticipantRowsByTerm(upsaleForm.participantSearch);
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
            detailPane.innerHTML = renderDetailContent(detail, {
                renderDetailHeader,
                renderPartnerDetailAvatar,
                renderSubscriptionCard,
                renderParticipantEditForm,
                renderRenewalForm,
                renderUpsaleForm,
                renderNewSubscriptionForm,
                getStateClass: (state) => this._getStateClass(state),
                getResyncAccessState,
                formMode,
                partnerPhotoForm,
                partnerEditForm,
                formError,
                formNotice,
                escapeHtml: (value) => this._escapeHtml(value),
                formatDateDisplay: (value) => this._formatDateDisplay(value),
                formatDateTimeDisplay: (value) => this._formatDateTimeDisplay(value),
                formatMoney: (value) => this._formatMoney(value),
                _t,
            });
            syncPartnerCameraPreview();
        };

        const renderDetailPreservingFocus = (detail) => {
            const focusState = captureFocusState(overlay);
            renderDetail(detail);
            restoreFocusState(overlay, focusState);
        };

        const loadDetail = async (partnerId, options = {}) => {
            await loadDetailController(modalState, partnerId, {
                force: Boolean(options && options.force),
                renderDetail,
                renderDetailEmpty,
                renderDetailLoading,
                fetchPartnerSubscriptionDetail: (targetPartnerId) => this._fetchPartnerSubscriptionDetail(targetPartnerId),
                _t,
            });
        };

        const render = () => {
            listFormContainer.innerHTML = renderNewPartnerForm();
            syncPartnerCameraPreview();
            renderActiveTabChrome();
            if (activeTab !== "directory") {
                return;
            }
            const query = searchInput.value || "";
            const stateFilter = query.trim() ? "all" : stateSelect.value;
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

            const counts = directorySummary || countDirectoryRows(rows);

            summary.innerHTML = renderDirectorySummary({
                counts,
                activeStateFilter: query.trim() ? "all" : stateSelect.value,
                directoryLoading,
                directoryLoadError,
                _t,
                escapeHtml: (value) => this._escapeHtml(value),
            });
            const pageStart = rows.length ? directoryPageOffset + 1 : 0;
            const pageEnd = directoryPageOffset + rows.length;
            pageLabel.textContent = rows.length
                ? _t("Socios %s-%s").replace("%s", String(pageStart)).replace("%s", String(pageEnd))
                : _t("Sin socios");
            prevPageButton.disabled = directoryLoading || directoryPageOffset <= 0;
            nextPageButton.disabled = directoryLoading || !directoryHasNextPage;

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

        const loadDirectorySummary = async () => {
            try {
                directorySummary = await this._fetchPartnerDirectorySummary();
                renderPreservingFocus();
            } catch (error) {
                console.error("Error al consultar resumen de suscripciones en POS", error);
            }
        };

        bindDirectoryRowSelection(tbody, (partnerId) => {
            selectDirectoryPartnerController(modalState, partnerId, {
                resetForPartnerSelection,
                render,
            });
        });

        summary.addEventListener("click", (event) => {
            const target = event.target.closest("[data-state-filter]");
            if (!target) {
                return;
            }
            const nextFilter = target.dataset.stateFilter || "actionable";
            if (stateSelect.value !== nextFilter) {
                stateSelect.value = nextFilter;
            }
            refreshDirectoryRowsForControls();
        });

        tabs.addEventListener("click", (event) => {
            const tabButton = event.target.closest("[data-tab]");
            if (!tabButton) {
                return;
            }
            const nextTab = tabButton.dataset.tab || "directory";
            if (activeTab === nextTab) {
                return;
            }
            activeTab = nextTab;
            render();
            if (activeTab === "access_log" && !accessLogLoaded) {
                loadAccessLog();
            }
        });

        accessLogToolbar.addEventListener("change", (event) => {
            if (event.target.classList.contains("wgs-access-log-from")) {
                accessLogFilters.from = event.target.value || "";
            } else if (event.target.classList.contains("wgs-access-log-to")) {
                accessLogFilters.to = event.target.value || "";
            } else if (event.target.classList.contains("wgs-access-log-result")) {
                accessLogFilters.result = event.target.value || "all";
            } else if (event.target.classList.contains("wgs-access-log-device")) {
                accessLogFilters.deviceId = event.target.value || "";
                accessLogNotice = "";
            }
        });

        accessLogToolbar.addEventListener("click", (event) => {
            const refreshButton = event.target.closest(".wgs-access-log-refresh");
            if (refreshButton) {
                loadAccessLog();
            }
        });

        accessLogBody.addEventListener("click", (event) => {
            const openDoorButton = event.target.closest(".wgs-access-door-open-btn");
            if (!openDoorButton) {
                return;
            }
            openAccessDoor(openDoorButton.dataset.deviceId || false);
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
                focusDirectoryPartner,
                loadDetail,
                createNewSubscriptionForm: (partnerId) => this._getDefaultNewSubscriptionForm(partnerId),
                openNewPartnerForm,
                overlayRoot: overlay,
                _t,
            }),
        };
        bindActionMap(listPane, listPaneActions);

        const getCurrentSubscriptionItem = (actionButton) =>
            getCurrentSubscriptionItemFromDetail(currentDetail, actionButton);

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
                updatePartner: (partnerId, values) => this._updatePartnerForPos(partnerId, values),
                updatePartnerPhoto: (partnerId, imageBase64) => this._updatePartnerPhotoForPos(partnerId, imageBase64),
                stopPartnerCamera,
                reloadDirectoryRows,
                focusDirectoryPartner,
                loadDetail,
                createNewSubscriptionForm: (partnerId) => this._getDefaultNewSubscriptionForm(partnerId),
                createPartnerEditForm: (detail) => this._getDefaultExistingPartnerForm(detail),
                openNewPartnerForm,
                openPartnerPhotoForm,
                openPartnerEditForm,
                overlayRoot: overlay,
                detailRoot: detailPane,
                detailCache,
                _t,
            }),
            ...buildSubscriptionInlineActionHandlers({
                state: modalState,
                clearFeedback,
                renderDetail,
                resetInlineForms,
                openRenewalForm,
                openReenrollForm,
                openUpsaleForm,
                openParticipantEditForm,
                fetchResyncAccess: (subscriptionId) => this._resyncSubscriptionAccess(subscriptionId),
                getResyncAccessState,
                setResyncAccessLoading,
                startResyncAccessCooldown,
                loadDetail,
                detailCache,
                getCurrentSubscriptionItem,
                getSelectedPlan,
                getSelectedUpsalePlan,
                getPlanPeriodEndDate,
                buildChargeBreakdown: (source, product, values) => buildChargeBreakdown(source, product, values),
                addConfiguredProductLineToOrder: (order, product, options) => addConfiguredProductLineToOrder(this, order, product, options),
                getCurrentOrder: () => getCurrentOrder(this),
                getPartnerIdFromOrder,
                getOrderLines,
                ensurePartnerLoadedInPos: (partnerId) => ensurePartnerLoadedInPos(this, partnerId, (recordId) => this.subscriptionPosApi.fetchPartnerRecord(recordId)),
                ensureProductLoadedInPos: (productId) => ensureProductLoadedInPos(this, productId, (recordId, companyId) => this.subscriptionPosApi.fetchProductRecord(recordId, companyId)),
                updatePartnerCurp: (partnerId, curp) => this._updatePartnerCurpForPos(partnerId, curp),
                setPartnerOnCurrentOrder: (partner) => setPartnerOnCurrentOrder(this, partner),
                getSubscriptionPartnerIdsFromOrder,
                saveSubscriptionParticipants: (subscriptionId, participantIds) => this._saveSubscriptionParticipants(subscriptionId, participantIds),
                validateSubscriptionProductEligibility: (partnerId, productId, flow, sourceSubscriptionId) =>
                    this._validateSubscriptionProductEligibilityForPos(partnerId, productId, flow, sourceSubscriptionId),
                authorizeSubscriptionDiscount: (partnerId, productId, flow, discountCode, supervisorPin, sourceSubscriptionId) =>
                    this._authorizeSubscriptionDiscountForPos(partnerId, productId, flow, discountCode, supervisorPin, sourceSubscriptionId),
                formatTodayISO,
                _t,
            }),
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
            await handleSubscriptionInlineFieldChange(
                { field, target },
                {
                    state: modalState,
                    clearFeedback,
                    applySelectedProduct,
                    updateSelectedPlan: updateSelectedPlanHandler,
                    applySelectedUpsaleProduct,
                    updateSelectedUpsalePlan,
                    toggleParticipant: toggleParticipantHandler,
                    toggleUpsaleParticipant: toggleUpsaleParticipantHandler,
                    toggleEditedParticipant: toggleEditedParticipantHandler,
                    formatTodayISO,
                    renderDetail,
                }
            );
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
            const shouldRender = handleSubscriptionInlineFieldInput(
                { field, target },
                { state: modalState }
            );
            if (!shouldRender && !handleDetailPartnerFieldInput({ field, target }, { state: modalState })) {
                return;
            }
            if (shouldRender) {
                renderDetailPreservingFocus(currentDetail);
                if (["participant_search", "upsale_participant_search", "edit_participant_search"].includes(field)) {
                    scheduleParticipantRowsLoad(target.value || "");
                }
            }
        });

        let directorySearchTimer = null;
        const refreshDirectoryRowsForControls = () => {
            directoryPageOffset = 0;
            loadDirectoryRowsInBackground({
                reset: true,
                preferredPartnerId: selectedPartnerId,
                preserveFocus: true,
                pageOffset: directoryPageOffset,
            });
        };

        const loadDirectoryPage = (nextOffset) => {
            directoryPageOffset = Math.max(0, Number(nextOffset || 0));
            loadDirectoryRowsInBackground({
                reset: true,
                preferredPartnerId: false,
                preserveFocus: true,
                pageOffset: directoryPageOffset,
            });
        };

        bindDirectoryToolbarEvents({
            searchInput,
            stateSelect,
            birthdaySelect,
            sortSelect,
            exportButton,
            prevPageButton,
            nextPageButton,
            onSearchInput: () => {
                renderPreservingFocus();
                if (directorySearchTimer) {
                    window.clearTimeout(directorySearchTimer);
                }
                directorySearchTimer = window.setTimeout(refreshDirectoryRowsForControls, 250);
            },
            onStateChange: refreshDirectoryRowsForControls,
            onBirthdayChange: render,
            onSortChange: render,
            onExport: () => {
                this._downloadDirectoryAsXls(filteredSnapshot);
            },
            onPrevPage: () => {
                loadDirectoryPage(directoryPageOffset - directoryPageSize);
            },
            onNextPage: () => {
                loadDirectoryPage(directoryPageOffset + directoryPageSize);
            },
        });

        render();
        loadDirectoryRowsInBackground({
            reset: !rows.length,
            preferredPartnerId: selectedPartnerId,
            stateFilter: "actionable",
            searchTerm: "",
            preserveFocus: true,
            pageOffset: 0,
            batchSize: directoryPageSize,
        }).then(() => {
            if (overlay.isConnected) {
                window.setTimeout(() => {
                    if (overlay.isConnected) {
                        loadDirectorySummary();
                    }
                }, 1200);
            }
        });
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

    _getDefaultExistingPartnerForm(detail) {
        return getDefaultExistingPartnerForm(detail);
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
            .wgs-status-tabs {
                display: flex;
                gap: 0.45rem;
                padding: 0.65rem 1.2rem 0;
                background: #f8fafc;
            }
            .wgs-status-tab {
                border: 1px solid #cbd5e1;
                background: #ffffff;
                color: #334155;
                border-radius: 0.65rem 0.65rem 0 0;
                padding: 0.55rem 0.85rem;
                font-weight: 700;
                cursor: pointer;
            }
            .wgs-status-tab-active {
                border-color: #0f766e;
                background: #0f766e;
                color: #ffffff;
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
            .wgs-access-log-toolbar input,
            .wgs-access-log-toolbar select,
            .wgs-access-log-toolbar button,
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
            .wgs-access-log-toolbar-shell {
                padding: 0.8rem 1.2rem;
                border-bottom: 1px solid #e5e7eb;
            }
            .wgs-access-log-toolbar {
                display: grid;
                grid-template-columns: repeat(4, minmax(150px, 1fr)) minmax(130px, 0.6fr);
                gap: 0.6rem;
                align-items: end;
            }
            .wgs-access-log-toolbar label {
                display: grid;
                gap: 0.25rem;
                margin: 0;
                font-size: 0.74rem;
                font-weight: 700;
                letter-spacing: 0.04em;
                text-transform: uppercase;
                color: #64748b;
            }
            .wgs-access-log-body {
                min-height: 0;
                overflow: auto;
                padding: 0.9rem 1.2rem 1.2rem;
            }
            .wgs-access-log-summary {
                display: flex;
                flex-wrap: wrap;
                gap: 0.5rem;
                margin-bottom: 0.75rem;
            }
            .wgs-access-door-panel {
                border: 1px solid #dbeafe;
                border-radius: 0.85rem;
                background: #eff6ff;
                padding: 0.75rem;
                margin-bottom: 0.85rem;
                display: grid;
                gap: 0.55rem;
            }
            .wgs-access-door-panel-title {
                color: #1e3a8a;
                font-weight: 800;
                font-size: 0.86rem;
                text-transform: uppercase;
                letter-spacing: 0.05em;
            }
            .wgs-access-door-row {
                display: grid;
                grid-template-columns: minmax(0, 1fr) minmax(110px, 0.18fr);
                gap: 0.65rem;
                align-items: center;
                border: 1px solid #bfdbfe;
                border-radius: 0.7rem;
                background: #ffffff;
                padding: 0.65rem 0.75rem;
            }
            .wgs-access-door-row strong {
                display: block;
                color: #0f172a;
                font-size: 0.9rem;
            }
            .wgs-access-door-row span,
            .wgs-access-door-empty {
                display: block;
                color: #64748b;
                font-size: 0.78rem;
                margin-top: 0.12rem;
            }
            .wgs-access-log-table-wrap {
                border: 1px solid #e5e7eb;
                border-radius: 0.75rem;
                overflow: auto;
                background: #ffffff;
            }
            .wgs-access-log-error {
                margin: 0 0 0.75rem;
                color: #9f1239;
                font-weight: 700;
            }
            .wgs-access-log-notice {
                margin: 0 0 0.75rem;
                color: #166534;
                font-weight: 700;
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
            button.wgs-summary-pill {
                cursor: pointer;
                line-height: 1.2;
            }
            button.wgs-summary-pill:hover {
                filter: brightness(0.97);
                transform: translateY(-1px);
            }
            .wgs-summary-active {
                box-shadow: 0 0 0 2px rgba(15, 118, 110, 0.16);
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
            .wgs-directory-pagination {
                padding: 0.65rem 1rem;
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 0.75rem;
                border-top: 1px solid #eef2f7;
                border-bottom: 1px solid #e5e7eb;
                background: #ffffff;
            }
            .wgs-directory-page-label {
                color: #475569;
                font-size: 0.82rem;
                font-weight: 700;
            }
            .wgs-directory-page-actions {
                display: flex;
                gap: 0.45rem;
                align-items: center;
            }
            .wgs-directory-page-btn {
                border: 1px solid #cbd5e1;
                border-radius: 0.55rem;
                background: #ffffff;
                color: #334155;
                padding: 0.45rem 0.75rem;
                font-size: 0.8rem;
                font-weight: 700;
                cursor: pointer;
            }
            .wgs-directory-page-btn:disabled {
                opacity: 0.55;
                cursor: not-allowed;
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
            .wgs-detail-inline-editor {
                margin-bottom: 0.75rem;
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
            .wgs-action-loading {
                display: inline-flex;
                align-items: center;
                justify-content: center;
                gap: 0.45rem;
            }
            .wgs-action-loading::before {
                content: "";
                width: 0.85rem;
                height: 0.85rem;
                border: 2px solid #cbd5e1;
                border-top-color: #0f766e;
                border-radius: 999px;
                animation: wgs-spin 0.8s linear infinite;
            }
            @keyframes wgs-spin {
                to { transform: rotate(360deg); }
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
            .wgs-inline-discount-card {
                border: 1px solid #dbeafe;
                border-radius: 0.75rem;
                background: #f8fbff;
                padding: 0.85rem;
            }
            .wgs-inline-note {
                font-size: 0.82rem;
                color: #64748b;
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
	                .wgs-access-log-toolbar,
	                .wgs-access-door-row,
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
