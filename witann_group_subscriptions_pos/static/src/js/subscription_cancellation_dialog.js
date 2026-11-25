/** @odoo-module **/

import { Component, useState, xml } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";

export class PackageCancellationDialog extends Component {
    static components = { Dialog };
    static props = { close: Function, getPayload: Function, subscriptionName: String, hasScheduledChanges: Boolean };
    static template = xml`
        <Dialog title="title" size="'md'">
            <p>Se cancelara el paquete <strong t-esc="props.subscriptionName"/> para todos sus participantes.</p>
            <p>No se borran ni se devuelven automaticamente pagos anteriores.</p>
            <p t-if="props.hasScheduledChanges" class="alert alert-warning">
                Tambien se cancelaran las renovaciones pagadas programadas. No se genera devolucion automatica.
            </p>
            <label class="form-label" for="wgs-cancellation-amount">Cargo total por cancelacion (impuestos incluidos)</label>
            <input id="wgs-cancellation-amount" class="form-control mb-3" type="number" min="0" step="0.01" t-model="state.amount"/>
            <label class="form-label" for="wgs-cancellation-reason">Motivo</label>
            <input id="wgs-cancellation-reason" class="form-control mb-3" maxlength="500" t-model="state.reason"/>
            <p t-if="hasCharge">El paquete sigue activo hasta que se pague el ticket del cargo.</p>
            <p t-else="">Con cargo cero, al confirmar se cancela inmediatamente sin crear un ticket.</p>
            <div t-if="state.error" class="alert alert-danger" t-esc="state.error"/>
            <t t-set-slot="footer">
                <button type="button" class="btn btn-danger" t-on-click="confirm">
                    <t t-if="hasCharge">Agregar cargo al ticket</t><t t-else="">Confirmar cancelacion sin cargo</t>
                </button>
                <button type="button" class="btn btn-secondary" t-on-click="props.close">Volver</button>
            </t>
        </Dialog>`;

    setup() { this.state = useState({ amount: "0", reason: "", error: "" }); }
    get title() { return _t("Cancelar paquete"); }
    get hasCharge() { return Number(this.state.amount) > 0; }
    confirm() {
        const amount = Number(this.state.amount);
        if (String(this.state.amount).trim() === "" || !Number.isFinite(amount) || amount < 0) {
            this.state.error = _t("Captura un cargo valido, mayor o igual a cero.");
            return;
        }
        this.props.getPayload({ amount, reason: this.state.reason });
        this.props.close();
    }
}
