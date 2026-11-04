"""Execute the real RPC boundary against a deliberately destructive native peer."""
import ast
from copy import deepcopy
from pathlib import Path
import unittest


class NativeConflict(Exception):
    pass


class NativeCheckout:
    def sync_from_ui(self, orders):
        self.calls += 1
        self.received.append(deepcopy(orders))
        orders[0].pop('wgs_subscription_configs')
        orders[0]['lines'][0][2].pop('uuid')
        orders[0]['lines'].clear()
        if self.fail:
            self.fail = False
            raise NativeConflict()
        return {'ok': True}


def boundary():
    source = Path(__file__).resolve().parents[2] / 'witann_group_subscriptions_pos/models/pos_order.py'
    model = next(node for node in ast.parse(source.read_text()).body if isinstance(node, ast.ClassDef) and node.name == 'PosOrder')
    method = next(node for node in model.body if isinstance(node, ast.FunctionDef) and node.name == 'sync_from_ui')
    method.decorator_list = []
    subject = ast.ClassDef(name='Checkout', bases=[ast.Name(id='NativeCheckout', ctx=ast.Load())],
                           keywords=[], body=[method], decorator_list=[])
    namespace = {'NativeCheckout': NativeCheckout, 'deepcopy': deepcopy}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[subject], type_ignores=[])), str(source), 'exec'), namespace)
    obj = namespace['Checkout']()
    obj.calls, obj.received = 0, []
    return obj


class RpcRetryTests(unittest.TestCase):
    def setUp(self):
        self.payload = [{'uuid':'order', 'wgs_subscription_configs':[{'pricing_snapshot':{'plan_id':15}}],
                         'lines':[[0, 0, {'uuid':'line', 'product_id':1554}]]}]

    def test_success_does_not_consume_caller_metadata(self):
        checkout = boundary()
        checkout.fail = False
        original = deepcopy(self.payload)
        self.assertEqual(checkout.sync_from_ui(self.payload), {'ok':True})
        self.assertEqual(self.payload, original)

    def test_retry_uses_all_original_nested_commands_and_metadata(self):
        checkout = boundary()
        checkout.fail = True
        original = deepcopy(self.payload)
        with self.assertRaises(NativeConflict):
            checkout.sync_from_ui(self.payload)
        self.assertEqual(self.payload, original)
        checkout.sync_from_ui(self.payload)
        self.assertEqual(checkout.received, [original, original])
        self.assertEqual(self.payload, original)
