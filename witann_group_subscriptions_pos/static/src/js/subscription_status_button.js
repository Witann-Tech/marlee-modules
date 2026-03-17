/** @odoo-module **/

import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { onWillUnmount } from "@odoo/owl";

const MODAL_ID = "wgs-subscription-status-modal";
const STYLE_ID = "wgs-subscription-status-style";
const STATE_SORT_RANK = {
    progress: 0,
    renew: 1,
    paused: 2,
    draft: 3,
    cancel: 4,
    closed: 5,
    upsell: 6,
    other: 7,
    none: 8,
};

function parseISODate(value) {
    if (!value || typeof value !== "string") {
        return null;
    }
    const match = value.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!match) {
        return null;
    }
    const year = Number(match[1]);
    const month = Number(match[2]);
    const day = Number(match[3]);
    const date = new Date(Date.UTC(year, month - 1, day));
    if (
        date.getUTCFullYear() !== year
        || (date.getUTCMonth() + 1) !== month
        || date.getUTCDate() !== day
    ) {
        return null;
    }
    return date;
}

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
        let rows = [];
        try {
            rows = await this._fetchPartnerDirectoryRows();
        } catch (error) {
            this._showSimpleInfoModal(
                _t("Error al consultar suscripciones"),
                _t("No se pudo consultar la informacion en este momento.")
            );
            console.error("Error al consultar suscripciones en POS", error);
            return;
        }

        if (!rows.length) {
            this._showSimpleInfoModal(
                _t("Sin clientes"),
                _t("No se encontraron clientes disponibles para mostrar.")
            );
            return;
        }

        this._showSubscriptionsModal(rows);
    },

    async _fetchPartnerDirectoryRows() {
        const rows = [];
        const batchSize = 500;
        let offset = 0;

        while (true) {
            const batch = await this.orm.call(
                "sale.order",
                "get_partner_directory_rows_for_pos",
                [offset, batchSize]
            );
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
        return this.orm.call("sale.order", "get_partner_subscription_detail_for_pos", [partnerId]);
    },

    _showSubscriptionsModal(rows) {
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
        const birthdaySelect = toolbar.querySelector(".wgs-filter-birthday");
        const sortSelect = toolbar.querySelector(".wgs-sort");
        const exportButton = toolbar.querySelector(".wgs-btn-export");
        const tbody = table.querySelector("tbody");

        let filteredSnapshot = [...rows];
        let selectedPartnerId = rows[0] ? rows[0].id : false;
        let detailRequestToken = 0;
        const detailCache = new Map();

        const renderDetailEmpty = (title, message) => {
            detailPane.innerHTML = `
                <div class="wgs-detail-empty">
                    <strong>${this._escapeHtml(title)}</strong>
                    <p>${this._escapeHtml(message)}</p>
                </div>
            `;
        };

        const renderDetailLoading = () => {
            detailPane.innerHTML = `
                <div class="wgs-detail-empty">
                    <strong>${this._escapeHtml(_t("Cargando detalle"))}</strong>
                    <p>${this._escapeHtml(_t("Estamos consultando las suscripciones del cliente seleccionado."))}</p>
                </div>
            `;
        };

        const renderDetail = (detail) => {
            if (!detail || !detail.partner_id) {
                renderDetailEmpty(
                    _t("Sin detalle"),
                    _t("No se pudo cargar la informacion del cliente seleccionado.")
                );
                return;
            }

            const subscriptions = Array.isArray(detail.items) ? detail.items : [];
            const summaryStateClass = this._getStateClass(detail.state);
            const subscriptionsHtml = subscriptions.length
                ? subscriptions.map((item) => {
                    const stateClass = this._getStateClass(item.native_state_key);
                    const participantNames = (item.participant_names || []).length
                        ? item.participant_names.map((name) => this._escapeHtml(name)).join(", ")
                        : this._escapeHtml(_t("Sin participantes"));
                    return `
                        <div class="wgs-subscription-card">
                            <div class="wgs-subscription-card-header">
                                <div>
                                    <strong>${this._escapeHtml(item.subscription_name || "-")}</strong>
                                    <div class="wgs-subscription-card-meta">${this._escapeHtml(item.partner_role_label || "-")}</div>
                                </div>
                                <span class="wgs-state-badge ${stateClass}">${this._escapeHtml(item.native_state_label || _t("Sin estado"))}</span>
                            </div>
                            <div class="wgs-subscription-grid">
                                <div><span>${this._escapeHtml(_t("Paquete"))}</span><strong>${this._escapeHtml((item.package_names || []).join(", ") || "-")}</strong></div>
                                <div><span>${this._escapeHtml(_t("Plan"))}</span><strong>${this._escapeHtml(item.plan_name || "-")}</strong></div>
                                <div><span>${this._escapeHtml(_t("Inicio"))}</span><strong>${this._escapeHtml(this._formatDateDisplay(item.start_date) || "-")}</strong></div>
                                <div><span>${this._escapeHtml(_t("Vencimiento"))}</span><strong>${this._escapeHtml(this._formatDateDisplay(item.valid_until) || "-")}</strong></div>
                                <div><span>${this._escapeHtml(_t("Proxima fecha"))}</span><strong>${this._escapeHtml(this._formatDateDisplay(item.next_invoice_date) || "-")}</strong></div>
                                <div><span>${this._escapeHtml(_t("Participantes"))}</span><strong>${this._escapeHtml(String(item.participant_count || 0))}</strong></div>
                            </div>
                            <div class="wgs-subscription-participants">
                                <span>${this._escapeHtml(_t("Listado de participantes"))}</span>
                                <p>${participantNames}</p>
                            </div>
                            <div class="wgs-subscription-actions">
                                <button type="button" class="wgs-action-btn" disabled>${this._escapeHtml(_t("Nueva suscripcion"))}</button>
                                <button type="button" class="wgs-action-btn" disabled>${this._escapeHtml(_t("Renovar"))}</button>
                                <button type="button" class="wgs-action-btn" disabled>${this._escapeHtml(_t("Cobrar pendiente"))}</button>
                                <button type="button" class="wgs-action-btn" disabled>${this._escapeHtml(_t("Editar participantes"))}</button>
                            </div>
                        </div>
                    `;
                }).join("")
                : `
                    <div class="wgs-detail-empty wgs-detail-empty-inline">
                        <strong>${this._escapeHtml(_t("Sin suscripciones relacionadas"))}</strong>
                        <p>${this._escapeHtml(_t("Este cliente no tiene suscripciones nativas vigentes o historicas visibles para POS."))}</p>
                    </div>
                `;

            detailPane.innerHTML = `
                <div class="wgs-detail-header-card">
                    <img class="wgs-detail-avatar" src="${this._escapeHtml(detail.image_url || "")}" alt="${this._escapeHtml(detail.partner_name || "")}" loading="lazy" />
                    <div class="wgs-detail-header-text">
                        <div class="wgs-detail-title-row">
                            <h4>${this._escapeHtml(detail.partner_name || "-")}</h4>
                            <span class="wgs-state-badge ${summaryStateClass}">${this._escapeHtml(detail.state_label || _t("Sin suscripcion"))}</span>
                        </div>
                        <div class="wgs-detail-contact-grid">
                            <div><span>${this._escapeHtml(_t("Telefono"))}</span><strong>${this._escapeHtml(detail.phone || "-")}</strong></div>
                            <div><span>${this._escapeHtml(_t("Email"))}</span><strong>${this._escapeHtml(detail.email || "-")}</strong></div>
                            <div><span>${this._escapeHtml(_t("Genero"))}</span><strong>${this._escapeHtml(detail.gender || "-")}</strong></div>
                            <div><span>${this._escapeHtml(_t("Cumpleanos"))}</span><strong>${this._escapeHtml(this._formatDateDisplay(detail.birthday) || "-")}</strong></div>
                            <div><span>${this._escapeHtml(_t("Ultimo acceso"))}</span><strong>${this._escapeHtml(this._formatDateTimeDisplay(detail.last_access) || "-")}</strong></div>
                            <div><span>${this._escapeHtml(_t("Resumen"))}</span><strong>${this._escapeHtml(detail.package_label || _t("Sin suscripcion"))}</strong></div>
                        </div>
                    </div>
                </div>
                <div class="wgs-detail-actions-bar">
                    <button type="button" class="wgs-primary-action-btn" disabled>${this._escapeHtml(_t("Nueva suscripcion"))}</button>
                    <button type="button" class="wgs-secondary-action-btn" disabled>${this._escapeHtml(_t("Renovar"))}</button>
                    <button type="button" class="wgs-secondary-action-btn" disabled>${this._escapeHtml(_t("Cobrar pendiente"))}</button>
                    <button type="button" class="wgs-secondary-action-btn" disabled>${this._escapeHtml(_t("Participantes"))}</button>
                </div>
                <div class="wgs-detail-note">${this._escapeHtml(_t("Las acciones de venta, renovacion y cobro se integraran en esta misma vista en la siguiente fase."))}</div>
                <div class="wgs-detail-section">
                    <div class="wgs-detail-section-title">${this._escapeHtml(_t("Suscripciones del cliente"))}</div>
                    <div class="wgs-subscription-cards">${subscriptionsHtml}</div>
                </div>
            `;
        };

        const loadDetail = async (partnerId) => {
            if (!partnerId) {
                renderDetailEmpty(
                    _t("Selecciona un cliente"),
                    _t("Aqui veras sus suscripciones nativas, participantes y acciones disponibles.")
                );
                return;
            }
            if (detailCache.has(partnerId)) {
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
            const query = (searchInput.value || "").trim().toLowerCase();
            const stateFilter = stateSelect.value;
            const birthdayFilter = birthdaySelect.value;
            const sortMode = sortSelect.value;

            let filtered = rows.filter((row) => {
                if (stateFilter !== "all" && (row.state || "none") !== stateFilter) {
                    return false;
                }
                if (!this._matchesBirthdayFilter(row.birthday, birthdayFilter)) {
                    return false;
                }
                if (!query) {
                    return true;
                }
                const haystack = `${row.name || ""} ${row.phone || ""} ${row.email || ""} ${row.package_label || ""} ${row.plan_name || ""} ${row.state_label || ""}`.toLowerCase();
                return haystack.includes(query);
            });

            filtered = filtered.sort((a, b) => {
                if (sortMode === "name_desc") {
                    return (b.name || "").localeCompare(a.name || "", "es");
                }
                if (sortMode === "state") {
                    const diff = this._getStateRank(a.state) - this._getStateRank(b.state);
                    if (diff !== 0) {
                        return diff;
                    }
                    return (a.name || "").localeCompare(b.name || "", "es");
                }
                if (sortMode === "valid_until_asc") {
                    const av = this._toTimestamp(a.valid_until);
                    const bv = this._toTimestamp(b.valid_until);
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
                    const av = this._toTimestamp(a.valid_until);
                    const bv = this._toTimestamp(b.valid_until);
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
                if (sortMode === "birthday_asc") {
                    const av = this._birthdaySortRank(a.birthday);
                    const bv = this._birthdaySortRank(b.birthday);
                    if (av !== bv) {
                        return av - bv;
                    }
                    return (a.name || "").localeCompare(b.name || "", "es");
                }
                if (sortMode === "last_access_desc") {
                    const av = this._toTimestamp(a.last_access);
                    const bv = this._toTimestamp(b.last_access);
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

            filteredSnapshot = filtered;

            const counts = rows.reduce(
                (acc, row) => {
                    const state = row.state || "none";
                    acc.total += 1;
                    acc[state] = (acc[state] || 0) + 1;
                    if (row.birthday) {
                        acc.birthday += 1;
                    }
                    return acc;
                },
                { total: 0, birthday: 0 }
            );

            summary.innerHTML = `
                <span class="wgs-summary-pill">${_t("Total")}: ${counts.total || 0}</span>
                <span class="wgs-summary-pill wgs-summary-positive">${_t("En progreso")}: ${counts.progress || 0}</span>
                <span class="wgs-summary-pill wgs-summary-positive">${_t("Por renovar")}: ${counts.renew || 0}</span>
                <span class="wgs-summary-pill wgs-summary-warning">${_t("Pausadas")}: ${counts.paused || 0}</span>
                <span class="wgs-summary-pill wgs-summary-negative">${_t("Canceladas")}: ${counts.cancel || 0}</span>
                <span class="wgs-summary-pill wgs-summary-none">${_t("Sin suscripcion")}: ${counts.none || 0}</span>
                <span class="wgs-summary-pill">${_t("Con cumpleanos")}: ${counts.birthday || 0}</span>
                <span class="wgs-summary-pill">${_t("Mostrando")}: ${filtered.length}</span>
            `;

            if (!filtered.length) {
                tbody.innerHTML = `<tr><td colspan="7">${_t("No hay resultados para el filtro actual.")}</td></tr>`;
                selectedPartnerId = false;
                renderDetailEmpty(
                    _t("Sin resultados"),
                    _t("Ajusta los filtros para volver a cargar clientes en el directorio.")
                );
                return;
            }

            const filteredIds = filtered.map((row) => row.id);
            if (!selectedPartnerId || !filteredIds.includes(selectedPartnerId)) {
                selectedPartnerId = filtered[0].id;
            }

            tbody.innerHTML = filtered.map((row) => {
                const rowClass = row.id === selectedPartnerId ? "wgs-selected-row" : "";
                const stateClass = this._getStateClass(row.state);
                return `
                    <tr class="${rowClass}" data-partner-id="${this._escapeHtml(String(row.id))}">
                        <td><img class="wgs-partner-avatar" src="${this._escapeHtml(row.image_url || "")}" alt="${this._escapeHtml(row.name || "")}" loading="lazy" /></td>
                        <td class="wgs-cell-name">${this._escapeHtml(row.name || "-")}</td>
                        <td><span class="wgs-state-badge ${stateClass}">${this._escapeHtml(row.state_label || _t("Sin suscripcion"))}</span></td>
                        <td>${this._escapeHtml(row.package_label || "-")}</td>
                        <td>${this._escapeHtml(row.plan_name || "-")}</td>
                        <td>${this._escapeHtml(this._formatDateDisplay(row.valid_until) || "-")}</td>
                        <td>${this._escapeHtml(this._formatDateTimeDisplay(row.last_access) || "-")}</td>
                    </tr>
                `;
            }).join("");

            loadDetail(selectedPartnerId);
        };

        tbody.addEventListener("click", (event) => {
            const rowElement = event.target.closest("tr[data-partner-id]");
            if (!rowElement) {
                return;
            }
            const partnerId = Number(rowElement.dataset.partnerId || 0);
            if (!partnerId || partnerId === selectedPartnerId) {
                return;
            }
            selectedPartnerId = partnerId;
            render();
        });

        searchInput.addEventListener("input", render);
        stateSelect.addEventListener("change", render);
        birthdaySelect.addEventListener("change", render);
        sortSelect.addEventListener("change", render);
        exportButton.addEventListener("click", () => {
            this._downloadDirectoryAsXls(filteredSnapshot);
        });

        render();
    },

    _getStateRank(state) {
        return STATE_SORT_RANK[state || "other"] ?? STATE_SORT_RANK.other;
    },

    _getStateClass(state) {
        const value = state || "none";
        if (value === "progress" || value === "renew") {
            return "wgs-state-positive";
        }
        if (value === "paused" || value === "draft" || value === "upsell") {
            return "wgs-state-warning";
        }
        if (value === "cancel" || value === "closed") {
            return "wgs-state-negative";
        }
        return "wgs-state-neutral";
    },

    _toTimestamp(value) {
        if (!value) {
            return null;
        }
        const ts = Date.parse(String(value).trim());
        return Number.isNaN(ts) ? null : ts;
    },

    _birthdaySortRank(birthdayValue) {
        const parsed = parseISODate(String(birthdayValue || "").trim());
        if (!parsed) {
            return 367;
        }
        const today = new Date();
        const currentYear = today.getFullYear();
        let nextBirthday = new Date(currentYear, parsed.getUTCMonth(), parsed.getUTCDate());
        if (nextBirthday < new Date(currentYear, today.getMonth(), today.getDate())) {
            nextBirthday = new Date(currentYear + 1, parsed.getUTCMonth(), parsed.getUTCDate());
        }
        const diffMs = nextBirthday.getTime() - new Date(currentYear, today.getMonth(), today.getDate()).getTime();
        return Math.floor(diffMs / 86400000);
    },

    _matchesBirthdayFilter(birthdayValue, filterMode) {
        if (filterMode === "all") {
            return true;
        }
        const parsed = parseISODate(String(birthdayValue || "").trim());
        if (!parsed) {
            return filterMode === "missing";
        }
        if (filterMode === "missing") {
            return false;
        }

        const today = new Date();
        const todayMonth = today.getMonth() + 1;
        const todayDay = today.getDate();
        const birthMonth = parsed.getUTCMonth() + 1;
        const birthDay = parsed.getUTCDate();

        if (filterMode === "today") {
            return birthMonth === todayMonth && birthDay === todayDay;
        }
        if (filterMode === "this_month") {
            return birthMonth === todayMonth;
        }
        if (filterMode === "next_7") {
            return this._birthdaySortRank(birthdayValue) <= 7;
        }
        return true;
    },

    _formatDateDisplay(value) {
        if (!value) {
            return "";
        }
        const parsed = parseISODate(String(value).slice(0, 10));
        if (!parsed) {
            return String(value);
        }
        const date = new Date(parsed.getUTCFullYear(), parsed.getUTCMonth(), parsed.getUTCDate());
        return date.toLocaleDateString("es-MX", {
            day: "2-digit",
            month: "short",
            year: "numeric",
        });
    },

    _formatDateTimeDisplay(value) {
        if (!value) {
            return "";
        }
        const ts = this._toTimestamp(value);
        if (ts === null) {
            return String(value);
        }
        return new Date(ts).toLocaleString("es-MX", {
            day: "2-digit",
            month: "short",
            year: "numeric",
            hour: "2-digit",
            minute: "2-digit",
        });
    },

    _downloadDirectoryAsXls(rows) {
        const dataRows = Array.isArray(rows) ? rows : [];
        const filenameDate = new Date().toISOString().slice(0, 10);
        const filename = `suscripciones_pos_${filenameDate}.xls`;

        const tableRows = dataRows.map((row) => `
            <tr>
                <td>${this._escapeHtml(row.name || "-")}</td>
                <td>${this._escapeHtml(row.state_label || _t("Sin suscripcion"))}</td>
                <td>${this._escapeHtml(row.package_label || "-")}</td>
                <td>${this._escapeHtml(row.plan_name || "-")}</td>
                <td>${this._escapeHtml(this._formatDateDisplay(row.start_date) || "-")}</td>
                <td>${this._escapeHtml(this._formatDateDisplay(row.valid_until) || "-")}</td>
                <td>${this._escapeHtml(row.gender || "-")}</td>
                <td>${this._escapeHtml(this._formatDateDisplay(row.birthday) || "-")}</td>
                <td>${this._escapeHtml(this._formatDateTimeDisplay(row.last_access) || "-")}</td>
                <td>${this._escapeHtml(row.phone || "-")}</td>
                <td>${this._escapeHtml(row.email || "-")}</td>
            </tr>
        `).join("");

        const html = `
            <html>
                <head>
                    <meta charset="UTF-8" />
                    <style>
                        table { border-collapse: collapse; font-family: Arial, sans-serif; font-size: 12px; }
                        th, td { border: 1px solid #999; padding: 6px; text-align: left; }
                        th { background: #e9eef5; }
                    </style>
                </head>
                <body>
                    <table>
                        <thead>
                            <tr>
                                <th>${this._escapeHtml(_t("Cliente"))}</th>
                                <th>${this._escapeHtml(_t("Estado"))}</th>
                                <th>${this._escapeHtml(_t("Paquete"))}</th>
                                <th>${this._escapeHtml(_t("Plan"))}</th>
                                <th>${this._escapeHtml(_t("Inicio"))}</th>
                                <th>${this._escapeHtml(_t("Vencimiento"))}</th>
                                <th>${this._escapeHtml(_t("Genero"))}</th>
                                <th>${this._escapeHtml(_t("Cumpleanos"))}</th>
                                <th>${this._escapeHtml(_t("Ultimo acceso"))}</th>
                                <th>${this._escapeHtml(_t("Telefono"))}</th>
                                <th>${this._escapeHtml(_t("Email"))}</th>
                            </tr>
                        </thead>
                        <tbody>${tableRows}</tbody>
                    </table>
                </body>
            </html>
        `;

        const blob = new Blob([`\uFEFF${html}`], { type: "application/vnd.ms-excel;charset=utf-8;" });
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = filename;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        setTimeout(() => URL.revokeObjectURL(url), 500);
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
            <div class="wgs-status-modal-body"><p class="wgs-simple-message">${this._escapeHtml(message)}</p></div>
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
            .wgs-status-toolbar button {
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
                overflow: auto;
                color: #1f2937;
            }
            .wgs-subscription-layout {
                display: grid;
                grid-template-columns: minmax(620px, 1.2fr) minmax(380px, 0.8fr);
                min-height: 60vh;
            }
            .wgs-subscription-list-pane {
                border-right: 1px solid #e5e7eb;
                overflow: auto;
            }
            .wgs-subscription-detail-pane {
                overflow: auto;
                background: #f8fafc;
                padding: 1rem;
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
            .wgs-detail-avatar {
                width: 72px;
                height: 72px;
                border-radius: 16px;
                object-fit: cover;
                background: #e2e8f0;
                border: 1px solid #d1d5db;
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
            .wgs-subscription-grid div {
                display: flex;
                flex-direction: column;
                gap: 0.18rem;
            }
            .wgs-detail-contact-grid span,
            .wgs-subscription-grid span,
            .wgs-subscription-participants span {
                font-size: 0.72rem;
                text-transform: uppercase;
                letter-spacing: 0.04em;
                color: #64748b;
                font-weight: 700;
            }
            .wgs-detail-contact-grid strong,
            .wgs-subscription-grid strong {
                color: #0f172a;
                font-size: 0.9rem;
            }
            .wgs-detail-actions-bar {
                display: grid;
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 0.55rem;
                margin-bottom: 0.65rem;
            }
            .wgs-primary-action-btn,
            .wgs-secondary-action-btn,
            .wgs-action-btn {
                border-radius: 0.65rem;
                padding: 0.65rem 0.8rem;
                font-weight: 700;
                font-size: 0.84rem;
                border: 1px solid #cbd5e1;
                background: #ffffff;
                color: #334155;
            }
            .wgs-primary-action-btn:disabled,
            .wgs-secondary-action-btn:disabled,
            .wgs-action-btn:disabled {
                opacity: 0.7;
                cursor: not-allowed;
            }
            .wgs-primary-action-btn {
                background: #0f766e;
                color: #ffffff;
                border-color: #0f766e;
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
            .wgs-subscription-card {
                background: #ffffff;
                border: 1px solid #e5e7eb;
                border-radius: 0.85rem;
                padding: 0.9rem;
                display: flex;
                flex-direction: column;
                gap: 0.75rem;
            }
            .wgs-subscription-card-header {
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
            .wgs-subscription-grid {
                display: grid;
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 0.7rem;
            }
            .wgs-subscription-participants p {
                margin: 0.25rem 0 0;
                color: #0f172a;
                line-height: 1.45;
            }
            .wgs-subscription-actions {
                display: grid;
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 0.5rem;
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
                }
                .wgs-subscription-list-pane {
                    border-right: none;
                    border-bottom: 1px solid #e5e7eb;
                    max-height: 42vh;
                }
            }
            @media (max-width: 900px) {
                .wgs-status-toolbar {
                    grid-template-columns: 1fr;
                }
                .wgs-detail-contact-grid,
                .wgs-subscription-grid,
                .wgs-detail-actions-bar,
                .wgs-subscription-actions {
                    grid-template-columns: 1fr;
                }
                .wgs-detail-header-card {
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
