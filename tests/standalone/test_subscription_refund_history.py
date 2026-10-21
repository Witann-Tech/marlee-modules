"""Commercial history survives native cancellation without reviving its sale."""

from datetime import date
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from test_subscription_contract import method, POS, UserError
from test_subscription_eligibility import Contracts, LinkedLines
from test_subscription_policy import source


SALE = 'witann_group_subscriptions_pos/models/sale_order.py'


def historical(*, state='cancel', paid='paid', qty=1, recurring=True):
    return SimpleNamespace(
        state=state, ensure_one=lambda: None,
        _fields={'is_subscription', 'subscription_state'},
        is_subscription=False, subscription_state=False,
        _get_recurring_lines=lambda: [object()] if recurring else [],
        wgs_pos_application_line_ids=LinkedLines([
            SimpleNamespace(qty=qty, order_id=SimpleNamespace(state=paid)),
        ]),
    )


class RefundHistoryTests(unittest.TestCase):
    def test_cancelled_paid_sale_keeps_history_even_without_native_flags(self):
        check = method(SALE, '_is_subscription_record_for_pos')
        for paid in ('paid', 'done', 'invoiced'):
            self.assertTrue(check(historical(paid=paid)))

    def test_unpaid_quotations_refunds_and_non_memberships_are_not_history(self):
        check = method(SALE, '_is_subscription_record_for_pos')
        for kwargs in ({'paid': 'draft'}, {'paid': 'cancel'}, {'qty': -1},
                       {'qty': 0}, {'recurring': False}, {'state': 'draft'}):
            with self.subTest(kwargs=kwargs):
                self.assertFalse(check(historical(**kwargs)))
        item = historical()
        item.wgs_pos_application_line_ids = LinkedLines([])
        self.assertFalse(check(item))

    def test_native_subscription_identity_is_unchanged_for_normal_sales(self):
        item = historical(state='sale')
        item.is_subscription, item.subscription_state = True, '3_progress'
        self.assertTrue(method(SALE, '_is_subscription_record_for_pos')(item))
        item.is_subscription = False
        self.assertFalse(method(SALE, '_is_subscription_record_for_pos')(item))

    def test_cancel_state_wins_over_stale_native_labels_and_contract(self):
        item = source(state='progress', access='enabled', start=date(2026, 11, 1))
        item.state = 'cancel'
        item._get_subscription_state_display_for_pos = Mock(side_effect=AssertionError('native label read'))
        state = method(SALE, '_get_native_subscription_state_info_for_pos')
        item._get_native_subscription_state_info_for_pos = lambda: state(item)
        item.wgs_domiciliation_contract_id = Mock(state='active')
        policy = item._wgs_subscription_operation_policy_for_pos()
        self.assertEqual(policy['state_key'], 'cancel')
        self.assertTrue(policy['can_reenroll'])
        self.assertFalse(policy['can_renew'])
        self.assertFalse(policy['can_upsale'])
        self.assertFalse(policy['access_state'])
        item.wgs_domiciliation_contract_id.wgs_get_operational_status.assert_not_called()
        self.assertFalse(method(SALE, '_wgs_build_domiciliation_status_item_for_pos')(item, date(2026, 10, 20)))

    def test_cancelled_holder_gets_new_contract_but_closed_sale_reuses_own(self):
        buyer = Mock()
        item = Mock(state='cancel', partner_id=buyer, participant_ids=[])
        service = Mock()
        service._wgs_find_subscription_history_for_partner.return_value = Contracts([item])
        check = method(POS, '_wgs_reenrollment_requires_new_contract')
        self.assertTrue(check(service, item, buyer))
        item.state = 'sale'
        self.assertFalse(check(service, item, buyer))

    def test_cancelled_origin_cannot_be_reused_while_replacement_is_active(self):
        buyer, other = Mock(), Mock()
        item = Mock(state='cancel', partner_id=buyer)
        service = Mock()
        service._wgs_find_subscription_history_for_partner.return_value = Contracts([item, other])
        check = method(POS, '_wgs_reenrollment_requires_new_contract')
        for state in ('progress', 'future'):
            other._wgs_subscription_operation_policy_for_pos.return_value = {
                'can_renew': state == 'progress', 'state_key': state,
            }
            with self.assertRaises(UserError):
                check(service, item, buyer)

    def test_directory_single_batch_and_checkout_search_include_cancellations(self):
        model = Mock(_fields={'company_id'})
        state_domain = method(SALE, '_wgs_subscription_history_state_domain_for_pos')(model)
        model._wgs_subscription_history_state_domain_for_pos.side_effect = lambda: list(state_domain)
        domain = method(SALE, '_get_subscription_action_domain_for_pos')(model, Mock(id=9))
        self.assertIn(('state', '=', 'cancel'), domain)
        self.assertIn(('wgs_pos_application_line_ids', 'any', [
            ('qty', '>', 0), ('order_id.state', 'in', ['paid', 'done', 'invoiced']),
        ]), domain)
        self.assertIn(('company_id', '=', 9), domain)
        check = method(SALE, '_is_subscription_record_for_pos')
        item = historical()
        item._is_subscription_record_for_pos = lambda: check(item)
        items = LinkedLines([item])
        model._wgs_and_domains_for_pos.side_effect = lambda *parts: list(parts)
        model._get_subscription_action_domain_for_pos.return_value = domain
        model.sudo.return_value.search.return_value = items
        model._filter_local_pos_subscriptions_for_pos.side_effect = lambda records, **kw: records
        partner = Mock(id=7, ids=[7])
        self.assertEqual(method(SALE, '_get_pos_subscription_orders')(model, partner, Mock(id=9)), items)
        # Native-recognition delegation is shared by quote/checkout and history.
        self.assertTrue(method(POS, '_wgs_order_has_subscription_signal')(None, item))


if __name__ == '__main__':
    unittest.main()
