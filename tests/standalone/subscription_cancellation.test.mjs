import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const root = new URL('../../witann_group_subscriptions_pos/static/src/js/', import.meta.url);
function load(context, file) {
    const code = fs.readFileSync(new URL(file, root), 'utf8')
        .replace(/^import[\s\S]*?;\s*$/gm, '')
        .replace(/^export\s*\{[\s\S]*?\};?\s*$/gm, '')
        .replace(/export (async function|function|class) /g, '$1 ');
    vm.runInContext(code, context, {filename: file});
}

function fixture({amount = 25, reply = true} = {}) {
    const calls = [];
    const source = {pos: {session: {id: 7}}};
    const order = {fiscal_position_id: {id: 3}};
    const control = {order, current: true, configs: []};
    const context = vm.createContext({
        getCurrentOrder: () => control.order, getPos: () => source.pos,
        collectSubscriptionConfigsFromOrder: () => control.configs,
        resolveSubscriptionOrderPartner: async (_source, _order, configs) => calls.push(['partner', configs[0].partner_id]),
        ensureProductLoadedInPos: async () => ({id: 90}),
        addConfiguredProductLineToOrder: async (...args) => {calls.push(['line', args[3]]); return {line:{id: 1, priceIncl: amount, delete:()=>calls.push(['removed'])}};},
    });
    load(context, 'subscription_cancellation_controller.js');
    const quote = {product_id: 90, amount_total: amount, ticket_charge_now: amount, partner_id: 8, fiscal_position_id: 3,
        cancellation_quote: {payload: {partner_id: 8}}};
    const options = {
        api: {
            preparePackageCancellation: async (...args) => {calls.push(['quote', ...args]);return quote;},
            cancelPackageWithoutCharge: async () => {calls.push(['zero']);return {ok:true};},
        },
        showDialog: async () => reply ? {amount, reason:'QA'} : undefined,
        isCurrent: () => control.current,
        onCancelled: async () => calls.push(['cancelled']), onFeeAdded: async () => calls.push(['added']),
    };
    const run = () => context.cancelPackageFromPos(source, {can_cancel: true, subscription_id: 9}, options);
    return {calls, control, options, run, context, quote};
}

test('positive cancellation adds a locked fee but never closes the contract', async () => {
    const f = fixture(); await f.run();
    assert.equal(f.calls.some(call => call[0] === 'zero'), false);
    const options = f.calls.find(call => call[0] === 'line')[1];
    assert.equal(options.quantity, 1);
    assert.equal(options.merge, false);
    assert.equal(options.metadata.flow, 'cancellation_charge');
    assert.equal(options.metadata.source_subscription_id, 9);
    assert.equal(options.metadata.pricing_snapshot, f.quote);
    assert.equal(f.calls.at(-1)[0], 'added');
});
test('zero cancellation confirms directly without modifying the ticket or its customer', async () => {
    const f = fixture({amount:0}); await f.run();
    assert.deepEqual(f.calls.map(call=>call[0]), ['quote','zero','cancelled']);
});
test('closing the dialog performs no server request', async () => {
    const f = fixture({reply:false}); await f.run(); assert.equal(f.calls.length,0);
});
test('a late quote cannot cancel another customer or add a fee to another ticket', async () => {
    for (const change of [f=>{f.control.current=false;}, f=>{f.control.order={};}]) {
        const f = fixture({amount:0});
        f.options.api.preparePackageCancellation = async () => {change(f);return f.quote;};
        await f.run(); assert.equal(f.calls.length,0);
    }
});
test('a ticket switch while the dialog is open rejects the operation', async () => {
    const f = fixture(); f.options.showDialog = async () => {f.control.order={};return {amount:25};};
    await assert.rejects(f.run(), /Cambio el ticket/); assert.equal(f.calls.length,0);
});
test('another operation on the same contract cannot share its cancellation ticket', async () => {
    const f = fixture(); f.control.configs = [{source_subscription_id:9}];
    await assert.rejects(f.run(), /ya contiene/);
    assert.equal(f.calls.some(call=>call[0]==='line' || call[0]==='zero'),false);
});
test('loading a holder with another fiscal position requotes before adding the fee', async () => {
    const f = fixture();
    f.context.resolveSubscriptionOrderPartner = async () => { f.control.order.fiscal_position_id={id:4}; };
    f.options.api.preparePackageCancellation = async (...args) => {
        f.calls.push(['quote', ...args]);
        return {...f.quote, fiscal_position_id:args[4]};
    };
    await f.run();
    assert.equal(f.calls.filter(call=>call[0]==='quote').length,2);
    assert.equal(f.calls.find(call=>call[0]==='line')[1].metadata.pricing_snapshot.fiscal_position_id,4);
});
test('failed fee insertion leaves the contract active and shows no success', async () => {
    const f = fixture();
    f.context.addConfiguredProductLineToOrder = async () => ({line:null});
    await assert.rejects(f.run(), /no se cancelo/);
    assert.equal(f.calls.some(call=>call[0]==='added' || call[0]==='zero'),false);
});
test('native tax drift removes the fee before it can be charged', async () => {
    for (const total of [134.56, undefined]) {
        const f = fixture({amount:116});
        f.context.addConfiguredProductLineToOrder = async () => ({line:{priceIncl:total,
            delete:()=>f.calls.push(['removed'])}});
        await assert.rejects(f.run(), /total del cargo no coincide/);
        assert.equal(f.calls.at(-1)[0], 'removed');
        assert.equal(f.calls.some(call=>call[0]==='added' || call[0]==='zero'),false);
    }
});
test('dialog rejects invalid amounts and requires an explicit confirmation for zero', () => {
    const context = vm.createContext({Component:class {}, Dialog:class {}, useState:x=>x, xml:s=>s.join(''), _t:x=>x});
    load(context, 'subscription_cancellation_dialog.js');
    const DialogClass = vm.runInContext('PackageCancellationDialog', context);
    const calls=[]; const dialog=new DialogClass(); dialog.setup();
    dialog.props={getPayload:answer=>calls.push(answer), close:()=>calls.push('close')};
    for (const amount of ['', '-1', 'NaN', 'Infinity']) {
        dialog.state.amount=amount; dialog.confirm(); assert.equal(calls.length,0);
    }
    dialog.state.amount='0'; dialog.confirm(); assert.equal(calls[0].amount,0); assert.equal(calls[1],'close');
});
test('subscription card has cancellation but never a door selector', () => {
    const context=vm.createContext({renderAccessRecovery:()=>''}); load(context,'subscription_card_render.js');
    const html=context.renderSubscriptionCard({item:{can_cancel:true,subscription_id:9},
        accessSummary:{}, escapeHtml:String, formatDateDisplay:String, formatMoney:String, _t:x=>x});
    assert.match(html,/Cancelar paquete/);
    assert.doesNotMatch(html,/resync-device|<select/);
});
