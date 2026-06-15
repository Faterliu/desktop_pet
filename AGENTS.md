# AGENTS.md

Project handoff notes for future AI coding agents. This file is meant to be read quickly before changing the repository; keep it concise and grounded in the current code.

## 5-Minute Overview

- Project: Windows desktop AI pet prototype built with Python and PySide6.
- App root: `desktop_pet/`.
- Entry point: `desktop_pet/main.py`.
- Main coordinator: `desktop_pet/app/desktop_pet_window.py`.
- Default config template: `desktop_pet/config/app_config.example.json`.
- Runtime user data: `desktop_pet/config/app_config.json`, `desktop_pet/data/`, logs, caches, and virtual environments must not be committed.
- Tests: `desktop_pet/tests/` uses `unittest`; there is no pytest, packaging, formatter, lint, or CI setup.
- Older planning and asset notes live under `xiaohu_codex_package/xiaohu_codex/`.

## Run And Setup

First launch:

```powershell
cd desktop_pet
.\setup_env.bat
```

Daily terminal-free startup:

```powershell
cd desktop_pet
wscript.exe .\start_main.vbs
```

Manual startup:

```powershell
cd desktop_pet
py -m pip install -r requirements.txt
py main.py
```

Use `py` / `py -m pip` on Windows. Do not assume `python` or `pip` points to the intended interpreter; they may be Microsoft Store aliases or old launchers.

Startup diagnostics:

- `desktop_pet/data/startup_bootstrap.log` is written before importing PySide6.
- `desktop_pet/data/app.log` contains normal app logs.
- `start_main.vbs` reads `data/runtime_python.txt`, runs `git pull --ff-only` best-effort, then launches `main.py` hidden. Failures are logged to `data/start_main_error.log`.

## Core Behavior

- Transparent, borderless, always-on-top desktop character window.
- Sprite animation from `desktop_pet/assets/spritesheet.webp` and `desktop_pet/assets/sprite_config.json`.
- Click opens a floating chat input; double-click triggers reply or proactive-feedback behavior.
- Right-click menu controls testing entries, reload config, scaling, do-not-disturb, always-on-top, autonomous movement, API chat, formal Q&A, cleanup, and exit.
- Chat can use local scripted replies or the DeepSeek OpenAI-compatible Chat Completions API.
- Local JSON stores keep chat history, summaries, memory, usage counters, generated local lines, and window position.
- Optional Mem0 / DashScope-backed long-term semantic memory is off by default and must degrade gracefully.
- Proactive behavior includes startup greetings, idle greetings, scenario-based greetings, knowledge greetings, time-period greetings, and low-interruption fallback. Knowledge greetings no longer show a local intro line before the generated content.

## Key Files

`desktop_pet/main.py`

- Application entry. Writes early boot logs, imports PySide6, configures logging, creates `QApplication`, then shows `DesktopPetWindow`.
- Avoid importing business modules before early startup diagnostics.

`desktop_pet/app/desktop_pet_window.py`

- Main UI and flow coordinator: window flags, mouse/menu events, chat flow, background worker wiring, formal Q&A panels, bubbles, movement, topmost enforcement, config reload, and exit animation.
- Large and stateful. Be careful around `QThread` lifecycle, `closeEvent()`, chat pending state, timers, topmost state, formal/informal mode, and floating-widget positioning.

`desktop_pet/app/background_task_registry.py`

- Central lifecycle manager for `QThread`/worker pairs. Use it for new background tasks instead of ad hoc thread cleanup.

`desktop_pet/app/chat_flow_controller.py`

- Non-UI chat-flow helper. It prepares local/API branches, formal/informal snapshots, worker args, and persistence decisions. It must not create widgets or call the model directly.

`desktop_pet/app/config_service.py`

- Read-only dot-path config helper. It does not load, save, migrate, or write config.

`desktop_pet/app/bubble_position_service.py`

- Pure positioning service for speech and reply bubbles. Keep QWidget creation and display timing outside this module.

`desktop_pet/app/history_clear_worker.py`

- Background worker for forced summarization, history clearing, and `last_cleaned_at` updates. It must not touch QWidget objects directly.

`desktop_pet/app/message_splitter.py`

- Plain-text helper for splitting knowledge-greeting replies into at most two bubble segments.

`desktop_pet/app/context_menu.py`

- Builds the right-click menu. New menu items usually require both this file and callback wiring in `DesktopPetWindow`.

`desktop_pet/app/chat_input.py`, `speech_bubble.py`, `formal_answer_panel.py`

- Floating input, message bubbles, reply bubble, and formal Q&A panels. Keep topmost/follow-position behavior synchronized with the main window.

`desktop_pet/animation/sprite_player.py`

- Loads sprite config and atlas, crops frames, advances actions with `QTimer`, emits `frame_changed`. Action names must match `assets/sprite_config.json`.

`desktop_pet/ai/deepseek_client.py`

- Calls `base_url + /chat/completions` with `requests.post()`. Handle missing keys, API errors, timeout, and response-shape differences.

`desktop_pet/ai/prompt_builder.py`

- Builds system prompt, safety rules, character settings, formal/informal instructions, summaries, local memory, optional Mem0 retrieval, and recent context. Safety and expression constraints should remain high priority.

`desktop_pet/ai/context_manager.py`, `summarizer.py`

- Context selection and summarization/memory extraction. Summarization must tolerate API failure and should not block normal chat.

`desktop_pet/ai/mem0_memory_service.py`

- Optional semantic memory wrapper. Missing DashScope key, missing dependency, or service failure should log and degrade without blocking startup, chat, summarization, or exit.

`desktop_pet/character/behavior_controller.py`

- Startup greetings, idle proactive lines, time-period checks, dynamic greeting intervals, local line selection, and proactive response ratio updates.

`desktop_pet/character/proactive_context.py`

- Pure logic for scenario-greeting context, local fallback templates, and API prompt messages. No UI, threads, or network calls here.

`desktop_pet/storage/*.py`

- JSON persistence, chat stores, memory stores, local line service, usage counters, and memory-vector index. Preserve compatibility with existing user data. Local line API refresh is configured per `local_lines.json` group under `local_lines_refresh.groups`; all groups default to disabled and use a 14-day interval unless overridden.

`desktop_pet/utils/logger.py`, `utils/log_sanitizer.py`

- Rotating logs and privacy-safe logging helpers. Do not log full prompts, API keys, memory contents, model replies, or raw API payloads.

## Common Edit Paths

- Startup or silent launch failure: start with `main.py`, `setup_env.bat`, `start_main.vbs`, `utils/logger.py`, and startup logs.
- Chat behavior: inspect `desktop_pet_window.py`, `chat_flow_controller.py`, `ChatWorker`, `deepseek_client.py`, `prompt_builder.py`, `context_manager.py`, and `summarizer.py`.
- Formal Q&A: inspect `desktop_pet_window.py`, `chat_flow_controller.py`, `formal_answer_panel.py`, dual chat stores, and prompt mode handling.
- Proactive greetings and local line refresh: inspect `behavior_controller.py`, `proactive_context.py`, `DesktopPetWindow` worker callbacks, `local_lines_service.py`, `local_lines.json`, and `config/app_config.example.json`.
- Memory changes: inspect `memory_store.py`, `summarizer.py`, `prompt_builder.py`, `mem0_memory_service.py`, `memory_vector_store.py`, and related tests.
- Bubbles and positioning: inspect `speech_bubble.py`, `bubble_position_service.py`, `chat_input.py`, and `_sync_floating_widgets()`.
- Background work: use `background_task_registry.py`; verify duplicate task handling and shutdown behavior.
- Config changes: update both code and `config/app_config.example.json`; never commit real keys or local `app_config.json`.
- Sprites/actions: update `sprite_config.json`, assets, `SpritePlayer`, and all action call sites together.

## Project Conventions

- Prefer small services with pure logic where possible; keep QWidget creation and signal wiring in UI modules.
- Keep long-running work off the Qt main thread.
- Background workers should report back through signals; UI updates must happen in the main window/main thread.
- Configuration reads may use `ConfigService`; writes should preserve the existing JSON structure and save paths.
- JSON stores should remain crash-tolerant and backward compatible.
- Example configs and docs must not contain real API keys.
- Runtime data, logs, caches, virtual environments, Qdrant data, and generated local user state are ignored and should stay ignored.
- When editing this file, update the relevant section directly. Do not add a sync log or changelog section.

## High-Risk Areas

- `desktop_pet_window.py`: many UI states and timers interact; regressions can appear only during exit, reload, or background task completion.
- `closeEvent()` and worker cleanup: avoid unbounded waits and avoid callbacks mutating UI during shutdown.
- `json_store.py`: affects all runtime persistence; preserve atomic write, backup, corrupt-file recovery, and old data compatibility.
- `app_config.example.json`: missing defaults can break first launch on new devices.
- `PromptBuilder`, `Summarizer`, `DeepSeekClient`: affect safety, privacy, token budget, formal/informal routing, and model failures.
- `Mem0MemoryService` and memory-vector logic: optional external services must not become startup or chat blockers.
- `SpritePlayer` and `sprite_config.json`: atlas layout, frame counts, action names, and UI call sites are coupled.
- `.gitignore`: do not unignore user data, logs, caches, or real config.

## Common Commands

Install dependencies:

```powershell
cd desktop_pet
py -m pip install -r requirements.txt
```

Run tests:

```powershell
py -m unittest discover -s desktop_pet/tests
```

Check Python syntax without writing `__pycache__`:

```powershell
@'
import ast
from pathlib import Path
for path in Path("desktop_pet").rglob("*.py"):
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    print(f"OK {path}")
'@ | py -3 -B -
```

Check JSON validity:

```powershell
@'
import json
from pathlib import Path
for path in Path("desktop_pet").rglob("*.json"):
    json.loads(path.read_text(encoding="utf-8"))
    print(f"OK {path}")
'@ | py -3 -B -
```

Inspect logs:

```powershell
Get-Content .\desktop_pet\data\startup_bootstrap.log -Tail 80
Get-Content .\desktop_pet\data\app.log -Tail 80
```

Inspect current changes:

```powershell
git status --short
git diff -- AGENTS.md
```

## Dependencies And Services

Dependencies are in `desktop_pet/requirements.txt`.

- `PySide6-Essentials`: QtCore, QtGui, QtWidgets for the desktop UI. Avoid switching to full PySide6 unless a required module proves necessary.
- `requests`: DeepSeek and embedding HTTP calls.
- `mem0ai==2.0.2`: optional semantic memory SDK. Keep imports and initialization failure-tolerant.

External services:

- DeepSeek API: default base URL `https://api.deepseek.com`, path `/chat/completions`.
- DashScope / Alibaba Cloud Bailian embeddings: default base URL `https://dashscope.aliyuncs.com/compatible-mode/v1`, model `text-embedding-v4`, dimension 1024.
- Keys come from config or environment variables. Never commit real keys.

## Open Questions

- No packaging plan exists yet; source-code execution is the current assumption.
- `ai/safety_filter.py` exists but is not wired into the main chat flow.
- Some reserved character-state modules are present but not clearly used by the main flow.
- Some Chinese text may display incorrectly in PowerShell depending on terminal encoding; verify whether the source file itself is affected before changing text.
