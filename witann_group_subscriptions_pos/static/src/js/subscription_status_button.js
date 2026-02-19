/** @odoo-module **/

import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { onMounted } from "@odoo/owl";

const STATUS_SUFFIX_RE = /\s\[(VIGENTE|SIN VIGENCIA|SIN PAQUETE)\]$/;

patch(ControlButtons.prototype, {
    setup() {
        super.setup(...arguments);
        this.orm = useService("orm");
        this._wgsStatusLoading = false;
        onMounted(() => {
            this._ensurePartnerStatusDecorated().catch((error) => {
                console.error("No se pudo cargar el estatus de vigencia para la lista de clientes.", error);
            });
        });
    },

    async onClickSubscriptionStatus() {
        await this._ensurePartnerStatusDecorated();
        const order = this._getCurrentOrder();
        const partner = this._getCurrentPartner(order);

        if (!partner) {
            window.alert(_t("Selecciona un cliente para consultar su vigencia de paquetes."));
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
            window.alert(_t("No se pudo consultar la vigencia en este momento."));
            console.error("Error al consultar vigencia de suscripción en POS", error);
            return;
        }

        const items = result.items || [];
        let body;

        if (!items.length) {
            body = _t("No hay paquetes de suscripción para este participante.");
        } else {
            body = items
                .map((item) => {
                    const packages = (item.package_names || []).join(", ") || item.subscription_name;
                    const periodStart = item.period_start || _t("N/D");
                    const validUntil = item.valid_until || _t("N/D");
                    return `${item.status_label}: ${packages}\nPeriodo: ${periodStart} a ${validUntil}\n${item.reason}`;
                })
                .join("\n\n");
        }

        window.alert(`${_t("Vigencia de paquetes")} - ${partner.name}\n\n${body}`);
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
            this._applyStatusToPartners(partners, pos.wgsPartnerStatusMap);
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

    _applyStatusToPartners(partners, statusMap) {
        for (const partner of partners) {
            if (!partner || !partner.id) {
                continue;
            }
            const mapRow = this._getPartnerStatusEntry(statusMap, partner.id);
            const suffix = mapRow && mapRow.short_label ? mapRow.short_label : "";
            const currentName = partner.name || partner.display_name || "";
            const baseName = partner._wgsBaseName || this._stripStatusSuffix(currentName);
            const decoratedName = suffix ? `${baseName} ${suffix}`.trim() : baseName;

            partner._wgsBaseName = baseName;
            partner.name = decoratedName;
            if ("display_name" in partner) {
                partner.display_name = decoratedName;
            }
        }
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

        const pos = this._getPos();
        if (pos && pos.models && pos.models["res.partner"] && pos.models["res.partner"].get) {
            return pos.models["res.partner"].get(partnerId) || { id: partnerId, name: _t("Cliente") };
        }

        if (pos && pos.db && pos.db.get_partner_by_id) {
            return pos.db.get_partner_by_id(partnerId) || { id: partnerId, name: _t("Cliente") };
        }

        return { id: partnerId, name: _t("Cliente") };
    },
});
