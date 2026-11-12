from __future__ import annotations

import base64
import sys
import tempfile
import unittest
from pathlib import Path


DESKTOP_PET_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DESKTOP_PET_ROOT))

from setup_shortcut import (  # noqa: E402
    DEFAULT_NAME,
    build_shortcut_script,
    clean_powershell_error,
    encode_powershell,
    parse_verification,
    prepare_icon,
    validate_shortcut_name,
)

NO_PROGRESS = "Write-Output"


class ShortcutScriptTests(unittest.TestCase):
    """验证快捷方式脚本的拼装与转义，不接触真实桌面。"""

    def _script(self, **overrides):
        """按默认参数生成脚本，允许用例覆盖个别字段。"""
        params = {
            "name": DEFAULT_NAME,
            "target": r"C:\pet\.desktop_pet_venv\Scripts\pythonw.exe",
            "arguments": "launch.py",
            "working_directory": r"C:\pet",
            "description": "小桃桌面宠物",
            "icon": r"C:\pet\assets\character.ico",
            "temp_name": ".dsh-link-1.lnk",
        }
        params.update(overrides)
        return build_shortcut_script(**params)

    def test_script_creates_temp_link_then_renames_to_display_name(self) -> None:
        """脚本必须先用 ASCII 临时名保存，再重命名成含特殊字符的显示名。"""
        script = self._script()

        self.assertIn("$temp = Join-Path $desktop '.dsh-link-1.lnk'", script)
        self.assertIn("$shortcut = $shell.CreateShortcut($temp)", script)
        self.assertIn("$shortcut.Save()", script)
        self.assertIn("Move-Item -LiteralPath $temp -Destination $final -Force", script)
        self.assertIn(f"'(´•ω•)`.lnk'", script)

    def test_script_sets_target_arguments_and_icon(self) -> None:
        """目标、参数、起始目录与图标都要写入快捷方式。"""
        script = self._script()

        self.assertIn(r"$shortcut.TargetPath = 'C:\pet\.desktop_pet_venv\Scripts\pythonw.exe'", script)
        self.assertIn("$shortcut.Arguments = 'launch.py'", script)
        self.assertIn(r"$shortcut.WorkingDirectory = 'C:\pet'", script)
        self.assertIn(r"$shortcut.IconLocation = 'C:\pet\assets\character.ico,0'", script)
        self.assertIn("$shortcut.Description = '小桃桌面宠物'", script)

    def test_icon_can_be_omitted(self) -> None:
        """没有图标文件时不应写入 IconLocation，避免快捷方式变成空白图标。"""
        script = self._script(icon=None)

        self.assertNotIn("IconLocation", script)

    def test_single_quotes_in_paths_are_doubled(self) -> None:
        """路径里的单引号按 PowerShell 规则加倍，避免脚本被提前截断。"""
        script = self._script(target=r"C:\it's\pythonw.exe")

        self.assertIn(r"$shortcut.TargetPath = 'C:\it''s\pythonw.exe'", script)

    def test_invalid_names_are_rejected(self) -> None:
        """含路径分隔符或非法字符的名称不能用来创建文件。"""
        for bad in ("", "   ", "a/b", r"a\b", "a:b", "a*b", "a?b", 'a"b', "a<b", "a|b", ".."):
            with self.subTest(name=bad):
                with self.assertRaises(ValueError):
                    validate_shortcut_name(bad)

    def test_default_name_is_preserved_exactly(self) -> None:
        """默认名称保持用户指定的字符，不被裁剪或替换。"""
        self.assertEqual(validate_shortcut_name(DEFAULT_NAME), "(´•ω•)`")

    def test_encoded_command_round_trips(self) -> None:
        """EncodedCommand 参数解码后应还原原脚本，保证中文描述不被破坏。"""
        script = self._script()

        decoded = base64.b64decode(encode_powershell(script)).decode("utf-16-le")

        self.assertEqual(decoded, script)

    def test_verification_parsing_reads_three_fields(self) -> None:
        """回读结果按 TARGET/ARGS/WORKDIR 解析，多余输出被忽略。"""
        output = f"{NO_PROGRESS}\nTARGET=C:\\pet\\pythonw.exe\nARGS=launch.py\nWORKDIR=C:\\pet\n"

        self.assertEqual(
            parse_verification(output),
            {"TARGET": r"C:\pet\pythonw.exe", "ARGS": "launch.py", "WORKDIR": r"C:\pet"},
        )

    def test_clixml_error_is_flattened(self) -> None:
        """PowerShell 的 CLIXML 错误要还原成一行可读文本，而不是整段序列化内容。"""
        clixml = (
            "#< CLIXML\n<Objs><S S=\"Error\">无法保存快捷方式_x000D__x000A_</S>"
            "<S S=\"Error\">+ CategoryInfo : OperationStopped</S></Objs>"
        )

        message = clean_powershell_error(clixml)

        self.assertNotIn("CLIXML", message)
        self.assertIn("无法保存快捷方式", message)
        self.assertIn("CategoryInfo", message)

    def test_plain_error_keeps_first_line(self) -> None:
        """非 CLIXML 的错误只保留第一行，避免提示被堆栈淹没。"""
        self.assertEqual(clean_powershell_error("boom\nstack"), "boom")
        self.assertEqual(clean_powershell_error(""), "")


class IconPreparationTests(unittest.TestCase):
    """验证图标被复制到用户配置区，快捷方式不再引用仓库内的路径。"""

    def test_icon_is_copied_into_icon_home(self) -> None:
        """把仓库图标复制到指定目录，并返回复制后的路径。"""
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source = base / "assets" / "character.ico"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"icon-bytes")

            target = prepare_icon(source, icon_home=base / "appdata")

            self.assertEqual(target, base / "appdata" / "character.ico")
            self.assertEqual(target.read_bytes(), b"icon-bytes")

    def test_missing_or_absent_icon_is_skipped(self) -> None:
        """图标缺失或调用方明确不提供图标时返回 None，不创建目录。"""
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)

            self.assertIsNone(prepare_icon(None, icon_home=base / "appdata"))
            self.assertIsNone(
                prepare_icon(base / "missing.ico", icon_home=base / "appdata")
            )
            self.assertFalse((base / "appdata").exists())


if __name__ == "__main__":
    unittest.main()
