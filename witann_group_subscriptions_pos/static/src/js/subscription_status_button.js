/** @odoo-module **/

import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { onWillUnmount } from "@odoo/owl";

const MODAL_ID = "wgs-subscription-status-modal";
const STYLE_ID = "wgs-subscription-status-style";

function getPos(component) {
    if (component.pos) {
        return component.pos;
    }
    if (component.env && component.env.pos) {
        return component.env.pos;
    }
    return null;
}

function getAllPartners(component) {
    const pos = getPos(component);
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
}

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
        const partners = getAllPartners(this);
        if (!partners.length) {
            this._showSimpleInfoModal(
                _t("Sin clientes cargados"),
                _t("No hay clientes disponibles en esta sesion de Punto de Venta.")
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
                _t("No se pudo consultar la informacion en este momento.")
            );
            console.error("Error al consultar control de acceso en POS", error);
            return;
        }

        const rows = partners.map((partner) => {
            const status = this._getPartnerStatusEntry(statusMap, partner.id) || {};
            return {
                id: partner.id,
                name: status.partner_name || partner.name || partner.display_name || _t("Sin nombre"),
                email: status.email || partner.email || "",
                phone: status.phone || partner.phone || partner.mobile || "",
                state: status.state || "none",
                payment_status: status.payment_status || "none",
                payment_status_label: status.payment_status_label || "",
                package_label: status.package_label || "",
                plan_name: status.plan_name || "",
                start_date: status.start_date || "",
                valid_until: status.valid_until || "",
                birthday: status.birthday || "",
                gender: status.gender || "",
                last_access: status.last_access || "",
                image_url: status.image_url || `/web/image/res.partner/${partner.id}/image_128`,
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
        modal.className = "wgs-status-modal wgs-directory-modal";

        const header = document.createElement("div");
        header.className = "wgs-status-modal-header";
        header.innerHTML = `
            <h3>${this._escapeHtml(_t("Directorio de Control de Acceso"))}</h3>
            <p class="wgs-subtitle">${this._escapeHtml(_t("Listado general de titulares y participantes, con vigencia y datos clave."))}</p>
        `;

        const toolbar = document.createElement("div");
        toolbar.className = "wgs-status-toolbar";
        toolbar.innerHTML = `
            <input type="text" class="wgs-filter-search" placeholder="${_t("Buscar por cliente, paquete, telefono o email")}" />
            <select class="wgs-filter-state">
                <option value="all">${_t("Estado: Todos")}</option>
                <option value="valid">${_t("Estado: Vigentes")}</option>
                <option value="expired">${_t("Estado: Sin vigencia")}</option>
                <option value="none">${_t("Estado: Sin paquete")}</option>
            </select>
            <select class="wgs-filter-payment">
                <option value="all">${_t("Cobro: Todos")}</option>
                <option value="window">${_t("Cobro: Ventana de pago")}</option>
                <option value="overdue">${_t("Cobro: Vencidos")}</option>
                <option value="up_to_date">${_t("Cobro: Al corriente")}</option>
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
                <option value="payment_status">${_t("Orden: Cobro recurrente")}</option>
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

        const table = document.createElement("table");
        table.className = "wgs-status-table";
        table.innerHTML = `
            <thead>
                <tr>
                    <th>${_t("Foto")}</th>
                    <th>${_t("Cliente")}</th>
                    <th>${_t("Estado")}</th>
                    <th>${_t("Paquete")}</th>
                    <th>${_t("Plan")}</th>
                    <th>${_t("Inicio")}</th>
                    <th>${_t("Vencimiento")}</th>
                    <th>${_t("Cobro")}</th>
                    <th>${_t("Genero")}</th>
                    <th>${_t("Cumpleanos")}</th>
                    <th>${_t("Ultimo acceso")}</th>
                    <th>${_t("Telefono")}</th>
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
        const paymentSelect = toolbar.querySelector(".wgs-filter-payment");
        const birthdaySelect = toolbar.querySelector(".wgs-filter-birthday");
        const sortSelect = toolbar.querySelector(".wgs-sort");
        const exportButton = toolbar.querySelector(".wgs-btn-export");
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
        const paymentStatusLabel = {
            up_to_date: _t("Al corriente"),
            window: _t("Ventana de pago"),
            overdue: _t("Pago vencido"),
            future: _t("Inicio futuro"),
            inactive: _t("Inactiva"),
            unknown: _t("Sin proxima fecha"),
            none: _t("Sin ciclo"),
        };
        const paymentStatusRank = {
            window: 0,
            overdue: 1,
            up_to_date: 2,
            future: 3,
            inactive: 4,
            unknown: 5,
            none: 6,
        };

        let filteredSnapshot = [...rows];

        const render = () => {
            const query = (searchInput.value || "").trim().toLowerCase();
            const stateFilter = stateSelect.value;
            const paymentFilter = paymentSelect.value;
            const birthdayFilter = birthdaySelect.value;
            const sortMode = sortSelect.value;

            let filtered = rows.filter((row) => {
                if (stateFilter !== "all" && row.state !== stateFilter) {
                    return false;
                }
                if (paymentFilter !== "all" && (row.payment_status || "none") !== paymentFilter) {
                    return false;
                }
                if (!this._matchesBirthdayFilter(row.birthday, birthdayFilter)) {
                    return false;
                }
                if (!query) {
                    return true;
                }
                const haystack = `${row.name || ""} ${row.phone || ""} ${row.email || ""} ${row.package_label || ""} ${row.plan_name || ""}`.toLowerCase();
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
                if (sortMode === "payment_status") {
                    const diff = (paymentStatusRank[a.payment_status] ?? 99) - (paymentStatusRank[b.payment_status] ?? 99);
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
                    acc.total += 1;
                    if (row.state === "valid") acc.valid += 1;
                    else if (row.state === "expired") acc.expired += 1;
                    else acc.none += 1;
                    if (row.payment_status === "window") acc.window += 1;
                    if (row.payment_status === "overdue") acc.overdue += 1;
                    if (row.birthday) acc.birthday += 1;
                    return acc;
                },
                { total: 0, valid: 0, expired: 0, none: 0, window: 0, overdue: 0, birthday: 0 }
            );

            summary.innerHTML = `
                <span class="wgs-summary-pill">${_t("Total")}: ${counts.total}</span>
                <span class="wgs-summary-pill wgs-summary-valid">${_t("Vigentes")}: ${counts.valid}</span>
                <span class="wgs-summary-pill wgs-summary-expired">${_t("Sin vigencia")}: ${counts.expired}</span>
                <span class="wgs-summary-pill wgs-summary-window">${_t("Ventana de pago")}: ${counts.window}</span>
                <span class="wgs-summary-pill wgs-summary-overdue">${_t("Vencidos de pago")}: ${counts.overdue}</span>
                <span class="wgs-summary-pill wgs-summary-none">${_t("Sin paquete")}: ${counts.none}</span>
                <span class="wgs-summary-pill">${_t("Con cumpleanos")}: ${counts.birthday}</span>
                <span class="wgs-summary-pill">${_t("Mostrando")}: ${filtered.length}</span>
            `;

            if (!filtered.length) {
                tbody.innerHTML = `<tr><td colspan="13">${_t("No hay resultados para el filtro actual.")}</td></tr>`;
                return;
            }

            tbody.innerHTML = filtered.map((row) => {
                const stateClass = row.state === "valid"
                    ? "wgs-state-valid"
                    : row.state === "expired"
                        ? "wgs-state-expired"
                        : "wgs-state-none";
                const paymentStatus = row.payment_status || "none";
                const paymentLabel = row.payment_status_label || paymentStatusLabel[paymentStatus] || paymentStatusLabel.none;
                const paymentClass = `wgs-payment-${this._escapeHtml(paymentStatus)}`;
                return `
                    <tr>
                        <td>
                            <img class="wgs-partner-avatar" src="${this._escapeHtml(row.image_url || "")}" alt="${this._escapeHtml(row.name || "")}" loading="lazy" />
                        </td>
                        <td class="wgs-cell-name">${this._escapeHtml(row.name || "-")}</td>
                        <td><span class="${stateClass}">${this._escapeHtml(stateLabel[row.state] || stateLabel.none)}</span></td>
                        <td>${this._escapeHtml(row.package_label || "-")}</td>
                        <td>${this._escapeHtml(row.plan_name || "-")}</td>
                        <td>${this._escapeHtml(this._formatDateDisplay(row.start_date) || "-")}</td>
                        <td>${this._escapeHtml(this._formatDateDisplay(row.valid_until) || "-")}</td>
                        <td><span class="wgs-payment-badge ${paymentClass}">${this._escapeHtml(paymentLabel)}</span></td>
                        <td>${this._escapeHtml(row.gender || "-")}</td>
                        <td>${this._escapeHtml(this._formatDateDisplay(row.birthday) || "-")}</td>
                        <td>${this._escapeHtml(this._formatDateTimeDisplay(row.last_access) || "-")}</td>
                        <td>${this._escapeHtml(row.phone || "-")}</td>
                        <td>${this._escapeHtml(row.email || "-")}</td>
                    </tr>
                `;
            }).join("");
        };

        searchInput.addEventListener("input", render);
        stateSelect.addEventListener("change", render);
        paymentSelect.addEventListener("change", render);
        birthdaySelect.addEventListener("change", render);
        sortSelect.addEventListener("change", render);
        exportButton.addEventListener("click", () => {
            this._downloadDirectoryAsXls(filteredSnapshot);
        });
        render();
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
        const filename = `directorio_control_acceso_${filenameDate}.xls`;

        const tableRows = dataRows.map((row) => `
            <tr>
                <td>${this._escapeHtml(row.name || "-")}</td>
                <td>${this._escapeHtml(row.state === "valid" ? _t("Vigente") : row.state === "expired" ? _t("Sin vigencia") : _t("Sin paquete"))}</td>
                <td>${this._escapeHtml(row.package_label || "-")}</td>
                <td>${this._escapeHtml(row.plan_name || "-")}</td>
                <td>${this._escapeHtml(this._formatDateDisplay(row.start_date) || "-")}</td>
                <td>${this._escapeHtml(this._formatDateDisplay(row.valid_until) || "-")}</td>
                <td>${this._escapeHtml(row.payment_status_label || "-")}</td>
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
                                <th>${this._escapeHtml(_t("Cobro"))}</th>
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
                width: min(1500px, 99vw);
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
                grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
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
            .wgs-summary-window {
                border-color: #facc15;
                color: #92400e;
                background: #fef3c7;
            }
            .wgs-summary-overdue {
                border-color: #fca5a5;
                color: #991b1b;
                background: #fee2e2;
            }
            .wgs-status-modal-body {
                padding: 0;
                overflow: auto;
                color: #1f2937;
            }
            .wgs-simple-message {
                padding: 1rem 1.2rem;
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
                padding: 0.55rem 0.6rem;
                text-align: left;
                vertical-align: middle;
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
                font-weight: 600;
                color: #0f172a;
                min-width: 180px;
            }
            .wgs-state-valid {
                color: #0f7b4b;
                font-weight: 700;
            }
            .wgs-state-expired {
                color: #9f1239;
                font-weight: 700;
            }
            .wgs-state-none {
                color: #475569;
                font-weight: 700;
            }
            .wgs-payment-badge {
                display: inline-block;
                border-radius: 999px;
                padding: 0.15rem 0.45rem;
                font-size: 0.74rem;
                font-weight: 700;
                border: 1px solid #d1d5db;
                background: #f8fafc;
                color: #374151;
                white-space: nowrap;
            }
            .wgs-payment-window {
                border-color: #facc15;
                background: #fef3c7;
                color: #92400e;
            }
            .wgs-payment-overdue {
                border-color: #fda4af;
                background: #ffe4e6;
                color: #9f1239;
            }
            .wgs-payment-up_to_date {
                border-color: #8ad9b5;
                background: #daf5e8;
                color: #0f7b4b;
            }
            .wgs-payment-future,
            .wgs-payment-unknown,
            .wgs-payment-inactive,
            .wgs-payment-none {
                border-color: #cbd5e1;
                background: #f1f5f9;
                color: #475569;
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
});
