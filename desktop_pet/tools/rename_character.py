"""批量替换桌宠角色名称：将 desktop_pet/ 目录下所有"小胡"替换为新名字。

用法:
    py rename_character.py 新名字
    py rename_character.py 芙芙

会递归扫描 desktop_pet/desktop_pet/ 下所有文本文件，预览并确认后执行替换。
"""

from __future__ import annotations

import sys
from pathlib import Path

TARGET_DIR = Path(__file__).resolve().parent.parent / "desktop_pet"
OLD_NAME = "小桃"  

TEXT_EXTENSIONS = {
    ".py", ".json", ".md", ".txt", ".bat", ".vbs", ".cfg", ".ini", ".yml", ".yaml"
}

BINARY_EXTENSIONS = {
    ".webp", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".bmp",
    ".pyc", ".pyd", ".dll", ".exe", ".so", ".zip", ".7z",
}


# 根据文件扩展名判断路径是否属于可替换文本文件。
def is_text_file(path: Path) -> bool:
    """根据文件扩展名判断路径是否属于可替换文本文件。"""
    suffix = path.suffix.lower()
    if suffix in BINARY_EXTENSIONS:
        return False
    if suffix in TEXT_EXTENSIONS:
        return True
    # 无后缀或有未知后缀，尝试读取前几个字节看是否文本
    return False


# 扫描目标目录，预览每个文件中旧名字的出现次数。
def scan_and_preview(new_name: str) -> dict[Path, int]:
    """扫描目标目录，预览每个文件中旧名字的出现次数。"""
    results: dict[Path, int] = {}
    total = 0
    print(f"扫描目录: {TARGET_DIR}")
    print(f"替换目标: 「{OLD_NAME}」→「{new_name}」")
    print()
    for file_path in sorted(TARGET_DIR.rglob("*")):
        if not file_path.is_file():
            continue
        if not is_text_file(file_path):
            continue
        # 跳过 __pycache__ 和 .git
        if "__pycache__" in file_path.parts or ".git" in file_path.parts:
            continue
        try:
            content = file_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, PermissionError):
            continue
        count = content.count(OLD_NAME)
        if count > 0:
            results[file_path] = count
            total += count
            rel = file_path.relative_to(TARGET_DIR.parent)
            print(f"  {rel}  ({count} 处)")
    print()
    print(f"共计 {len(results)} 个文件，{total} 处替换。")
    return results


# 在指定文件中执行替换。
def execute_replace(new_name: str, files: dict[Path, int]) -> None:
    """在指定文件中执行替换。"""
    replaced = 0
    for file_path in files:
        content = file_path.read_text(encoding="utf-8")
        new_content = content.replace(OLD_NAME, new_name)
        if new_content != content:
            file_path.write_text(new_content, encoding="utf-8")
            replaced += 1
    print(f"已完成 {replaced} 个文件的替换。")


# 运行当前模块的主流程。
def main() -> None:
    """运行当前模块的主流程。"""
    if len(sys.argv) < 2:
        print("用法: py rename_character.py 新名字")
        print("示例: py rename_character.py 小虎")
        sys.exit(1)

    new_name = sys.argv[1].strip()
    if not new_name:
        print("错误: 新名字不能为空。")
        sys.exit(1)
    if new_name == OLD_NAME:
        print(f"新名字和旧名字相同（{OLD_NAME}），无需替换。")
        sys.exit(0)

    files = scan_and_preview(new_name)
    if not files:
        print("未找到需要替换的文件。")
        return

    answer = input("确认执行以上替换？(y/N): ").strip().lower()
    if answer in ("y", "yes"):
        execute_replace(new_name, files)
    else:
        print("已取消。")


if __name__ == "__main__":
    main()
