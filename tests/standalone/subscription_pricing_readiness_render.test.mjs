import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const root = new URL('../../witann_group_subscriptions_pos/static/src/js/', import.meta.url);
const context = vm.createContext({
    buildChargeFromSnapshot: () => ({}), getCurrentPlanChoice: () => '',
    getDiscountedDisplayAmount: () => 0,
    renderDiscountAuthorizationSection: () => '',
    renderDomiciliationInstallmentSelector: () => '',
});
for (const file of ['subscription_quote_request.js', 'subscription_renewal_render.js', 'subscription_upsale_render.js']) {
    const source = fs.readFileSync(new URL(file, root), 'utf8')
        .replace(/^import[\s\S]*?;\s*$/gm, '')
        .replace(/^export\s*\{[\s\S]*?\};?\s*$/gm, '')
        .replace(/export function /g, 'function ');
    vm.runInContext(source, context, {filename:file});
}
for (const mode of ['renewal', 'reenroll', 'upsale']) {
    test(`${mode}: submit is disabled without a quote and enabled for a signed zero-price quote`, () => {
        const form = {subscriptionId:1, productId:2, loading:false, pricingSnapshot:null};
        const options = {item:{subscription_id:1}, formMode:mode,
            renewalForm:form, upsaleForm:form, productCatalog:[], filteredParticipants:[],
            escapeHtml:String, formatDateDisplay:String, formatMoney:String,
            getChargeDisplayAmount:() => 0, _t:value => value};
        const render = mode === 'upsale' ? context.renderUpsaleForm : context.renderRenewalForm;
        const action = `data-action="save-${mode}"`;
        assert.match(render(options), new RegExp(`${action} disabled`));
        form.pricingSnapshot = {plan_id:1, ticket_charge_now:0,
            commercial_quote:{payload:{product_id:2},signature:'server-signature'}};
        assert.doesNotMatch(render(options), new RegExp(`${action} disabled`));
        form.loading = true;
        assert.match(render(options), new RegExp(`${action} disabled`));
    });
}
