from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from app.desktop_pet_window import DesktopPetWindow
from utils.logger import configure_logging


def main() -> int:
    """初始化应用、创建桌宠主窗口并启动事件循环。"""
    configure_logging()
    app = QApplication(sys.argv)
    app.setApplicationName("小胡 Desktop Pet")

    project_root = Path(__file__).resolve().parent
    window = DesktopPetWindow(project_root)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
