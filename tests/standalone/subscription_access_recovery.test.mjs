import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const root = new URL('../../witann_group_subscriptions_pos/static/src/js/', import.meta.url);
const context = vm.createContext({console});
for (const file of ['subscription_access_recovery_render.js', 'subscription_inline_form_handlers.js', 'subscription_pos_api.js']) {
    const source = fs.readFileSync(new URL(file, root), 'utf8')
        .replace(/^import[\s\S]*?;\s*$/gm, '')
        .replace(/^export\s*\{[\s\S]*?\};?\s*$/gm, '').replace(/export function /g, 'function ');
    vm.runInContext(source, context, {filename: file});
}
const escape = value => String(value).replaceAll('<', '&lt;').replaceAll('>', '&gt;');
const translate = value => value;

for (const state of ['queued', 'sent', 'delivered', 'expired', 'failed', 'superseded']) {
    test(`${state} is never rendered as hardware-confirmed`, () => {
        const html = context.renderAccessRecovery({targets: [{name:'QA',device_name:'Puerta 2',state}]}, escape, translate);
        assert.doesNotMatch(html, /Confirmada por el equipo/);
    });
}
test('confirmed status and actionable errors render safely', () => {
    const html = context.renderAccessRecovery({targets: [
        {name:'QA',device_name:'Puerta 2',state:'confirmed'},
        {name:'<script>',device_name:'Puerta 1',state:'failed',error:'Falta foto <img>'},
    ]}, escape, translate);
    assert.match(html, /Confirmada por el equipo/);
    assert.match(html, /Falta foto &lt;img&gt;/);
    assert.doesNotMatch(html, /<script>/);
});
test('v2 explains bounded queue waiting without claiming confirmation or extending membership', () => {
    const html = context.renderAccessRecovery({protocol_version:2, targets:[{state:'sent'}]}, escape, translate);
    assert.match(html,/espera en cola no consume/);
    assert.match(html,/vigencia original/);
    assert.doesNotMatch(html,/Confirmada por el equipo/);
});
test('rejected, expired, superseded and empty results never use a green success notice', () => {
    for (const targets of [[], ...['failed', 'expired', 'superseded'].map(state => [{state}]),
        [{state:'confirmed'}, {state:'failed'}]]) {
        const html = context.renderAccessRecovery({targets}, escape, translate);
        assert.match(html, /class="wgs-inline-error"/);
        assert.doesNotMatch(html, /class="wgs-inline-notice"/);
    }
});

function fixture(overrides = {}) {
    const state = {selectedPartnerId: 7, currentDetail: {partner_id:7}};
    const calls = [];
    const loading = [];
    const handlers = context.buildSubscriptionInlineActionHandlers({
        state, clearFeedback(){}, renderDetail(){}, getResyncAccessState:()=>({}),
        setResyncAccessLoading:(...args)=>loading.push(args), startResyncAccessCooldown(){},
        fetchResyncAccess:async (...args)=>{calls.push(['recover',...args]);return {cooldown_seconds:60};},
        fetchAccessRecoveryStatus:async (...args)=>{calls.push(['status',...args]);return {state:'pending'};},
        loadDetail:async (...args)=>calls.push(['detail',...args]), detailCache:new Map(), _t:translate,
        ...overrides,
    });
    const actionButton = {dataset:{subscriptionId:'9'}, closest:()=>({querySelector:()=>({value:'4'})})};
    return {state,calls,loading,handlers,actionButton};
}
test('recover always includes all authorized terminals and never claims hardware success', async () => {
    const f = fixture(); await f.handlers['resync-access']({actionButton:f.actionButton});
    assert.deepEqual(f.calls[0], ['recover',9]);
    assert.match(f.state.formNotice, /aun no confirma acceso fisico/);
    assert.deepEqual(f.loading, [[9,true],[9,false]]);
});
test('checking status does not enqueue another recovery or payment', async () => {
    const f = fixture(); await f.handlers['check-resync-access']({actionButton:f.actionButton});
    assert.equal(f.calls[0][0], 'status');
    assert.equal(f.calls.filter(row=>row[0]==='recover').length,0);
    assert.equal(f.actionButton.disabled,false);
});
test('a late recovery response does not overwrite another customer', async () => {
    let resolve;
    const pending = new Promise(done=>{resolve=done;});
    const f = fixture({fetchResyncAccess:()=>pending});
    const result = f.handlers['resync-access']({actionButton:f.actionButton});
    f.state.selectedPartnerId = 8; resolve({cooldown_seconds:60}); await result;
    assert.equal(f.state.formNotice,undefined);
    assert.equal(f.calls.length,0);
    assert.deepEqual(f.loading,[[9,true],[9,false]]);
});
test('resync and status RPCs preserve the selected POS company', async () => {
    const calls=[]; const api=context.createSubscriptionPosApi({call:async(...args)=>calls.push(args)},()=>10);
    await api.resyncSubscriptionAccess(9); await api.fetchAccessRecoveryStatus(9);
    assert.equal(calls[0][1],'wgs_resync_subscription_access_for_pos');
    assert.deepEqual(JSON.parse(JSON.stringify(calls[0][2])),[9]);
    assert.deepEqual(JSON.parse(JSON.stringify(calls[1][3])),{context:{allowed_company_ids:[10]}});
});
