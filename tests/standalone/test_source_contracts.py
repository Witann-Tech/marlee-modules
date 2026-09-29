"""Lightweight syntax/name gate, complementary to real ORM integration tests."""

import ast
import builtins
from pathlib import Path
import symtable
import unittest


ROOT = Path(__file__).resolve().parents[2]


class SourceContracts(unittest.TestCase):
    def test_addons_compile_and_have_no_unresolved_global_names(self):
        for manifest in ROOT.glob('*/__manifest__.py'):
            for path in manifest.parent.rglob('*.py'):
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
