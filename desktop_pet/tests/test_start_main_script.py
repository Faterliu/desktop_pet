from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class StartMainScriptTests(unittest.TestCase):
    # 验证vbs does not repeat pyside 6 dependency import check场景下的预期结果。
    def test_vbs_does_not_repeat_pyside6_dependency_import_check(self) -> None:
        """验证vbs does not repeat pyside 6 dependency import check场景下的预期结果。"""
        script_text = (PROJECT_ROOT / "start_main.vbs").read_text(encoding="utf-8")

        self.assertNotIn("import PySide6, requests", script_text)
        self.assertNotIn("Project dependencies are missing or incomplete", script_text)


if __name__ == "__main__":
    unittest.main()
