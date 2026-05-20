from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any, Iterator


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from ai.mem0_memory_service import Mem0MemoryService  # noqa: E402
from storage.json_store import load_json_prefer_primary  # noqa: E402


def iter_text_values(obj: Any) -> Iterator[str]:
    if isinstance(obj, dict):
        for value in obj.values():
            yield from iter_text_values(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from iter_text_values(value)
    elif isinstance(obj, str):
        text = obj.strip()
        if text:
            yield text


def main() -> None:
    app_config = load_json_prefer_primary(
        PROJECT_ROOT / "config" / "app_config.json",
        PROJECT_ROOT / "config" / "app_config.example.json",
        {},
    )

    service = Mem0MemoryService(app_config)
    if not service.is_available():
        print("Mem0 is not available. Enable memory.enable_mem0 first.")
        return

    memory_path = PROJECT_ROOT / "data" / "memory.json"
    if not memory_path.exists():
        print(f"No memory.json found: {memory_path}")
        return

    data = json.loads(memory_path.read_text(encoding="utf-8"))
    user_id = app_config.get("memory", {}).get("mem0_user_id", "default_user")

    seen: set[str] = set()
    imported = 0
    for text in iter_text_values(data):
        if text in seen:
            continue
        seen.add(text)
        service.add_memory_text(
            user_id=user_id,
            text=text,
            metadata={"source": "legacy_memory_json_import"},
        )
        imported += 1

    print(f"Imported {imported} memory text items into Mem0.")


if __name__ == "__main__":
    main()
