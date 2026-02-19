/** @odoo-module **/

import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { onWillUnmount } from "@odoo/owl";

const MODAL_ID = "wgs-subscription-status-modal";
const STYLE_ID = "wgs-subscription-status-style";

patch(ControlButtons.prototype, {
    setup() {
        super.setup(...arguments);
        this.orm = useService("orm");
        this._ensureStatusStyles();

        onWillUnmount(() => {
            const modal = document.getElementById(MODAL_ID);
            if (modal) {
                modal.remove();
            }
        });
    },

    async onClickSubscriptionStatus() {
        const partners = this._getAllPartners();
        if (!partners.length) {
            this._showSimpleInfoModal(
                _t("Sin clientes cargados"),
                _t("No hay clientes disponibles en esta sesión de Punto de Venta.")
            );
            return;
        }

        const partnerIds = partners.map((partner) => partner.id).filter(Boolean);
        let statusMap = {};
        try {
            statusMap = await this._fetchPartnerStatusMap(partnerIds);
        } catch (error) {
            this._showSimpleInfoModal(
                _t("Error al consultar vigencia"),
                _t("No se pudo consultar la vigencia en este momento.")
            );
            console.error("Error al consultar vigencia global en POS", error);
            return;
        }

        const rows = partners.map((partner) => {
            const status = this._getPartnerStatusEntry(statusMap, partner.id) || {};
            return {
                id: partner.id,
                name: partner._wgsBaseName || partner.name || partner.display_name || _t("Sin nombre"),
                email: partner.email || "",
                phone: partner.phone || partner.mobile || "",
                state: status.state || "none",
                valid_until: status.valid_until || "",
            };
        });

        this._showDirectoryModal(rows);
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

    _showDirectoryModal(rows) {
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
        title.textContent = _t("Directorio de Vigencia de Clientes");
        header.appendChild(title);

        const toolbar = document.createElement("div");
        toolbar.className = "wgs-status-toolbar";
        toolbar.innerHTML = `
            <input type="text" class="wgs-filter-search" placeholder="${_t("Buscar por nombre, teléfono o email")}" />
            <select class="wgs-filter-state">
                <option value="all">${_t("Todos")}</option>
                <option value="valid">${_t("Vigentes")}</option>
                <option value="expired">${_t("Sin vigencia")}</option>
                <option value="none">${_t("Sin paquete")}</option>
            </select>
            <select class="wgs-sort">
                <option value="name_asc">${_t("Nombre A-Z")}</option>
                <option value="name_desc">${_t("Nombre Z-A")}</option>
                <option value="state">${_t("Estado")}</option>
                <option value="valid_until_asc">${_t("Vigencia cercana")}</option>
                <option value="valid_until_desc">${_t("Vigencia lejana")}</option>
            </select>
        `;

        const summary = document.createElement("div");
        summary.className = "wgs-status-summary";

        const body = document.createElement("div");
        body.className = "wgs-status-modal-body";

        const table = document.createElement("table");
        table.className = "wgs-status-table";
        table.innerHTML = `
            <thead>
                <tr>
                    <th>${_t("Cliente")}</th>
                    <th>${_t("Estado")}</th>
                    <th>${_t("Vigente hasta")}</th>
                    <th>${_t("Teléfono")}</th>
                    <th>${_t("Email")}</th>
                </tr>
            </thead>
            <tbody></tbody>
        `;
        body.appendChild(table);

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

        document.body.appendChild(overlay);

        const searchInput = toolbar.querySelector(".wgs-filter-search");
        const stateSelect = toolbar.querySelector(".wgs-filter-state");
        const sortSelect = toolbar.querySelector(".wgs-sort");
        const tbody = table.querySelector("tbody");

        const stateLabel = {
            valid: _t("Vigente"),
            expired: _t("Sin vigencia"),
            none: _t("Sin paquete"),
        };

        const stateRank = {
            valid: 0,
            expired: 1,
            none: 2,
        };

        const parseDate = (value) => {
            if (!value) {
                return null;
            }
            const ts = Date.parse(value);
            return Number.isNaN(ts) ? null : ts;
        };

        const render = () => {
            const query = (searchInput.value || "").trim().toLowerCase();
            const stateFilter = stateSelect.value;
            const sortMode = sortSelect.value;

            let filtered = rows.filter((row) => {
                if (stateFilter !== "all" && row.state !== stateFilter) {
                    return false;
                }
                if (!query) {
                    return true;
                }
                const haystack = `${row.name} ${row.phone} ${row.email}`.toLowerCase();
                return haystack.includes(query);
            });

            filtered = filtered.sort((a, b) => {
                if (sortMode === "name_desc") {
                    return (b.name || "").localeCompare(a.name || "", "es");
                }
                if (sortMode === "state") {
                    const diff = (stateRank[a.state] ?? 9) - (stateRank[b.state] ?? 9);
                    if (diff !== 0) {
                        return diff;
                    }
                    return (a.name || "").localeCompare(b.name || "", "es");
                }
                if (sortMode === "valid_until_asc") {
                    const av = parseDate(a.valid_until);
                    const bv = parseDate(b.valid_until);
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
                    const av = parseDate(a.valid_until);
                    const bv = parseDate(b.valid_until);
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

            const counts = rows.reduce(
                (acc, row) => {
                    acc.total += 1;
                    if (row.state === "valid") acc.valid += 1;
                    else if (row.state === "expired") acc.expired += 1;
                    else acc.none += 1;
                    return acc;
                },
                { total: 0, valid: 0, expired: 0, none: 0 }
            );

            summary.innerHTML = `
                <span class="wgs-summary-pill">${_t("Total")}: ${counts.total}</span>
                <span class="wgs-summary-pill wgs-summary-valid">${_t("Vigentes")}: ${counts.valid}</span>
                <span class="wgs-summary-pill wgs-summary-expired">${_t("Sin vigencia")}: ${counts.expired}</span>
                <span class="wgs-summary-pill wgs-summary-none">${_t("Sin paquete")}: ${counts.none}</span>
                <span class="wgs-summary-pill">${_t("Mostrando")}: ${filtered.length}</span>
            `;

            if (!filtered.length) {
                tbody.innerHTML = `<tr><td colspan="5">${_t("No hay resultados para el filtro actual.")}</td></tr>`;
                return;
            }

            tbody.innerHTML = filtered
                .map((row) => {
                    const badgeClass = row.state === "valid" ? "wgs-badge-valid" : row.state === "expired" ? "wgs-badge-expired" : "wgs-badge-none";
                    const badgeLabel = stateLabel[row.state] || stateLabel.none;
                    const untilLabel = row.valid_until || _t("N/D");
                    return `
                        <tr>
                            <td>${this._escapeHtml(row.name || "")}</td>
                            <td><span class="wgs-status-badge ${badgeClass}">${this._escapeHtml(badgeLabel)}</span></td>
                            <td>${this._escapeHtml(untilLabel)}</td>
                            <td>${this._escapeHtml(row.phone || "-")}</td>
                            <td>${this._escapeHtml(row.email || "-")}</td>
                        </tr>
                    `;
                })
                .join("");
        };

        searchInput.addEventListener("input", render);
        stateSelect.addEventListener("change", render);
        sortSelect.addEventListener("change", render);
        render();
    },

    _showSimpleInfoModal(title, message) {
        const previous = document.getElementById(MODAL_ID);
        if (previous) {
            previous.remove();
        }

        const overlay = document.createElement("div");
        overlay.id = MODAL_ID;
        overlay.className = "wgs-status-modal-overlay";

        const modal = document.createElement("div");
        modal.className = "wgs-status-modal";

        modal.innerHTML = `
            <div class="wgs-status-modal-header"><h3>${this._escapeHtml(title)}</h3></div>
            <div class="wgs-status-modal-body"><p>${this._escapeHtml(message)}</p></div>
            <div class="wgs-status-modal-footer">
                <button type="button" class="wgs-status-close-btn">${this._escapeHtml(_t("Cerrar"))}</button>
            </div>
        `;

        const closeModal = () => overlay.remove();
        modal.querySelector(".wgs-status-close-btn").addEventListener("click", closeModal);
        overlay.addEventListener("click", (event) => {
            if (event.target === overlay) {
                closeModal();
            }
        });

        overlay.appendChild(modal);
        document.body.appendChild(overlay);
    },

    _escapeHtml(value) {
        return String(value)
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#39;");
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
                max-height: 92vh;
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
            .wgs-status-toolbar {
                padding: 0.8rem 1.2rem;
                display: grid;
                grid-template-columns: minmax(260px, 1fr) 180px 210px;
                gap: 0.6rem;
                border-bottom: 1px solid #e5e7eb;
            }
            .wgs-status-toolbar input,
            .wgs-status-toolbar select {
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
            .wgs-summary-valid {
                border-color: #8ad9b5;
                color: #0f7b4b;
                background: #daf5e8;
            }
            .wgs-summary-expired {
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
                padding: 0.55rem 0.6rem;
                text-align: left;
                vertical-align: top;
                font-size: 0.86rem;
            }
            .wgs-status-table th {
                position: sticky;
                top: 0;
                z-index: 1;
                background: #f8fafc;
                font-size: 0.76rem;
                color: #374151;
                text-transform: uppercase;
                letter-spacing: 0.03em;
            }
            .wgs-status-badge {
                border-radius: 999px;
                padding: 0.12rem 0.5rem;
                font-size: 0.72rem;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.03em;
                white-space: nowrap;
            }
            .wgs-badge-valid {
                background: #daf5e8;
                color: #0f7b4b;
                border: 1px solid #8ad9b5;
            }
            .wgs-badge-expired {
                background: #ffe4e6;
                color: #9f1239;
                border: 1px solid #fda4af;
            }
            .wgs-badge-none {
                background: #f1f5f9;
                color: #475569;
                border: 1px solid #cbd5e1;
            }
            @media (max-width: 900px) {
                .wgs-status-toolbar {
                    grid-template-columns: 1fr;
                }
            }
        `;
        document.head.appendChild(style);
    },

    _getPartnerStatusEntry(statusMap, partnerId) {
        return statusMap[partnerId] || statusMap[String(partnerId)] || null;
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

    _getPos() {
        if (this.pos) {
            return this.pos;
        }
        if (this.env && this.env.pos) {
            return this.env.pos;
        }
        return null;
    },
});
