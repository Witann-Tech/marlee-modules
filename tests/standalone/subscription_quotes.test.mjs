import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../witann_group_subscriptions_pos/static/src/js');
const context = vm.createContext({ console, canOpenNewSubscription: () => true });
for (const file of ['subscription_quote_request.js', 'subscription_pricing_snapshot.js', 'subscription_flow_controllers.js', 'subscription_inline_form_handlers.js']) {
    const source = fs.readFileSync(path.join(root, file), 'utf8')
        .replace(/^import[\s\S]*?;\s*$/gm, '')
        .replace(/^export\s*\{[\s\S]*?\};?\s*$/gm, '')
        .replace(/export function /g, 'function ');
    vm.runInContext(source, context, { filename: file });
}
function deferred() {
    let resolve, reject;
    const promise = new Promise((a, b) => { resolve=a; reject=b; });
    return {promise, resolve, reject};
}
const quote = (id) => ({pricing: {product_id:id, plan_id:id, recurring_price:id * 100,
    ticket_charge_now:id * 100, commercial_quote:{payload:{product_id:id, company_id:9, partner_id:7}}}});
test('fixed cutoff and signed calendar survive the ticket JSON roundtrip', () => {
    const charge = {monthly_cutoff_day:31, subscription_start_date:'2027-03-01',
        subscription_end_date:'2027-03-31', next_billing_date:'2027-04-01'};
    charge.commercial_quote = {payload:{pricing:{...charge}}, signature:'server-signature'};
    const snapshot = JSON.parse(JSON.stringify(context.buildPricingSnapshotFromCharge(charge)));
    assert.equal(snapshot.monthly_cutoff_day, 31);
    assert.equal(snapshot.subscription_end_date, '2027-03-31');
    assert.deepEqual(snapshot.commercial_quote, charge.commercial_quote);
    assert.equal(context.buildPricingSnapshotFromCharge({}).monthly_cutoff_day, 0);
});

test('initial proportional end is separate from the domiciliation forced-term end', () => {
    const snapshot = context.buildPricingSnapshotFromCharge({
        first_period_end_date: '2026-10-31', subscription_end_date: '2027-09-30',
    });
    const persisted = JSON.parse(JSON.stringify(snapshot));
    assert.equal(persisted.first_period_end_date, '2026-10-31');
    assert.equal(persisted.subscription_end_date, '2027-09-30');
});

test('purchased calendar inputs survive restoration from the signed quote', () => {
    const terms = {version:1, mode:'term', start:'2027-03-01', interval:1, unit:'month',
        cutoff:31, previous_end:'2027-02-28', aligned:false};
    const signed = {payload:{pricing:{period_contract:terms}}, signature:'server-signature'};
    const snapshot = JSON.parse(JSON.stringify(context.buildPricingSnapshotFromCharge({commercial_quote:signed})));
    assert.deepEqual(snapshot.period_contract, terms);
    assert.deepEqual(snapshot.commercial_quote, signed);
});
function stateFor(mode) {
    const state = {formMode:mode, selectedPartnerId:7, currentDetail:{}, productCatalog:[
        {id:1, name:'Daily'}, {id:2, name:'Monthly'},
    ]};
    const key = mode === 'new' ? 'newSubscriptionForm' : mode === 'upsale' ? 'upsaleForm' : 'renewalForm';
    state[key] = {holderPartnerId:7, subscriptionId:8, sourceProductId:1, participantIds:[7]};
    return [state,key];
}
test('renewing into domiciliation preserves its initial installment quote', async () => {
    const [state, key] = stateFor('renewal');
    const response = quote(2);
    response.pricing.domiciliation = {is_domiciliation:true, selection_mode:'initial',
        selected_installment_sequences:[1,12], term_months:12,
        installments:[{sequence:1, amount:35}, {sequence:12, amount:70}]};
    response.pricing.ticket_charge_now = 105;
    response.pricing.subscription_start_date = '2026-10-16';
    response.pricing.subscription_end_date = '2027-09-30';
    await context.applySelectedRenewalProduct(state, 2, {
        _t:value => value, renderDetail() {}, fetchSubscriptionQuote:async () => response,
    });
    assert.equal(state[key].packageChangeSelected, true);
    assert.equal(state[key].pricingSnapshot.domiciliation.selection_mode, 'initial');
    assert.deepEqual(JSON.parse(JSON.stringify(state[key].pricingSnapshot.domiciliation.selected_installment_sequences)), [1,12]);
    assert.equal(state[key].pricingSnapshot.ticket_charge_now, 105);
});
test('pricing readiness rejects absent/unsigned/loading quotes but accepts a signed zero price', () => {
    assert.equal(context.isPricingReady(null), false);
    assert.equal(context.isPricingReady({loading:false, pricingSnapshot:null}), false);
    assert.equal(context.isPricingReady({pricingSnapshot:quote(1).pricing}), false);
    const form = {loading:false, pricingSnapshot:{...quote(1).pricing, ticket_charge_now:0,
        commercial_quote:{payload:{product_id:1}, signature:'server-signature'}}};
    assert.equal(context.isPricingReady(form), true);
    form.loading = true;
    assert.equal(context.isPricingReady(form), false);
});
for (const [mode, action] of [['new','save-new'], ['renewal','save-renewal'],
    ['reenroll','save-reenroll'], ['upsale','save-upsale']]) {
    test(`${mode}: failed quote cannot assign a customer or add a line through the action handler`, async () => {
        const [state, key] = stateFor(mode);
        state[key].loading = false;
        state[key].pricingSnapshot = null;
        let renders = 0;
        const handlers = context.buildSubscriptionInlineActionHandlers({state,
            renderDetail() { renders++; }, _t: value => value,
            getCurrentOrder() { assert.fail('No ticket access before valid quote'); },
        });
        await handlers[action]({});
        assert.equal(renders, 1);
        assert.match(state.formError, /cotizacion valida/);
        assert.equal(state.subscriptionTicketPending, undefined);
    });
}
for (const [mode, handler, field] of [
    ['new', 'applySelectedProduct', 'start_date'],
    ['reenroll', 'applySelectedReenrollProduct', 'reenroll_start_date'],
]) {
    test(`${mode}: date changed during first product quote replaces the in-flight calendar`, async () => {
        const [state, key] = stateFor(mode);
        state[key].startDate = '2026-11-03';
        const requests = [];
        const deps = {
            renderDetail() {}, _t: value => value,
            fetchSubscriptionQuote(...args) {
                const response = deferred();
                requests.push({args, response});
                return response.promise;
            },
        };
        const apply = id => context[handler](state, id, deps);
        const first = apply(1);
        const changed = context.handleSubscriptionInlineFieldChange({field, target:{value:'2026-11-01'}}, {
            state, clearFeedback() {}, renderDetail() {},
            applySelectedProduct: apply, applySelectedReenrollProduct: apply,
            formatTodayISO: () => '2026-11-03',
        });
        assert.equal(requests.length, 2);
        assert.equal(requests[0].args[8], '2026-11-03');
        assert.equal(requests[1].args[8], '2026-11-01');
        requests[0].response.resolve({pricing:{...quote(1).pricing, subscription_start_date:'2026-11-03'}});
        await first;
        assert.equal(state[key].pricingSnapshot, null);
        assert.equal(state[key].loading, true);
        requests[1].response.resolve({pricing:{...quote(1).pricing, subscription_start_date:'2026-11-01'}});
        await changed;
        assert.equal(state[key].startDate, '2026-11-01');
        assert.equal(state[key].pricingSnapshot.subscription_start_date, '2026-11-01');
        assert.equal(state[key].loading, false);
    });
}
for (const [mode, handler] of [
    ['new','applySelectedProduct'], ['renewal','applySelectedRenewalProduct'],
    ['reenroll','applySelectedReenrollProduct'], ['upsale','applySelectedUpsaleProduct'],
]) {
    test(`${mode}: response A cannot overwrite B`, async () => {
        const [state,key] = stateFor(mode);
        const a=deferred(), b=deferred();
        const deps={_t:(s)=>s,renderDetail:()=>{},fetchSubscriptionQuote:(_, id)=>id===1?a.promise:b.promise};
        const pendingA=context[handler](state,1,deps);
        const pendingB=context[handler](state,2,deps);
        b.resolve(quote(2)); await pendingB;
        a.resolve(quote(1)); await pendingA;
        assert.equal(state[key].productId,2);
        assert.equal(state[key].pricingSnapshot.plan_id,2);
        assert.equal(state[key].pricingSnapshot.recurring_price,200);
        assert.equal(state[key].pricingSnapshot.commercial_quote.payload.product_id,2);
    });
    test(`${mode}: closed form does not get resurrected by a failed request`, async () => {
        const [state,key] = stateFor(mode), a=deferred();
        const request=context[handler](state,1,{_t:(s)=>s,renderDetail:()=>{},fetchSubscriptionQuote:()=>a.promise});
        state[key]=null; state.formMode=null;
        a.reject(new Error('late failure')); await request;
        assert.equal(state[key],null);
        assert.equal(state.formError,undefined);
    });
}
test('quote context includes identity and permits a real zero price', () => {
    const result=context.buildPricingSnapshotFromCharge({recurring_price:0,ticket_charge_now:0,
        commercial_quote:{payload:{product_id:1,partner_id:2,company_id:10}}});
    assert.equal(result.ticket_charge_now,0);
    assert.equal(result.product_id,1);
    assert.equal(result.partner_id,2);
    assert.equal(result.company_id,10);
});

test('next renewal defaults to the last scheduled package without changing the current one', async () => {
    const [state] = stateFor('renewal');
    let quotedProduct;
    await context.openRenewalForm(state, {
        subscription_id:8, holder_partner_id:7, renewal_product_id:1,
        participant_ids:[7], max_participants_total:1,
        renewal_defaults:{product_id:2, product_name:'Pair', plan_id:2,
            participant_ids:[7,9], max_participants_total:2},
    }, {
        stopPartnerCamera:()=>{}, renderDetail:()=>{}, formatTodayISO:()=> '2026-09-15', _t:(s)=>s,
        fetchSubscriptionQuote:async (_, product) => { quotedProduct=product; return quote(product); },
    });
    assert.equal(quotedProduct,2);
    assert.equal(state.renewalForm.sourceProductId,1);
    assert.equal(state.renewalForm.packageChangeSelected,true);
    assert.deepEqual(Array.from(state.renewalForm.participantIds),[7,9]);
    assert.equal(state.renewalForm.maxParticipantsTotal,2);
    await context.applySelectedRenewalProduct(state,1,{
        renderDetail:()=>{}, fetchSubscriptionQuote:async (_, product)=>quote(product), _t:(s)=>s,
    });
    assert.deepEqual(Array.from(state.renewalForm.participantIds),[7]);
});

test('ticket preflight selection becomes stale when participants or customer change', () => {
    const [state,key] = stateFor('renewal');
    state[key].pricingSnapshot = quote(2).pricing;
    const selection = context.capturePricingSelection(state,key);
    assert.equal(selection.isCurrent(),true);
    state[key].participantIds.push(99);
    assert.equal(selection.isCurrent(),false);
    const otherSelection = context.capturePricingSelection(state,key);
    state.selectedPartnerId = 100;
    assert.equal(otherSelection.isCurrent(),false);
});

const ticketContext = vm.createContext({console});
vm.runInContext(fs.readFileSync(path.join(root,'subscription_ticket.js'),'utf8').replace(/^export /gm,''),ticketContext);
test('native persisted line metadata survives reload and stays bound to its UUID', () => {
    const a = {uuid:'line-a', product_id:{id:1}, qty:1,
        wgs_operation_config_json:JSON.stringify({flow:'renewal',plan_id:12,pricing_snapshot:quote(1).pricing})};
    const b = {uuid:'line-b', product_id:{id:1}, qty:1,
        wgs_operation_config_json:JSON.stringify({flow:'reenroll',plan_id:24,pricing_snapshot:quote(2).pricing})};
    const result = ticketContext.collectSubscriptionConfigsFromOrder({lines:[a,b]});
    assert.equal(result[0].line_uuid,'line-a');
    assert.equal(result[0].plan_id,12);
    assert.equal(result[1].line_uuid,'line-b');
    assert.equal(result[1].plan_id,24);
    assert.equal(result[1].pricing_snapshot.commercial_quote.payload.product_id,2);
});
test('refund metadata is not mistaken for a positive subscription purchase', () => {
    const refund = {uuid:'refund',qty:-1,product_id:{id:1},price_unit:100,discount:0,
        refunded_orderline_id:{id:77},wgs_operation_config_json:JSON.stringify({flow:'new'})};
    const order = {lines:[refund]};
    assert.equal(ticketContext.collectSubscriptionConfigsFromOrder(order).length,0);
    assert.equal(ticketContext.collectMembershipRefundsFromOrder(order)[0].original_line_id,77);
});
