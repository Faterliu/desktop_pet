from __future__ import annotations

import sys
import traceback
from pathlib import Path


BOOT_LOG_NAME = "startup_bootstrap.log"


# 在程序极早期写入启动日志，便于排查导入前后的静默退出问题。
def _write_boot_log(project_root: Path, message: str) -> None:
    """在程序极早期写入启动日志，便于排查导入前后的静默退出问题。"""
    data_dir = project_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    log_path = data_dir / BOOT_LOG_NAME
    with log_path.open("a", encoding="utf-8") as file:
        file.write(f"{message}\n")


# 初始化应用、创建桌宠主窗口并启动事件循环。
def main() -> int:
    """初始化应用、创建桌宠主窗口并启动事件循环。"""
    project_root = Path(__file__).resolve().parent
    _write_boot_log(project_root, "[boot] entering main()")

    try:
        from PySide6.QtWidgets import QApplication

        from app.desktop_pet_window import DesktopPetWindow
        from utils.logger import configure_logging

        _write_boot_log(project_root, "[boot] imports completed")
        configure_logging()
        _write_boot_log(project_root, "[boot] logging configured")

        app = QApplication(sys.argv)
        app.setQuitOnLastWindowClosed(False)
        app.setApplicationName("小桃 Desktop Pet")
        _write_boot_log(project_root, "[boot] QApplication created")

        window = DesktopPetWindow(project_root)
        _write_boot_log(project_root, "[boot] DesktopPetWindow created")
        window.show()
        window.raise_()
        window.activateWindow()
        _write_boot_log(project_root, "[boot] window shown")
        return app.exec()
    except Exception:  # noqa: BLE001
        error_text = traceback.format_exc()
        _write_boot_log(project_root, "[boot] startup failed")
        _write_boot_log(project_root, error_text)
        print(error_text, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
