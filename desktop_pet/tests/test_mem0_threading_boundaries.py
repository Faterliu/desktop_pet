from __future__ import annotations

import ast
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WINDOW_SOURCE_PATH = PROJECT_ROOT / "app" / "desktop_pet_window.py"


# 为测试准备methodsource数据或断言辅助结果。
def _method_source(class_name: str, method_name: str) -> str:
    """为测试准备methodsource数据或断言辅助结果。"""
    source = WINDOW_SOURCE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == method_name:
                    return ast.get_source_segment(source, item) or ""
    raise AssertionError(f"Missing {class_name}.{method_name}")


class Mem0ThreadingBoundaryTests(unittest.TestCase):
    # 验证mem 0 init and reload are 工作线程 driven场景下的预期结果。
    def test_mem0_init_and_reload_are_worker_driven(self) -> None:
        """验证mem 0 init and reload are 工作线程 driven场景下的预期结果。"""
        source = WINDOW_SOURCE_PATH.read_text(encoding="utf-8")
        init_source = _method_source("DesktopPetWindow", "__init__")
        reload_source = _method_source("DesktopPetWindow", "_reload_config")

        self.assertIn("class Mem0InitializationWorker", source)
        self.assertIn("_start_mem0_initialization(close_existing=False)", init_source)
        self.assertIn("_start_mem0_initialization(close_existing=True)", reload_source)
        self.assertNotIn("Mem0MemoryService(self.app_config)", init_source)
        self.assertNotIn("Mem0MemoryService(self.app_config)", reload_source)

    # 验证知识问候 记忆 check starts search 工作线程 without sync search场景下的预期结果。
    def test_knowledge_memory_check_starts_search_worker_without_sync_search(self) -> None:
        """验证知识问候 记忆 check starts search 工作线程 without sync search场景下的预期结果。"""
        source = WINDOW_SOURCE_PATH.read_text(encoding="utf-8")
        method_source = _method_source("DesktopPetWindow", "_has_knowledge_memory")

        self.assertIn("class Mem0SearchWorker", source)
        self.assertIn("_start_mem0_search_worker", method_source)
        self.assertNotIn("format_for_prompt", method_source)


if __name__ == "__main__":
    unittest.main()
