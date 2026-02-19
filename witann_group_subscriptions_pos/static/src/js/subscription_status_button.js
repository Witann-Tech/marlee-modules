/** @odoo-module **/

import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { onMounted, onPatched, onWillUnmount } from "@odoo/owl";

const STATUS_SUFFIX_RE = /\s\[(VIGENTE|SIN VIGENCIA|SIN PAQUETE)\]$/;
const MODAL_ID = "wgs-subscription-status-modal";
const STYLE_ID = "wgs-subscription-status-style";
const BADGE_CLASS = "wgs-subscription-badge";

patch(ControlButtons.prototype, {
    setup() {
        super.setup(...arguments);
        this.orm = useService("orm");
        this._wgsStatusLoading = false;
        this._wgsStatusObserver = null;
        this._wgsRenderTimer = null;
        this._wgsLastPartnerId = null;

        this._ensureStatusStyles();

        onMounted(() => {
            this._startStatusObserver();
            this._ensurePartnerStatusDecorated().catch((error) => {
                console.error("No se pudo cargar estatus de vigencia para clientes POS.", error);
            });
            this._refreshCurrentPartnerStatus().catch((error) => {
                console.error("No se pudo refrescar vigencia del cliente actual.", error);
            });
        });

        onPatched(() => {
            this._scheduleBadgeRender();
            this._refreshCurrentPartnerStatus().catch((error) => {
                console.error("No se pudo refrescar vigencia al cambiar cliente.", error);
            });
        });

        onWillUnmount(() => {
            this._stopStatusObserver();
            if (this._wgsRenderTimer) {
                clearTimeout(this._wgsRenderTimer);
                this._wgsRenderTimer = null;
            }
        });
    },

    async onClickSubscriptionStatus() {
        await this._refreshCurrentPartnerStatus();

        const order = this._getCurrentOrder();
        const partner = this._getCurrentPartner(order);

        if (!partner) {
            this._showSimpleInfoModal(
                _t("Cliente no seleccionado"),
                _t("Selecciona un cliente para consultar su vigencia de paquetes.")
            );
            return;
        }

        let result;
        try {
            result = await this.orm.call(
                "sale.order",
                "get_partner_subscription_status_for_pos",
                [partner.id]
            );
        } catch (error) {
            this._showSimpleInfoModal(
                _t("Error al consultar vigencia"),
                _t("No se pudo consultar la vigencia en este momento.")
            );
            console.error("Error al consultar vigencia de suscripción en POS", error);
            return;
        }

        this._showSubscriptionStatusModal(partner, result.items || []);
    },

    async _refreshCurrentPartnerStatus() {
        const order = this._getCurrentOrder();
        const partner = this._getCurrentPartner(order);
        const partnerId = partner && partner.id ? partner.id : null;

        if (!partnerId) {
            this._wgsLastPartnerId = null;
            return;
        }

        const pos = this._getPos();
        if (!pos) {
            return;
        }

        pos.wgsPartnerStatusMap = pos.wgsPartnerStatusMap || {};
        const existing = this._getPartnerStatusEntry(pos.wgsPartnerStatusMap, partnerId);
        if (partnerId === this._wgsLastPartnerId && existing) {
            return;
        }

        this._wgsLastPartnerId = partnerId;

        const partialMap = await this._fetchPartnerStatusMap([partnerId]);
        Object.assign(pos.wgsPartnerStatusMap, partialMap || {});

        this._applyStatusToPartners(this._getAllPartners());
        this._scheduleBadgeRender();
    },

    async _ensurePartnerStatusDecorated(force = false) {
        const pos = this._getPos();
        if (!pos) {
            return;
        }
        if (this._wgsStatusLoading) {
            return;
        }
        if (!force && pos.wgsPartnerStatusLoaded) {
            this._applyStatusToPartners(this._getAllPartners());
            this._scheduleBadgeRender();
            return;
        }

        const partners = this._getAllPartners();
        const partnerIds = partners.map((partner) => partner.id).filter(Boolean);
        if (!partnerIds.length) {
            return;
        }

        this._wgsStatusLoading = true;
        try {
            const statusMap = await this._fetchPartnerStatusMap(partnerIds);
            pos.wgsPartnerStatusMap = statusMap || {};
            pos.wgsPartnerStatusLoaded = true;
            this._applyStatusToPartners(partners);
            this._scheduleBadgeRender();
        } catch (error) {
            console.error("Error al cargar estatus de vigencia para clientes POS.", error);
        } finally {
            this._wgsStatusLoading = false;
        }
    },

    async _fetchPartnerStatusMap(partnerIds) {
        const statusMap = {};
        const chunkSize = 500;

        for (let index = 0; index < partnerIds.length; index += chunkSize) {
            const chunk = partnerIds.slice(index, index + chunkSize);
            const partialMap = await this.orm.call(
                "sale.order",
                "get_partner_subscription_status_map_for_pos",
                [chunk]
            );
            Object.assign(statusMap, partialMap || {});
        }

        return statusMap;
    },

    _applyStatusToPartners(partners) {
        for (const partner of partners) {
            if (!partner) {
                continue;
            }
            const currentName = partner.name || partner.display_name || "";
            const baseName = partner._wgsBaseName || this._stripStatusSuffix(currentName);
            partner._wgsBaseName = baseName;

            if (partner.name !== baseName) {
                partner.name = baseName;
            }
            if ("display_name" in partner && partner.display_name !== baseName) {
                partner.display_name = baseName;
            }
        }
    },

    _startStatusObserver() {
        if (this._wgsStatusObserver) {
            return;
        }

        this._wgsStatusObserver = new MutationObserver(() => {
            this._scheduleBadgeRender();
        });

        this._wgsStatusObserver.observe(document.body, {
            childList: true,
            subtree: true,
        });
    },

    _stopStatusObserver() {
        if (this._wgsStatusObserver) {
            this._wgsStatusObserver.disconnect();
            this._wgsStatusObserver = null;
        }
    },

    _scheduleBadgeRender() {
        if (this._wgsRenderTimer) {
            clearTimeout(this._wgsRenderTimer);
        }
        this._wgsRenderTimer = setTimeout(() => {
            this._wgsRenderTimer = null;
            this._renderPartnerStatusBadges();
        }, 80);
    },

    _renderPartnerStatusBadges() {
        const statusMap = this._getStatusMap();
        if (!statusMap || !Object.keys(statusMap).length) {
            return;
        }

        const rows = this._getPartnerRowsInDom();
        for (const row of rows) {
            const partnerId = this._extractPartnerIdFromRow(row);
            if (!partnerId) {
                continue;
            }

            const status = this._getPartnerStatusEntry(statusMap, partnerId);
            const statusState = status && status.state ? status.state : "none";

            const existingBadge = row.querySelector(`.${BADGE_CLASS}`);
            if (statusState === "none") {
                if (existingBadge) {
                    existingBadge.remove();
                }
                continue;
            }

            const target = this._findRowNameTarget(row);
            if (!target) {
                continue;
            }

            const badge = existingBadge || document.createElement("span");
            badge.className = `${BADGE_CLASS} ${statusState === "valid" ? "wgs-badge-valid" : "wgs-badge-expired"}`;
            badge.textContent = statusState === "valid" ? _t("Vigente") : _t("Sin vigencia");

            if (!existingBadge) {
                target.appendChild(badge);
            }
        }
    },

    _getPartnerRowsInDom() {
        const selectors = [
            ".partner-list .partner-line",
            ".partner-list .partner",
            ".client-list .partner-line",
            ".client-list .client-line",
            ".popup .partner-line",
            ".partner-list-contents .partner-line",
            ".partnerlist-screen .partner-line",
            ".partner-line",
        ];

        for (const selector of selectors) {
            const found = Array.from(document.querySelectorAll(selector));
            if (found.length) {
                return found;
            }
        }

        return [];
    },

    _extractPartnerIdFromRow(row) {
        const attrCandidates = [
            row.getAttribute("data-partner-id"),
            row.getAttribute("data-res-id"),
            row.getAttribute("data-id"),
            row.dataset && row.dataset.partnerId,
            row.dataset && row.dataset.resId,
            row.dataset && row.dataset.id,
        ];

        for (const value of attrCandidates) {
            const parsed = this._parsePositiveInt(value);
            if (parsed && this._getPartnerById(parsed)) {
                return parsed;
            }
        }

        const nested = row.querySelector("[data-partner-id],[data-res-id],[data-id]");
        if (nested) {
            const nestedCandidates = [
                nested.getAttribute("data-partner-id"),
                nested.getAttribute("data-res-id"),
                nested.getAttribute("data-id"),
                nested.dataset && nested.dataset.partnerId,
                nested.dataset && nested.dataset.resId,
                nested.dataset && nested.dataset.id,
            ];
            for (const value of nestedCandidates) {
                const parsed = this._parsePositiveInt(value);
                if (parsed && this._getPartnerById(parsed)) {
                    return parsed;
                }
            }
        }

        return null;
    },

    _findRowNameTarget(row) {
        const candidates = [
            row.querySelector(".partner-name"),
            row.querySelector(".name"),
            row.querySelector(".fw-bolder"),
            row.querySelector("strong"),
            row.querySelector("h5"),
            row.querySelector("h6"),
            row.firstElementChild,
        ].filter(Boolean);

        if (!candidates.length) {
            return null;
        }

        const target = candidates[0];
        if (!target.classList.contains("wgs-name-target")) {
            target.classList.add("wgs-name-target");
        }
        return target;
    },

    _parsePositiveInt(value) {
        if (value === undefined || value === null || value === "") {
            return null;
        }
        const parsed = Number.parseInt(value, 10);
        return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
    },

    _showSimpleInfoModal(title, message) {
        this._showSubscriptionStatusModal({ name: title }, [{
            status_label: "",
            package_names: [],
            period_start: false,
            valid_until: false,
            reason: message,
            is_valid: false,
            _simple: true,
        }]);
    },

    _showSubscriptionStatusModal(partner, items) {
        const previous = document.getElementById(MODAL_ID);
        if (previous) {
            previous.remove();
        }

        const overlay = document.createElement("div");
        overlay.id = MODAL_ID;
        overlay.className = "wgs-status-modal-overlay";

        const modal = document.createElement("div");
        modal.className = "wgs-status-modal";

        const header = document.createElement("div");
        header.className = "wgs-status-modal-header";
        const title = document.createElement("h3");
        title.textContent = `${_t("Vigencia de paquetes")} - ${partner && partner.name ? partner.name : _t("Cliente")}`;
        header.appendChild(title);

        const body = document.createElement("div");
        body.className = "wgs-status-modal-body";

        if (!items.length) {
            const emptyMessage = document.createElement("p");
            emptyMessage.textContent = _t("No hay paquetes de suscripción para este participante.");
            body.appendChild(emptyMessage);
        } else if (items.length === 1 && items[0]._simple) {
            const simpleMessage = document.createElement("p");
            simpleMessage.textContent = items[0].reason;
            body.appendChild(simpleMessage);
        } else {
            const table = document.createElement("table");
            table.className = "wgs-status-table";

            const thead = document.createElement("thead");
            thead.innerHTML = `
                <tr>
                    <th>${_t("Estado")}</th>
                    <th>${_t("Paquete")}</th>
                    <th>${_t("Periodo")}</th>
                    <th>${_t("Vigente hasta")}</th>
                    <th>${_t("Detalle")}</th>
                </tr>
            `;
            table.appendChild(thead);

            const tbody = document.createElement("tbody");
            for (const item of items) {
                const row = document.createElement("tr");

                const statusCell = document.createElement("td");
                const statusBadge = document.createElement("span");
                statusBadge.className = item.is_valid ? "wgs-badge-valid" : "wgs-badge-expired";
                statusBadge.textContent = item.status_label || (item.is_valid ? _t("Vigente") : _t("Sin vigencia"));
                statusCell.appendChild(statusBadge);

                const packageCell = document.createElement("td");
                packageCell.textContent = (item.package_names || []).join(", ") || item.subscription_name || "-";

                const periodCell = document.createElement("td");
                const periodStart = item.period_start || _t("N/D");
                const validUntil = item.valid_until || _t("N/D");
                periodCell.textContent = `${periodStart} -> ${validUntil}`;

                const untilCell = document.createElement("td");
                untilCell.textContent = item.valid_until || _t("N/D");

                const detailCell = document.createElement("td");
                detailCell.textContent = item.reason || "";

                row.appendChild(statusCell);
                row.appendChild(packageCell);
                row.appendChild(periodCell);
                row.appendChild(untilCell);
                row.appendChild(detailCell);
                tbody.appendChild(row);
            }
            table.appendChild(tbody);
            body.appendChild(table);
        }

        const footer = document.createElement("div");
        footer.className = "wgs-status-modal-footer";
        const closeButton = document.createElement("button");
        closeButton.type = "button";
        closeButton.className = "wgs-status-close-btn";
        closeButton.textContent = _t("Cerrar");

        const closeModal = () => overlay.remove();
        closeButton.addEventListener("click", closeModal);

        footer.appendChild(closeButton);

        modal.appendChild(header);
        modal.appendChild(body);
        modal.appendChild(footer);
        overlay.appendChild(modal);

        overlay.addEventListener("click", (event) => {
            if (event.target === overlay) {
                closeModal();
            }
        });

        document.body.appendChild(overlay);
    },

    _ensureStatusStyles() {
        if (document.getElementById(STYLE_ID)) {
            return;
        }

        const style = document.createElement("style");
        style.id = STYLE_ID;
        style.textContent = `
            .wgs-name-target {
                display: inline-flex;
                align-items: center;
                gap: 0.4rem;
                flex-wrap: wrap;
            }
            .${BADGE_CLASS} {
                font-size: 0.72rem;
                font-weight: 700;
                border-radius: 999px;
                padding: 0.12rem 0.5rem;
                text-transform: uppercase;
                letter-spacing: 0.03em;
                white-space: nowrap;
            }
            .wgs-badge-valid {
                background: #daf5e8;
                color: #0f7b4b;
                border: 1px solid #8ad9b5;
                border-radius: 999px;
                padding: 0.12rem 0.5rem;
                font-size: 0.72rem;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.03em;
                white-space: nowrap;
            }
            .wgs-badge-expired {
                background: #ffe4e6;
                color: #9f1239;
                border: 1px solid #fda4af;
                border-radius: 999px;
                padding: 0.12rem 0.5rem;
                font-size: 0.72rem;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.03em;
                white-space: nowrap;
            }
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
                width: min(980px, 96vw);
                max-height: 90vh;
                overflow: hidden;
                background: #ffffff;
                border-radius: 0.75rem;
                box-shadow: 0 20px 50px rgba(0, 0, 0, 0.3);
                display: flex;
                flex-direction: column;
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
            .wgs-status-modal-body {
                padding: 1rem 1.2rem;
                overflow: auto;
                color: #1f2937;
            }
            .wgs-status-modal-footer {
                padding: 0.8rem 1.2rem;
                border-top: 1px solid #e5e7eb;
                display: flex;
                justify-content: flex-end;
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
            .wgs-status-table {
                width: 100%;
                border-collapse: collapse;
            }
            .wgs-status-table th,
            .wgs-status-table td {
                border-bottom: 1px solid #e5e7eb;
                padding: 0.55rem 0.45rem;
                text-align: left;
                vertical-align: top;
                font-size: 0.88rem;
            }
            .wgs-status-table th {
                font-size: 0.8rem;
                color: #374151;
                text-transform: uppercase;
                letter-spacing: 0.03em;
            }
        `;
        document.head.appendChild(style);
    },

    _getStatusMap() {
        const pos = this._getPos();
        return pos ? (pos.wgsPartnerStatusMap || {}) : {};
    },

    _getPartnerStatusEntry(statusMap, partnerId) {
        return statusMap[partnerId] || statusMap[String(partnerId)] || null;
    },

    _stripStatusSuffix(name) {
        return (name || "").replace(STATUS_SUFFIX_RE, "").trim();
    },

    _getAllPartners() {
        const pos = this._getPos();
        if (!pos) {
            return [];
        }

        if (pos.models && pos.models["res.partner"]) {
            const partnerModel = pos.models["res.partner"];
            if (typeof partnerModel.getAll === "function") {
                return partnerModel.getAll();
            }
            if (Array.isArray(partnerModel.records)) {
                return partnerModel.records;
            }
        }

        if (pos.db) {
            if (typeof pos.db.get_partners_sorted === "function") {
                return pos.db.get_partners_sorted(100000) || [];
            }
            if (pos.db.partner_by_id) {
                return Object.values(pos.db.partner_by_id);
            }
        }

        return [];
    },

    _getPartnerById(partnerId) {
        const pos = this._getPos();
        if (!pos || !partnerId) {
            return null;
        }

        if (pos.models && pos.models["res.partner"] && pos.models["res.partner"].get) {
            const partner = pos.models["res.partner"].get(partnerId);
            if (partner) {
                return partner;
            }
        }

        if (pos.db && pos.db.get_partner_by_id) {
            return pos.db.get_partner_by_id(partnerId);
        }

        return null;
    },

    _getPos() {
        if (this.pos) {
            return this.pos;
        }
        if (this.env && this.env.pos) {
            return this.env.pos;
        }
        return null;
    },

    _getCurrentOrder() {
        const pos = this._getPos();
        if (this.currentOrder) {
            return this.currentOrder;
        }
        if (this.props && this.props.order) {
            return this.props.order;
        }
        if (pos && pos.get_order) {
            return pos.get_order();
        }
        return null;
    },

    _getCurrentPartner(order) {
        if (this.props && this.props.partner && this.props.partner.id) {
            return this.props.partner;
        }

        if (!order) {
            return null;
        }

        if (typeof order.get_partner === "function") {
            const partner = order.get_partner();
            if (partner) {
                return partner;
            }
        }

        if (order.partner && order.partner.id) {
            return order.partner;
        }

        const partnerField = order.partner_id;
        let partnerId = null;

        if (Array.isArray(partnerField) && partnerField.length) {
            partnerId = partnerField[0];
        } else if (typeof partnerField === "number") {
            partnerId = partnerField;
        } else if (partnerField && typeof partnerField === "object" && partnerField.id) {
            return partnerField;
        }

        if (!partnerId) {
            return null;
        }

        return this._getPartnerById(partnerId) || { id: partnerId, name: _t("Cliente") };
    },
});
