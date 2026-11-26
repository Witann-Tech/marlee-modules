import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const context = vm.createContext({});
const source = fs.readFileSync(new URL('../../witann_group_subscriptions_pos/static/src/js/subscription_modal_state.js', import.meta.url), 'utf8');
vm.runInContext(source.replace(/^export\s*\{[\s\S]*?\};?\s*$/gm, ''), context);

test('new customer draft survives empty/loading results and first automatic selection', () => {
    for (const rows of [[], [{id: 7}], [{id: 8}]]) {
        const draft = {name: 'QA Customer', cameraActive: true};
        const state = {formMode: 'new_partner', newPartnerForm: draft, selectedPartnerId: 7,
            formError: 'Capture required fields', formNotice: 'Draft'};
        context.reconcileDirectorySelectionState(state, rows, {
            clearDirectorySelection() {assert.fail('Must not discard creation');},
            resetForPartnerSelection() {assert.fail('Must not rebind creation');},
        });
        assert.equal(state.newPartnerForm, draft);
        assert.equal(state.formMode, 'new_partner');
        assert.equal(state.formError, 'Capture required fields');
        assert.equal(draft.cameraActive, true);
    }
});

test('ordinary directory navigation still clears empty results and selects a new row', () => {
    let cleared = 0, reset = 0;
    const deps = {clearDirectorySelection() {cleared++;}, resetForPartnerSelection() {reset++;}};
    const state = {selectedPartnerId: 7};
    context.reconcileDirectorySelectionState(state, [], deps);
    assert.equal(cleared, 1);
    context.reconcileDirectorySelectionState(state, [{id: 8}], deps);
    assert.equal(state.selectedPartnerId, 8);
    assert.equal(reset, 1);
    context.reconcileDirectorySelectionState(state, [{id: 8}], deps);
    assert.equal(reset, 1);
});

test('cancelled or incomplete new customer form cannot block normal directory navigation', () => {
    for (const state of [{formMode: null, newPartnerForm: {}}, {formMode:'new_partner', newPartnerForm:null}]) {
        let reset = 0;
        context.reconcileDirectorySelectionState(state, [{id: 9}], {
            clearDirectorySelection() {assert.fail('Nonempty rows');}, resetForPartnerSelection() {reset++;},
        });
        assert.equal(state.selectedPartnerId, 9);
        assert.equal(reset, 1);
    }
});
