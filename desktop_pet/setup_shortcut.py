"""在桌面创建桌宠启动快捷方式，供 setup_env.bat 在环境就绪后调用。

快捷方式直接指向 `.desktop_pet_venv\\Scripts\\pythonw.exe launch.py`，不经过
`.vbs` 脚本宿主，因此不会出现「打开文件 - 安全警告」。非 ASCII 的快捷方式名称
放在这里而不是 `.bat` 里，避免 cmd.exe 按 OEM 代码页误读。

WScript.Shell 的 CreateShortcut 会把目标文件名按系统 ANSI 代码页转换，遇到
`´`、`•` 这类字符会失败；因此先用纯 ASCII 临时名创建，再用 NTFS 重命名改成
最终名称，属性与图标都在临时名阶段写入。
"""

from __future__ import annotations

import argparse
import base64
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
VENV_PYTHONW = BASE_DIR / ".desktop_pet_venv" / "Scripts" / "pythonw.exe"
LAUNCH_SCRIPT = BASE_DIR / "launch.py"
DEFAULT_ICON = BASE_DIR / "assets" / "character.ico"
# 图标放在用户配置区：仓库所在目录可能受 ACL 或沙箱保护，外壳取图标会读不到。
ICON_HOME = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "DesktopPet"
DEFAULT_NAME = "(´•ω•)`"
DEFAULT_DESCRIPTION = "小桃桌面宠物"
INVALID_NAME_CHARS = set('\\/:*?"<>|')

CREATE_NO_WINDOW = 0x08000000


# 把仓库里的图标复制到用户配置区，返回快捷方式应引用的路径。
def prepare_icon(source: Path | None, icon_home: Path | None = None) -> Path | None:
    """复制图标到本地应用目录；源文件不存在时返回 None，跳过图标设置。"""
    if source is None:
        return None
    source_path = Path(source)
    if not source_path.is_file():
        return None
    target_dir = Path(icon_home) if icon_home else ICON_HOME
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "character.ico"
    if source_path.resolve() != target.resolve():
        shutil.copyfile(source_path, target)
    return target


# 把纯文本转成 PowerShell 单引号字面量，内部单引号按 PowerShell 规则加倍。
def _ps_quote(value: str) -> str:
    """返回可直接嵌入 PowerShell 脚本的单引号字符串。"""
    return "'" + str(value).replace("'", "''") + "'"


# 校验收到的快捷方式名称能作为文件名使用，避免把路径分隔符带进桌面目录。
def validate_shortcut_name(name: str) -> str:
    """校验快捷方式名称，非法字符或缺省名称时抛出 ValueError。"""
    cleaned = str(name or "").strip()
    if not cleaned:
        raise ValueError("shortcut name is empty")
    if cleaned in {".", ".."} or any(char in INVALID_NAME_CHARS for char in cleaned):
        raise ValueError(f"shortcut name is not a valid file name: {name!r}")
    return cleaned


# 生成创建快捷方式的 PowerShell 脚本：先用 ASCII 临时名写入属性，再重命名并回读校验。
def build_shortcut_script(
    name: str,
    target: str,
    arguments: str,
    working_directory: str,
    description: str,
    icon: str | None = None,
    temp_name: str = ".dsh-link-tmp.lnk",
) -> str:
    """返回创建桌面快捷方式的 PowerShell 脚本正文。"""
    final_name = validate_shortcut_name(name) + ".lnk"
    lines = [
        "$ErrorActionPreference = 'Stop'",
        "$desktop = [Environment]::GetFolderPath('Desktop')",
        f"$temp = Join-Path $desktop {_ps_quote(temp_name)}",
        f"$final = Join-Path $desktop {_ps_quote(final_name)}",
        "if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Force }",
        "$shell = New-Object -ComObject WScript.Shell",
        "$shortcut = $shell.CreateShortcut($temp)",
        f"$shortcut.TargetPath = {_ps_quote(target)}",
        f"$shortcut.Arguments = {_ps_quote(arguments)}",
        f"$shortcut.WorkingDirectory = {_ps_quote(working_directory)}",
        f"$shortcut.Description = {_ps_quote(description)}",
    ]
    if icon:
        lines.append(f"$shortcut.IconLocation = {_ps_quote(str(icon) + ',0')}")
    lines.extend([
        "$shortcut.Save()",
        "Move-Item -LiteralPath $temp -Destination $final -Force",
        "$app = New-Object -ComObject Shell.Application",
        f"$item = $app.NameSpace($desktop).ParseName({_ps_quote(final_name)})",
        "if ($null -eq $item) { throw 'shortcut could not be resolved' }",
        "$link = $item.GetLink",
        "Write-Output ('TARGET=' + $link.Target.Path)",
        "Write-Output ('ARGS=' + $link.Arguments)",
        "Write-Output ('WORKDIR=' + $link.WorkingDirectory)",
    ])
    return "\n".join(lines) + "\n"


# 用 UTF-16LE + Base64 传递脚本，命令行参数保持纯 ASCII，不受控制台代码页影响。
def encode_powershell(script: str) -> str:
    """把脚本编码成 powershell.exe -EncodedCommand 所需的参数。"""
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


# 把 PowerShell 的 CLIXML 错误输出还原成可读文本，失败时给用户看得懂的提示。
def clean_powershell_error(text: str) -> str:
    """从标准错误里提取错误行，CLIXML 序列化内容按行拆开并去掉转义。"""
    raw = (text or "").strip()
    if not raw:
        return ""
    if "#< CLIXML" in raw:
        messages = [
            match.replace("_x000D__x000A_", "\n").strip()
            for match in re.findall(r'<S S="Error">(.*?)</S>', raw, flags=re.DOTALL)
        ]
        joined = "\n".join(message for message in messages if message)
        if joined:
            return joined
    return raw.splitlines()[0]


# 执行编码后的脚本并返回其标准输出；窗口隐藏，避免初始化时闪出控制台。
def _run_powershell(script: str) -> str:
    """运行 PowerShell 脚本并返回标准输出。"""
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-EncodedCommand",
            encode_powershell(script),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=CREATE_NO_WINDOW,
    )
    if completed.returncode != 0:
        message = clean_powershell_error(completed.stderr) or clean_powershell_error(completed.stdout)
        raise RuntimeError(message or f"powershell exited with {completed.returncode}")
    return completed.stdout.strip()


# 解析脚本回读结果，确认快捷方式确实指向预期的目标与参数。
def parse_verification(output: str) -> dict[str, str]:
    """把 TARGET=/ARGS=/WORKDIR= 回读行解析成字典。"""
    result: dict[str, str] = {}
    for line in output.splitlines():
        key, sep, value = line.partition("=")
        if sep and key in {"TARGET", "ARGS", "WORKDIR"}:
            result[key] = value
    return result


# 创建桌面快捷方式，返回生成的 .lnk 路径；图标缺失时退回目标程序自带图标。
def create_desktop_shortcut(
    name: str = DEFAULT_NAME,
    target: Path = VENV_PYTHONW,
    arguments: str = "launch.py",
    working_directory: Path = BASE_DIR,
    description: str = DEFAULT_DESCRIPTION,
    icon: Path | None = DEFAULT_ICON,
) -> Path:
    """创建或覆盖桌面快捷方式，返回 .lnk 完整路径。"""
    if not Path(target).exists():
        raise FileNotFoundError(f"shortcut target is missing: {target}")
    icon_path = prepare_icon(icon)
    script = build_shortcut_script(
        name=name,
        target=str(target),
        arguments=arguments,
        working_directory=str(working_directory),
        description=description,
        icon=str(icon_path) if icon_path else None,
        temp_name=f".dsh-link-{os.getpid()}.lnk",
    )
    verification = parse_verification(_run_powershell(script))
    if Path(verification.get("TARGET", "")) != Path(target) or verification.get("ARGS") != arguments:
        raise RuntimeError(f"shortcut verification failed: {verification}")
    desktop = Path(_run_powershell("[Environment]::GetFolderPath('Desktop')").strip())
    shortcut_path = desktop / f"{validate_shortcut_name(name)}.lnk"
    if not shortcut_path.exists() or shortcut_path.stat().st_size == 0:
        raise RuntimeError(f"shortcut was not created: {shortcut_path}")
    return shortcut_path


def main(argv: list[str] | None = None) -> int:
    """解析命令行参数并创建桌面快捷方式。"""
    parser = argparse.ArgumentParser(description="Create the desktop pet shortcut.")
    parser.add_argument("--name", default=DEFAULT_NAME, help="shortcut file name without .lnk")
    parser.add_argument("--icon", default=str(DEFAULT_ICON), help="ico file used by the shortcut")
    parser.add_argument("--no-icon", action="store_true", help="ignore the icon file")
    parser.add_argument("--target", default=str(VENV_PYTHONW), help="executable the shortcut runs")
    parser.add_argument("--arguments", default="launch.py", help="arguments passed to the target")
    parser.add_argument("--working-directory", default=str(BASE_DIR), help="shortcut working directory")
    args = parser.parse_args(argv)

    icon = None if args.no_icon else Path(args.icon)
    try:
        path = create_desktop_shortcut(
            name=args.name,
            target=Path(args.target),
            arguments=args.arguments,
            working_directory=Path(args.working_directory),
            icon=icon,
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Failed to create the desktop shortcut: {error}", file=sys.stderr)
        return 1
    print("Desktop shortcut created:")
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
