import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const context = vm.createContext({console});
const source = fs.readFileSync(new URL('../../witann_group_subscriptions_pos/static/src/js/subscription_data_controllers.js', import.meta.url), 'utf8');
vm.runInContext(source.replace(/^export\s*\{[\s\S]*?\};?\s*$/gm, ''), context);
function deferred() {
    let resolve, reject;
    const promise = new Promise((a, b) => { resolve=a; reject=b; });
    return {promise, resolve, reject};
}
function setup() {
    const state = {rows:[], directoryLoadError:''};
    const overlay = {isConnected:true};
    const requests = [];
    let renders = 0;
    const deps = {overlay, _t:value => value, render() { renders++; },
        fetchPartnerDirectoryBatch() {
            const request = deferred(); requests.push(request); return request.promise;
        }};
    return {state, overlay, requests, deps, renders:() => renders};
}
test('a failed obsolete directory search cannot overwrite a newer successful result', async () => {
    const {state, requests, deps} = setup();
    const old = context.loadDirectoryRowsInBackground(state, deps);
    const current = context.loadDirectoryRowsInBackground(state, deps);
    requests[1].resolve([{id:7}]);
    await current;
    requests[0].reject(new Error('obsolete network failure'));
    await old;
    assert.equal(state.directoryLoadError, '');
    assert.equal(state.rows[0].id, 7);
    assert.equal(state.directoryLoading, false);
});
for (const outcome of ['success', 'failure']) {
    test(`closing the directory prevents a late ${outcome} from rendering`, async () => {
        const {state, overlay, requests, deps, renders} = setup();
        const pending = context.loadDirectoryRowsInBackground(state, deps);
        const before = renders();
        overlay.isConnected = false;
        if (outcome === 'success') requests[0].resolve([{id:7}]);
        else requests[0].reject(new Error('closed directory failure'));
        await pending;
        assert.equal(renders(), before);
        assert.equal(state.rows.length, 0);
        assert.equal(state.directoryLoadError, '');
    });
}
