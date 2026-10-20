import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const source = fs.readFileSync(new URL('../../witann_group_subscriptions_pos/static/src/js/subscription_card_render.js', import.meta.url), 'utf8');
const context = vm.createContext({});
vm.runInContext(source.replace(/export\s*\{[^}]*\};?\s*$/, ''), context);

function render(change) {
    return context.renderSubscriptionCard({
        item: { subscription_id: 1905, scheduled_changes: [change], can_renew: true },
        accessSummary: {}, escapeHtml: (value) => String(value),
        formatDateDisplay: (value) => value, _t: (value) => value,
    });
}

test('legacy and transient failures describe automatic activation, never a human review', () => {
    const html = render({ state: 'review', retry_pending: true, product: 'SEMANA', start: '2026-10-16', end: '2026-10-22' });
    assert.match(html, /activacion automatica pendiente/);
    assert.doesNotMatch(html, /requiere revision/);
    assert.match(html, /2026-10-16 - 2026-10-22/);
});

test('normal future purchases remain scheduled and do not look like failures', () => {
    const html = render({ state: 'scheduled', retry_pending: false });
    assert.match(html, /Cambio de paquete pagado y programado/);
    assert.doesNotMatch(html, /activacion automatica pendiente/);
});
