import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../witann_group_subscriptions_pos/static/src/js');

function screenFixture({ member = true, refund = false, failure = false, refused = false } = {}) {
    const calls = [], alerts = [];
    const order = {
        uuid: 'order-uuid', uid: 'order-uuid', to_invoice: true, partner_id: 8,
        configs: member ? [{ flow: 'renewal', line_uuid: 'line-uuid',
            pricing_snapshot: {commercial_quote: {payload: {partner_id: 8}}} }] : [],
        lines: [{ uuid: 'line-uuid', product_id: { id: 20, recurring_invoice: member }, qty: refund ? -1 : 1, price_unit: 619, discount: 0 }],
    };
    const stats = { validated: 0, setup: 0 };
    class PaymentScreen {}
    const context = vm.createContext({
        PaymentScreen, console: { error() {} }, document: {}, window: { alert(message) { alerts.push(message); } },
        _t: (value) => value, useService: () => ({}), onMounted() {}, onPatched() {},
        patch(_target, extension) {
            Object.setPrototypeOf(extension, {
                setup() { stats.setup++; },
                validateOrder(...args) { stats.validated++; stats.args = args; return 'validated'; },
            });
            Object.assign(PaymentScreen.prototype, extension);
        },
        collectMembershipRefundsFromOrder: () => refund ? [{ original_line_id: 1, qty: -1 }] : [],
        collectSubscriptionConfigsFromOrder: (value) => value.configs,
        getCurrentCompanyId: () => 10, getLineQty: (line) => line.qty,
        getOrderLines: (value) => value.lines, getOrderUid: (value) => value.uuid,
        getPartnerIdFromOrder: (value) => value.partner_id,
        getProductIdFromLine: (line) => line.product_id.id,
        getOrderFromPaymentScreen: (screen) => screen.currentOrder,
        clearInvoiceFlag: (value) => { value.to_invoice = false; },
        disableInvoiceControls() {}, installInvoiceControlGuard() {},
    });
    const ticket = fs.readFileSync(path.join(root, 'subscription_ticket.js'), 'utf8')
        .replace(/export (async )?function /g, (_match, asyncPart) => `${asyncPart || ''}function `);
    vm.runInContext(ticket, context, { filename: 'subscription_ticket.js' });
    // Payment-screen doubles use numeric IDs; ticket's actual identity resolver
    // is also exercised below with native registered partner records.
    context.getPartnerIdFromOrder = (value) => typeof value.partner_id === 'number'
        ? value.partner_id : Number(value.partner_id?.id || 0);
    context.getCurrentCompanyId = () => 10;
    context.collectSubscriptionConfigsFromOrder = (value) => value.configs;
    context.collectMembershipRefundsFromOrder = () => refund ? [{original_line_id: 1, qty: -1}] : [];
    const source = fs.readFileSync(path.join(root, 'subscription_payment_guard.js'), 'utf8')
        .replace(/^import[\s\S]*?;\s*$/gm, '')
        .replace('export async function ', 'async function ');
    vm.runInContext(source, context, { filename: 'subscription_payment_guard.js' });
    const screen = new PaymentScreen();
    screen.currentOrder = order;
    screen.pos = {};
    screen.notification = { add(message) { alerts.push(message); } };
    screen.orm = { async call(...args) {
        calls.push(args);
        if (failure) throw new Error('Payment preflight rejected');
        return { ok: !refused };
    } };
    return { screen, order, calls, alerts, stats };
}

test('membership preflight stages exact UUID once before native payment and clears invoicing', async () => {
    const { screen, order, calls, stats } = screenFixture();
    assert.equal(await screen.validateOrder(true), 'validated');
    assert.equal(order.to_invoice, false);
    assert.equal(calls.length, 1);
    assert.equal(calls[0][1], 'wgs_stage_subscription_config_for_uuid');
    assert.equal(calls[0][2][0], 'order-uuid');
    assert.equal(calls[0][2][2].company_id, 10);
    assert.equal(calls[0][2][2].lines[0].price_unit, 619);
    assert.equal(stats.validated, 1);
    assert.deepEqual(stats.args, [true]);
});

test('ordinary product sales still validate without subscription RPCs', async () => {
    const { screen, order, calls, stats } = screenFixture({ member: false });
    await screen.validateOrder();
    assert.equal(calls.length, 0);
    assert.equal(stats.validated, 1);
    assert.equal(order.to_invoice, false);
});

test('failed or refused preflight never calls native payment', async () => {
    for (const options of [{ failure: true }, { refused: true }]) {
        const { screen, alerts, stats } = screenFixture(options);
        await screen.validateOrder();
        assert.equal(stats.validated, 0);
        assert.equal(alerts.length, 1);
    }
});

test('refund validation precedes native payment and preserves total-refund policy', async () => {
    const { screen, calls, stats } = screenFixture({ refund: true, member: false });
    await screen.validateOrder();
    assert.equal(calls[0][1], 'wgs_validate_subscription_refunds_for_pos');
    assert.equal(stats.validated, 1);
    const failed = screenFixture({ refund: true, member: false, failure: true });
    await failed.screen.validateOrder();
    assert.equal(failed.stats.validated, 0);
});

test('invoice toggle stays disabled in the consolidated payment extension', () => {
    const { screen, order, alerts } = screenFixture();
    assert.equal(screen.toggleIsToInvoice(), false);
    assert.equal(order.to_invoice, false);
    assert.equal(alerts.length, 1);
});

test('the addon registers exactly one PaymentScreen extension', () => {
    const count = fs.readdirSync(root).filter((name) => name.endsWith('.js')).reduce((total, name) =>
        total + [...fs.readFileSync(path.join(root, name), 'utf8').matchAll(/patch\(PaymentScreen\.prototype/g)].length, 0
    );
    assert.equal(count, 1);
});

test('a restored membership loads its signed customer as a native record before preflight', async () => {
    const { screen, order, calls, stats } = screenFixture();
    const registered = new Map();
    order.partner_id = false;
    order.setPartner = (partner) => { order.partner_id = partner; };
    screen.pos = { models: {'res.partner': registered}, data: {
        async read(model, ids) {
            assert.equal(model, 'res.partner');
            assert.equal(ids[0], 8);
            registered.set(8, {id: 8, name: 'Registered customer'});
        },
    } };
    await screen.validateOrder();
    assert.equal(order.partner_id, registered.get(8));
    assert.equal(calls[0][2][2].partner_id, 8);
    assert.equal(stats.validated, 1);
});

test('restoration never overwrites another explicitly selected customer', async () => {
    const { screen, order, calls, stats } = screenFixture();
    order.partner_id = 99;
    await screen.validateOrder();
    assert.equal(order.partner_id, 99);
    assert.equal(stats.validated, 0);
    assert.equal(calls.length, 0);
});

test('customer lookup failure and mixed quote owners never reach native payment', async () => {
    for (const mixed of [false, true]) {
        const { screen, order, stats } = screenFixture();
        order.partner_id = false;
        screen.pos = {models: {'res.partner': new Map()}, data: {async read() { throw Error('offline'); }}};
        if (mixed) order.configs.push({pricing_snapshot: {commercial_quote: {payload: {partner_id: 9}}}});
        await screen.validateOrder();
        assert.equal(stats.validated, 0);
        assert.equal(order.partner_id, false);
    }
});
