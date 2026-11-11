"""不经过脚本宿主的启动器：先做只快进更新，再把桌宠跑在同一个进程里。

使用 `pythonw.exe launch.py` 启动可以避开 `.vbs` 的「打开文件 - 安全警告」，
同时保留 `start_main.vbs` 原有的三件事：写启动日志、自动 `git pull --ff-only`、
把标准输出和异常都落到 `data/start_main_error.log`。
"""

from __future__ import annotations

import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent
DATA_DIR = BASE_DIR / "data"
# 独立日志：start_main.vbs 的 cmd 重定向会独占 start_main_error.log，两者不能同时追加。
ERROR_LOG = DATA_DIR / "launch.log"


def _write(handle, text: str) -> None:
    """写入一行日志并立即刷新，保证进程异常退出时内容不丢。"""
    handle.write(text)
    handle.flush()


def _git_pull(handle) -> int:
    """在仓库根目录执行只快进拉取，输出直接写入启动日志。"""
    try:
        result = subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as error:
        _write(handle, f"Warning: git pull could not run: {error}\n")
        return 1
    output = (result.stdout or "").strip()
    if output:
        _write(handle, output + "\n")
    return result.returncode


def _start_pet(handle) -> int:
    """在启动日志接管标准输出的前提下运行业务入口。"""
    sys.path.insert(0, str(BASE_DIR))
    if "--check" in sys.argv[1:]:
        import main as pet_main

        _write(handle, f"check ok: main.main={callable(getattr(pet_main, 'main', None))}\n")
        return 0
    import main as pet_main

    return int(pet_main.main())


def main() -> int:
    """执行启动检查并运行业务入口，返回退出码。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with ERROR_LOG.open("a", encoding="utf-8", buffering=1) as handle:
        _write(
            handle,
            f"Desktop Pet startup check\nTime: {datetime.now():%Y/%m/%d %H:%M:%S}\n\n",
        )
        _write(handle, "Updating current git branch...\n")
        code = _git_pull(handle)
        if code != 0:
            _write(handle, f"Warning: git pull --ff-only failed with code {code}. Continuing startup.\n")
        _write(handle, "Starting main.py...\n")
        sys.stdout = handle
        sys.stderr = handle
        try:
            return _start_pet(handle)
        except BaseException:  # noqa: BLE001 - 启动阶段任何异常都要留在日志里
            _write(handle, traceback.format_exc())


if __name__ == "__main__":
    raise SystemExit(main())
