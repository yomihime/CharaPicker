from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PyInstallerSpecTests(unittest.TestCase):
    def test_main_bundle_keeps_runtime_files_outside_executable(self) -> None:
        tree = ast.parse((ROOT / "main.spec").read_text(encoding="utf-8-sig"))
        exe_call = self._assigned_call(tree, "exe", "EXE")
        collect_call = self._assigned_call(tree, "coll", "COLLECT")

        keywords = {keyword.arg: keyword.value for keyword in exe_call.keywords}
        self.assertIn("exclude_binaries", keywords)
        self.assertIsInstance(keywords["exclude_binaries"], ast.Constant)
        self.assertIs(keywords["exclude_binaries"].value, True)

        embedded_analysis_parts = {
            argument.attr
            for argument in exe_call.args
            if isinstance(argument, ast.Attribute)
            and isinstance(argument.value, ast.Name)
            and argument.value.id == "a"
        }
        self.assertTrue({"binaries", "datas", "zipfiles"}.isdisjoint(embedded_analysis_parts))

        collected_analysis_parts = {
            argument.attr
            for argument in collect_call.args
            if isinstance(argument, ast.Attribute)
            and isinstance(argument.value, ast.Name)
            and argument.value.id == "a"
        }
        self.assertTrue({"binaries", "datas"}.issubset(collected_analysis_parts))

    def _assigned_call(self, tree: ast.Module, target_name: str, call_name: str) -> ast.Call:
        for node in tree.body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name) or target.id != target_name:
                continue
            self.assertIsInstance(node.value, ast.Call)
            self.assertIsInstance(node.value.func, ast.Name)
            self.assertEqual(node.value.func.id, call_name)
            return node.value
        self.fail(f"Missing {target_name} = {call_name}(...) in main.spec")


if __name__ == "__main__":
    unittest.main()
