"""Lightweight syntax/name gate, complementary to real ORM integration tests."""

import ast
import builtins
from pathlib import Path
import symtable
import unittest


ROOT = Path(__file__).resolve().parents[2]
ADDONS = ('access_control_api', 'witann_group_subscriptions', 'witann_group_subscriptions_pos')


class SourceContracts(unittest.TestCase):
    def test_all_wgs_orm_test_files_are_registered(self):
        for addon in ADDONS:
            folder = ROOT / addon / 'tests'
            imports = ast.parse((folder / '__init__.py').read_text())
            loaded = {alias.name for node in imports.body if isinstance(node, ast.ImportFrom) for alias in node.names}
            self.assertEqual({path.stem for path in folder.glob('test_*.py')}, loaded, addon)

    def test_addons_compile_and_have_no_unresolved_global_names(self):
        for addon in ADDONS:
            for path in (ROOT / addon).rglob('*.py'):
                with self.subTest(path=str(path.relative_to(ROOT))):
                    source = path.read_text()
                    ast.parse(source, filename=str(path))
                    table = symtable.symtable(source, str(path), 'exec')
                    defined = {
                        symbol.get_name() for symbol in table.get_symbols()
                        if symbol.is_assigned() or symbol.is_imported() or symbol.is_namespace()
                    } | set(dir(builtins)) | {'__file__', '__name__', '__class__'}
                    pending = [table]
                    while pending:
                        scope = pending.pop()
                        for symbol in scope.get_symbols():
                            if symbol.is_referenced() and symbol.is_global():
                                self.assertIn(symbol.get_name(), defined, (path, scope.get_name()))
                        pending.extend(scope.get_children())
