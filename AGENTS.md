# AGENTS.md

Project handoff document for future AI coding agents. This is not a regular README; it is meant to let an agent entering this repository for the first time know, within five minutes, what to read first, where to make changes, and which areas should not be touched casually.

## 5-Minute Quick Overview

- One-sentence overview: This is a Windows desktop AI pet prototype built with Python and PySide6. The character is displayed on the desktop through a pixel spritesheet, can chat, proactively greet the user, save local JSON data, and call the DeepSeek API.
- The runnable application lives under `desktop_pet/`, and the entry point is `desktop_pet/main.py`. The root `README.md` is a changelog, and `xiaohu_codex_package/xiaohu_codex/` contains early requirements, task notes, and asset documentation.
- For the first launch, run `desktop_pet/setup_env.bat` to create the project-local virtual environment and install dependencies. After that, daily startup should use `desktop_pet/start_main.vbs` for terminal-free launch. Manual startup is still available by running `cd desktop_pet`, then `py -m pip install -r requirements.txt` and `py main.py`. Do not trust `python` or `pip` by default, because on Windows they may point to Microsoft Store aliases or old interpreters.
- The main coordinator is `desktop_pet/app/desktop_pet_window.py`. Most UI, chat, configuration, animation, auto-movement, formal Q&A, and exit flows are wired together from there.
- Runtime personalized data should not be committed: `desktop_pet/config/app_config.json`, `desktop_pet/data/`, logs, and caches are ignored by `.gitignore`. The default configuration template is `desktop_pet/config/app_config.example.json`.
- There is currently no standalone test framework, build script, or packaging flow, but `desktop_pet/tests/` contains `unittest` regression tests. Common checks are running `python -m unittest discover -s desktop_pet/tests` in the project-local virtual environment, validating JSON, checking Python AST/syntax, and manually running the desktop pet.
- After each code change by an agent, check whether this file needs to be updated. If the change touches directory structure, core flows, APIs, data structures, configuration keys, dependencies, test methods, build methods, or project conventions, update the "Documentation Sync Log" at the bottom of this file.

## 1. One-Sentence Project Overview

`desktop_pet` is a local Windows desktop AI companion pet application: it uses PySide6 to create a transparent, borderless, always-on-top window that displays a pixel character and interacts with the user through local scripted lines or the DeepSeek Chat Completions API.

## 2. Main Goals and Run Methods

The main goals come from `xiaohu_codex_package/xiaohu_codex/PROJECT_REQUIREMENTS.md` and the current code implementation:

- Display a transparent desktop character window, with support for dragging, position persistence, a right-click menu, and exit.
- Crop and play animation frames from `assets/spritesheet.webp` and `assets/sprite_config.json`.
- Open a chat input box when the character is clicked, supporting either local replies or DeepSeek API replies.
- Save chat history, summaries, memory, daily usage counters, and window position under `desktop_pet/data/`.
- Support startup greetings, idle proactive lines, do-not-disturb mode, autonomous movement, character scaling, and formal Q&A mode.

Run method:

```powershell
cd desktop_pet
py -m pip install -r requirements.txt
py main.py
```

Quick startup:

```powershell
cd desktop_pet
.\setup_env.bat
wscript.exe .\start_main.vbs
```

Notes:

- `python main.py` is reliable only when `python` points to a real interpreter. During earlier migration debugging, when `python` pointed to `Microsoft\WindowsApps\python.exe`, the result was no output, no window, and no `data/` directory.
- `pip install -r requirements.txt` may hit a broken `pip.exe` launcher from an old Python version. Prefer `py -m pip install -r requirements.txt`.
- `setup_env.bat` handles environment preparation: it only accepts interpreters that can run `python -m pip --version` and support `venv`; it first looks for Miniforge, then CPython 3.13 installed by `uv`, then `py -3.13`, `py -3`, and the current `python`. If none are usable, it attempts to install Python through `winget install --id Python.Python.3.13 -e --source winget --accept-package-agreements --accept-source-agreements`. It then creates the project-local `desktop_pet/.desktop_pet_venv`, installs dependencies into that local environment, and writes `.desktop_pet_venv/Scripts/python.exe` without a trailing newline to `data/runtime_python.txt`. This script no longer installs project dependencies into the global Python environment.
- `start_main.vbs` is the default terminal-free startup entry: it first runs `git pull --ff-only` from the repository root to try to pull the latest code for the current branch, then reads `data/runtime_python.txt`, strips carriage returns, newlines, tabs, and BOM, verifies that the Python path exists, and directly runs `main.py` hidden. Output is written to `data/start_main_error.log`; pull failures only write a warning and continue startup. Only missing environment or a nonzero `main.py` exit opens an error terminal and displays the log. Dependency completeness is validated by `setup_env.bat`; daily startup no longer performs an extra `import PySide6, requests` smoke check.
- After startup, the program should create `desktop_pet/data/startup_bootstrap.log` and `desktop_pet/data/app.log`. The former is written before importing PySide6 and is used for early startup diagnostics.

## 3. Key Directories and Files

`desktop_pet/main.py`

- Program entry point. It first writes `data/startup_bootstrap.log`, then imports PySide6, configures logging, and creates `QApplication` and `DesktopPetWindow`.
- Change scenarios: startup failure diagnostics, Qt application lifecycle, window display, and event loop strategy.
- Risk: importing business modules too early weakens the diagnostic value of the early startup log.

`desktop_pet/app/desktop_pet_window.py`

- Core coordinator. It handles window attributes, mouse events (single-click chat, double-click reply/greeting, drag movement, right-click menu including the always-on-top toggle), chat flow, background threads, formal Q&A panels, auto-movement, position restore, and the exit animation (plays `waving` and shows a `farewell` goodbye bubble on exit).
- `_enforce_topmost()` is driven every 30 seconds by `_topmost_enforcement_timer`, and uses `force_window_topmost()` at the Windows API level to force `WS_EX_TOPMOST`, preventing frequent `setMask()` calls from causing the system to clear the topmost style.
- When `_sync_floating_widgets()` makes bubbles/input boxes follow the character position, the main window still determines which floating widgets are visible, but bubble target coordinates are calculated by `BubblePositionService`. The main window only passes the other visible bubble's `geometry()` as `exclusion_rects` into the service and moves `SpeechBubble` / `ReplyBubble`, so the two bubbles avoid overlapping. The chat input box still uses `ChatInput.reposition()`.
- When an idle proactive greeting hits scenario-based generation, `BehaviorController` emits `scenario_greeting_requested`, and the main window creates a `ScenarioGreetingWorker` in a separate `QThread` to call DeepSeek and generate one short greeting. If the API is unavailable, the thread is busy, or generation fails, it silently falls back to a local template and does not display an error to the user.
- Clearing formal/informal chat history no longer forces summarization on the UI thread. Instead, it creates a `ChatHistoryClearWorker` in a separate `QThread` to run summarization, clearing, and `last_cleaned_at` updates; the main window only receives completion/failure signals and decides after the background operation whether to display a result.
- `BackgroundTaskRegistry` centrally registers chat tasks, history clearing, Mem0 initialization/search, semantic memory maintenance, local line refresh, and other `QThread` background tasks. Duplicate registration with the same name is rejected to avoid repeated concurrency. On exit, `closeEvent()` centrally requests background threads to stop and performs bounded `wait()` according to task configuration; timed-out tasks log a warning and shutdown continues, avoiding unbounded waits.
- `ConfigService` wraps low-risk configuration reads inside the main window, including default values and nested-field reads. Config write-back still stays on the main window's existing `setdefault()` paths to avoid changing the `app_config.json` structure or persistence behavior.
- Change scenarios: almost all user-visible behavior entry points are wired here.
- Risk: this file is large and many states interact, including `chat_thread`, `clear_history_thread`, `move_animation`, `behavior_controller`, `formal_answer_panels`, `exit_animation_in_progress`, `_close_after_workers_finished`, `_click_timer`, `_suppress_click`, `_waiting_timer`, `_pending_was_formal`, and `_topmost_enforcement_timer`.

`desktop_pet/app/history_clear_worker.py`

- Background cleanup worker. `ChatHistoryClearWorker.run()` runs off the UI thread, force-summarizes according to config, clears the corresponding `ChatStore`, and updates `last_cleaned_at`.
- Change scenarios: clearing chat history, summarizing before clearing, cleanup failure fallback.
- Risk: the worker must not directly operate on any QWidget or bubble; UI display must remain in `DesktopPetWindow` signal callbacks.

`desktop_pet/app/background_task_registry.py`

- Lightweight background task registry. It centrally registers, unregisters/removes, queries, and stops `QThread`/worker pairs, and handles `quit()`, bounded `wait()`, necessary `terminate()`, `deleteLater()`, and cleanup callbacks.
- Main interfaces include `register(name, thread, worker, cleanup=None, wait_timeout_ms=None)`, `unregister(name)`, `is_running(name)`, `request_quit_all(timeout_ms=None)`, `clear_finished()`, and `stop_all()`; `remove()` remains as a compatibility alias path.
- Change scenarios: adding background `QThread` tasks, adjusting exit wait timeouts, debugging duplicate concurrent tasks or thread leaks.
- Risk: the registry only manages lifecycle and should not contain specific business logic; success/failure signals from business workers are still handled by `DesktopPetWindow`.

`desktop_pet/app/bubble_position_service.py`

- Bubble position calculation service. It centralizes candidate positions for normal bubbles and knowledge-greeting reply bubbles relative to the desktop pet window, clamps to available screen area, avoids covering the desktop pet, and uses `exclusion_rects` to avoid another visible bubble.
- `DesktopPetWindow._sync_floating_widgets()` uses this service to calculate target coordinates and then calls bubble `move()`. Bubble creation, display, hiding, timed close, and style remain in `SpeechBubble` / `ReplyBubble` and the original display methods on the main window.
- Change scenarios: adjusting bubble priority above/below/left/right of the desktop pet, screen-edge avoidance strategy, or mutual exclusion rules between two bubbles.
- Risk: do not introduce chat, proactive greeting, QThread, or QWidget creation logic here; it should remain a position calculation service that is easy to unit test.

`desktop_pet/app/config_service.py`

- Lightweight configuration read service. `ConfigService` is based on the in-memory configuration dictionary and supports `get(path, default=None)`, `get_bool()`, `get_int()`, and `get_str()`, where `path` uses dot-separated nested paths such as `api.enable_chat_api` or `ui.bubble_durations_ms.assistant_reply`.
- Change scenarios: repeated read-only configuration access in the main window or other modules, default fallbacks, and nested-field reads.
- Risk: this service is not responsible for loading, saving, or migrating configuration, and should not change the structure of `app_config.json` / `app_config.example.json`; configuration writes should still use the existing save paths.

`desktop_pet/app/chat_flow_controller.py`

- Lightweight chat-flow coordinator. `ChatFlowController` does not create QWidget objects, switch actions, or start `QThread`; it only helps `DesktopPetWindow` manage normal/formal Q&A mode snapshots, current user-message persistence, local-reply or missing-API-config branching, `ChatWorker` argument dictionaries, assistant-message persistence after success/failure, and pending state.
- Change scenarios: adjusting non-UI state in the user chat flow, formal/informal chat-history routing, local-reply/API request branching, and preventing duplicate chat tasks with the same name.
- Risk: do not introduce `DeepSeekClient.chat()` calls, `PromptBuilder` changes, `ContextManager` changes, bubble/formal-answer-panel display, or thread lifecycle management here; those remain the responsibility of `ChatWorker` and `DesktopPetWindow`.

`desktop_pet/app/message_splitter.py`

- Local message display splitting helper. `split_knowledge_bubble_text()` splits a full knowledge-greeting model reply into at most two segments using Chinese sentence-ending punctuation such as full stops, question marks, exclamation marks, and semicolons; if the first segment is too short, it merges the next sentence, and single-sentence text or text that cannot be split safely is kept unchanged.
- Change scenarios: adjusting knowledge-greeting bubble display rhythm, split punctuation, minimum first-segment length, or maximum displayed segments.
- Risk: this module only handles plain-text splitting and should not introduce QWidget, QTimer, API calls, or chat-record persistence logic.

`desktop_pet/app/context_menu.py`

- Builds the right-click menu, including the test menu (controlled by `ui.show_test_menu`, default off), the cleanup menu (controlled by `ui.show_clear_menu`, default off, can separately clear informal and formal chat history), reload configuration (controlled by `ui.show_reload_config`, default on), character scaling, do-not-disturb, window always-on-top, autonomous movement, chat API toggle, formal Q&A mode, and exit.
- Change scenarios: adding menu items or changing menu visibility entry points.
- Note: menu callbacks are injected by `DesktopPetWindow._show_context_menu()`. New menu items usually need changes in both places.

`desktop_pet/app/chat_input.py`

- Floating chat input box that follows the character position; Enter or the send button submits, and the close button hides it.
- Change scenarios: input box layout, submit behavior, close behavior, follow-position logic.

`desktop_pet/app/speech_bubble.py`

- Short message bubble that auto-closes and follows the character position. Before `show_message()`, the main window calls `set_always_on_top()` to synchronize the topmost state.
- Bubble style, auto-close, click signal, transparent-window fixes, and window mask remain in this module; when the main window synchronizes positions for two visible bubbles, target coordinates are calculated by `BubblePositionService`.
- `SpeechBubble.reposition()` and `ReplyBubble.reposition()` remain as each bubble component's own follow-position interface, to avoid breaking existing display calls and external call conventions.
- `ReplyBubble`: an independent right-side reply bubble for knowledge greetings. It is clickable, has no tail, uses a green color scheme, and emits a `clicked` signal for the main window to handle user responses.
- Change scenarios: display style and positioning for local prompts, normal chat replies, and system prompts; adding new bubble directions or avoidance rules.

`desktop_pet/app/formal_answer_panel.py`

- Draggable, copyable, closable text panel used by formal Q&A mode.
- Change scenarios: full-answer display, appending multiple answers, panel lifecycle, and copy experience.
- Risk: objects should be fully released after closing. Currently `WA_DeleteOnClose` and a `destroyed` callback let the main window remove references.

`desktop_pet/animation/sprite_player.py`

- Reads sprite configuration and the atlas, crops action frames, advances frames with `QTimer`, and emits `frame_changed`.
- Change scenarios: action playback, frame rate, scaling, and missing-asset fallback.
- The current minimum action frame interval is `400ms`.

`desktop_pet/assets/sprite_config.json`

- Defines crop parameters and action rows for `spritesheet.webp`: `idle`, `running_right`, `running_left`, `waving`, `jumping`, `failed`, `waiting`, `running`, and `review`.
- Change scenarios: adding actions, changing frame counts, changing rows/columns, replacing assets.
- Risk: it must match the actual spritesheet layout.

`desktop_pet/ai/deepseek_client.py`

- Uses `requests.post()` to call the OpenAI-compatible `base_url + /chat/completions`.
- Change scenarios: model service parameters, timeout, error messages, response-structure compatibility.
- Config dependencies: `api.base_url`, `api.model`, `api.api_key`, `api.timeout_seconds`.

`desktop_pet/ai/mem0_memory_service.py`

- Optional Mem0 long-term semantic memory wrapper. It initializes Mem0, writes long-term memories extracted from summaries, retrieves relevant memories based on the current user input, and formats them as injectable prompt text.
- Controlled by configuration keys in `config/app_config.json` / `app_config.example.json`, including `memory.enable_mem0`, `memory.inject_mem0_to_prompt`, `memory.use_mem0_for_knowledge_speak`, `memory.mem0_search_top_k`, and `memory.write_sensitive_memory`; default is off.
- If `memory.enable_mem0` is true but the DashScope embedding key is empty, the service logs info and directly degrades to unavailable without importing `mem0` or creating Qdrant/history directories, avoiding startup warnings, extra directory creation, and initialization delay. Only when `memory.dashscope_api_key` exists or the environment variable named by `memory.dashscope_api_key_env` exists will it continue to initialize with `Memory.from_config()`. The main window no longer constructs or rebuilds Mem0 directly on the UI thread; startup and config reload use `Mem0InitializationWorker` in a separate `QThread`, then return to the main thread to replace `mem0_memory_service` and synchronize it to both `Summarizer` instances.
- Initialization uses `Memory.from_config(config)`, with the LLM provider fixed to Mem0's officially supported `deepseek` provider. By default it reuses the project's existing `api.api_key`, `api.base_url`, and `api.model`; if `memory.mem0_deepseek_model` or `memory.mem0_deepseek_base_url` is non-empty, values under the memory node take priority.
- The Mem0 embedder uses the DashScope / Alibaba Cloud Bailian OpenAI-compatible embeddings API, internally passing `openai_base_url` and `embedding_dims` through Mem0's OpenAI embedder. The default base URL is `https://dashscope.aliyuncs.com/compatible-mode/v1`, the model is `text-embedding-v4`, and the dimension is 1024.
- DashScope API key priority: read `memory.dashscope_api_key` first; if empty, read the environment variable specified by `memory.dashscope_api_key_env`, defaulting to `DASHSCOPE_API_KEY`. Example configuration and documentation must not contain real keys.
- The default Qdrant vector-store path is `desktop_pet/data/mem0_qdrant`, and the history SQLite path is `desktop_pet/data/mem0_history.db`; it explicitly uses 1024 dimensions to avoid mismatch with Mem0's default 1536 dimensions.
- Change scenarios: replacing the memory backend, adjusting retrieval top_k, configuring LLM/embedder/vector store, adding memory deletion or export features.
- Risk: Mem0 may depend on external LLM or embedding services. Exceptions must degrade gracefully and must not block chat, summarization, startup, or exit flows.

`desktop_pet/ai/prompt_builder.py`

- Assembles system prompts, character settings, safety rules, formal/informal mode instructions, `memory.json` memory, optional Mem0 retrieved memory, summaries (choosing the corresponding file based on formal/informal mode), and context messages. `build_messages()` supports an optional `relevant_memories` parameter for injecting long-term semantic memories related to the current user input into the system prompt.
- Local `memory.json` injection has been split into three explicit blocks: `[User Fact Memory]` for projects, preferences, background, and current tasks; `[Interaction Style Memory]` for tone, level of detail, confirmation frequency, companionship boundaries, and other relationship/style memories, with an explicit instruction not to repeat them directly to the user; and `[Long-Term Semantic Memory Relevant to the Current Question]` for Mem0 retrieval results, to be referenced only when directly relevant to the current question. It then appends `[Expression Constraints]`, requiring the assistant not to frequently say "you previously said", not to expose implementation details such as memory.json/Mem0/databases, and to prefer the current expression if old memories conflict with the current wording.
- In formal Q&A mode, fact memory can help understand project background, while relationship memory is only used for answer structure, level of detail, and confirmation frequency, reducing small talk and companion-style padding. In normal companion chat mode, relationship memory may naturally influence tone and suggestions, but should not appear as if reading a profile.
- Change scenarios: personality, reply style, safety rule priority, formal Q&A answer strategy.
- Risk: safety rules must take priority over character `custom_prompt`.

`desktop_pet/ai/context_manager.py`

- Reads recent chat context according to configuration (choosing the corresponding store based on formal/informal mode) and determines whether the summarization trigger threshold has been reached.
- Change scenarios: context length and summary-round strategy.

`desktop_pet/ai/summarizer.py`

- Attempts to summarize history after chat. If the API is available, it asks the model to output JSON; on failure, it falls back to a local simplified summary and merges memory. `maybe_summarize()` supports a `force` parameter; when true, it skips the round-count check for use before manual chat-history clearing. However, if there are no non-empty user messages in history, it skips directly to avoid generating erroneous memory from empty chat history.
- Model summarization and model memory extraction are currently split: the summary is still generated from recent full conversation, but `memory_updates` are extracted only from user messages, preventing character/assistant replies from being mixed into `memory.json`; the summary file itself no longer persists `memory_updates`. The model memory extraction schema is compatible with older `user_profile` / `work_study` outputs and also supports the new `relationship_memory` output for recording communication preferences, interaction style, and recent interaction patterns. Relationship memory rules emphasize recording only interaction preferences and ways of relating, not psychological diagnoses, medical judgments, or personality labels.
- If model memory extraction returns a valid but empty structure with no actual text, `Summarizer` continues falling back to local rule extraction. In formal Q&A mode, local rules use the user's non-empty question as a fallback saved under `work_study.current_learning_topics`. Informal/formal mode detection must check `informal` before `formal` to avoid misclassifying `conversation_summary_informal.json` because its filename contains the substring `formal`. Current local `current_learning_topics` keywords include: study, review, knowledge, course, algorithm, question/request phrasing, how to do, how to implement, how, what is, why, and difference. Local relationship-memory fallbacks cover only a few explicit expressions: do not/no need to confirm writes `confirmation_preference=avoid_unnecessary_confirmation`; "give directly" or "actionable plan" writes `preferred_response_style=direct_actionable`; "more detailed" writes `detail_level=high`; and mentions of database/data store/mechanical memory/like a tool write an avoidance of mechanical memory expression. `memory.json` is merged and Mem0 side-write is triggered only when non-empty memory text exists, avoiding refreshes of only empty memory timestamps during chat cleanup.
- If Mem0 is enabled, `Summarizer` keeps the original `memory.json` merge logic while side-writing extracted `memory_updates` into Mem0 as a long-term semantic retrieval data source. Mem0 write failures only log warnings and must not affect summarization or the main chat flow. Summary triggering is based on batches of newly added user messages: after the first time `api.summary_trigger_rounds` is reached, the same number of additional user messages must be added since the previous `covered_message_count` before summarization triggers again, avoiding re-summarization after every round once the threshold is reached.
- Change scenarios: summary structure, memory extraction, failure fallback.
- Risk: summarization is triggered in a thread, and exceptions must not affect normal chat.

`desktop_pet/ai/safety_filter.py`

- Simple keyword-based high-risk detection function. It is not currently used directly in the main chat flow.
- Change scenarios: adding local safety pre-filtering.
- To confirm: whether it should be wired before `_handle_user_message()` or `PromptBuilder`.

`desktop_pet/character/proactive_context.py`

- Pure-logic module for scenario-based proactive greetings. `build_proactive_context()` selects a small amount of recent tasks, communication preferences, companionship boundaries, and interaction patterns from `memory.json`, avoiding passing complete memory directly to the model. `build_local_scenario_greeting()` uses `scenario_greeting_templates` or `low_interrupt` as local fallback templates. `build_scenario_greeting_messages()` builds the API prompt, requiring a single short Chinese sentence, no "according to memory" or "you previously said", and no exposure of memory.json, Mem0, database, or configuration details.
- Change scenarios: proactive-greeting context selection, local template fallback, scenario-greeting prompt rules.
- Risk: do not introduce UI, QThread, or network requests here; it should remain pure logic that is easy to unit test.

`desktop_pet/storage/*.py`

- `json_store.py`: JSON read/write infrastructure. Missing files automatically create parent directories and default files. Saves write a same-directory `.tmp` first, then `flush` + `os.fsync`, then atomically replace the target with `os.replace`; when the target file is non-empty, a `.bak` is preserved first. When reading damaged JSON, the main file is first renamed to `.corrupt.<timestamp>`, then `.bak` is preferred; if the backup is also unusable, it returns a deep copy of the default value. `cleanup_tmp_json_files()` cleans up `.tmp` files left by interrupted writes.
- `local_lines_service.py`: local line reading and controlled update interface. `LocalLinesService` supports `pick_line()`, `get_lines()`, `append_manual_line()`, `replace_generated_lines()`, `validate_lines()`, `consume_first_start_line()`, `should_refresh_generated_lines()`, and `group_metadata()`. Updates preserve the existing array structure in `local_lines.json`, use `json_store.save_json()` for atomic writes, and can record generated-line source, update time, latest refresh time, monthly refresh marker, and item count in `data/local_lines_generated_meta.json`. It is used for API-based periodic local line refresh, deduplication, length limits, seven-day/month-start refresh checks, and filtering mechanical memory expressions.
- `chat_store.py`: saves and reads formal/informal chat history (`chat_history_formal.json` / `chat_history_informal.json`) and records a `last_cleaned_at` timestamp for manual clearing.
- `memory_store.py`: saves and merges `data/memory.json`. Reads, saves, and merges pass through `normalize_memory_schema()` to maintain compatibility with older structures and fill v2 defaults: `relationship_memory.communication_style`, `relationship_memory.companionship_style`, `relationship_memory.interaction_patterns`, and `memory_meta.schema_version=2`; filling defaults preserves unknown old fields and does not clear existing user memory. Saves/merges still write UTF-8 JSON and update both top-level `last_updated` and `memory_meta.last_updated`; when merging relationship memory, updated relationship sub-blocks receive `last_updated` or `last_observed_at`.
- `memory_vector_store.py`: maintains compact machine-written `data/memory_vectors.json` for eligible `memory.json` text leaves. It uses the existing DashScope OpenAI-compatible embedding config, rounds embeddings according to `memory.memory_vector_precision`, skips texts shorter than `memory.memory_vector_min_text_length`, limits stored entries with `memory.memory_vector_max_items`, includes precision in `embedding_signature`, skips cleanly when no key or `requests` is unavailable, and supports same-field semantic duplicate merging on a two-month cadence.
- `usage_store.py`: daily proactive-line and API-proactive usage counters.
- Change scenarios: data structures, persistence strategy, runtime data compatibility.

`desktop_pet/character/behavior_controller.py`

- Manages startup greetings, idle proactive lines, and time-period change detection. A `QTimer` checks idle state and time period every 60 seconds, constrained by do-not-disturb, daily limits, idle time, and waiting-for-user-reply state.
- `_startup_greeting()` first reads `first_start.enable` from `local_lines.json`; when true, it randomly selects one line from `first_start.data` and immediately writes `enable=false` after a successful selection, making it trigger only once. If it does not hit, it keeps the original priority: seasonal greeting on the first day of each 5-day cycle (`greeting_spring`/`greeting_summer`/`greeting_autumn`/`greeting_winter`), then current time-period greeting (`greeting_morning`/`greeting_noon`/`greeting_afternoon`/`greeting_evening`/`sleepy`), then fallback to `startup`. Startup greetings are controlled by do-not-disturb and the `startup_greeting` switch, but are not blocked by the daily proactive-line limit and do not increment `local_proactive_lines_used`.
- `_maybe_idle_prompt()` and `trigger_test_speak()` mix current time-period groups into the line pool. `trigger_test_idle_prompt()` bypasses timing constraints to test the full idle logic and returns the trigger type plus a ratio string.
- `_check_period_change()` is driven every 60 seconds by `period_check_timer`; it detects time-period or season changes and immediately pops a new time-period greeting when a change occurs.
- `pick_farewell_line()` randomly selects from the `farewell` group for the exit flow.
- `pick_reply_line()` randomly selects from `break_reminder` / `comfort` / `encourage` for normal double-click replies.
- `pick_feedback_line()` randomly selects from `feedback` for user responses inside the proactive-greeting window.
- `is_within_proactive_reply_window(window_seconds=60)` checks whether the current time is within 60 seconds after the previous proactive greeting.
- `pick_ignored_line()` randomly selects from `ignored` for use when always-on-top is disabled.
- `pick_return_after_idle_line()` randomly selects from `return_after_idle` for use when always-on-top is enabled.
- `pick_waiting_line()` randomly selects from `waiting` for long-idle prompts while the chat input box is open.
- `pick_reply_ack_line()` randomly selects a short acknowledgement from `reply` after a knowledge greeting is displayed.
- `_consecutive_unanswered` drives dynamic greeting intervals: first 15min -> second 15min -> third 30min -> fourth and later random 30-60min (maximum 60min), while respecting `behavior.min_proactive_interval_minutes` as a lower bound. `notify_user_interaction()` and every successful `_maybe_idle_prompt()` greeting both reset the counter.
- `_has_memory_content()` checks whether `memory.json` contains usable memory. `_proactive_ratio()` / `_adjust_ratio()` manage the ratio of proactive-greeting content types. `notify_proactive_response()` adjusts the ratio when the user responds: response type +0.005, mutually exclusive type -0.001, still clamped to 0.3-0.7; when the main window passes `config_saver`, the adjusted `proactive_content_ratio` is persisted back to `app_config.json`.
- `behavior.max_local_lines_per_day` is read through safe integer parsing; invalid, empty, or non-positive values fall back to 10, preventing local configuration errors from causing QTimer callback exceptions.
- When `memory.use_mem0_for_knowledge_speak` is true, after the knowledge-greeting probability branch hits, `_has_memory_content()` first uses the Mem0 retrieval callback passed by the main window to determine whether long-term semantic memory exists. The main window uses `Mem0SearchWorker` in a separate `QThread` to retrieve `top_k=3` Mem0 context once and temporarily stores it for `KnowledgeSpeakWorker` reuse, avoiding duplicate retrieval between the check and generation phases and preventing the proactive-greeting timer callback from blocking the UI. While retrieval is in progress, it returns `None`, and `BehaviorController._maybe_idle_prompt()` skips this round's normal greeting fallback; after retrieval succeeds, the main window triggers the knowledge greeting. If Mem0 is unavailable or returns no results, it falls back to the original `memory.json` check.
- Scenario-based proactive greetings are controlled by `behavior.enable_scenario_greeting`, enabled by default but with a 60-minute cooldown. After basic guards pass (do-not-disturb, proactive chat switch, daily limit, dynamic interval), if consecutive unanswered greetings reach `scenario_greeting_low_interrupt_after_ignored`, it first uses a low-interruption line from `low_interrupt`; otherwise, when cooldown is over and `memory.json` contains enough recent tasks or relationship memory, it builds scenario context. If `scenario_greeting_api_enabled` is true and API proactive quota is available, it emits `scenario_greeting_requested` for the main window background worker; otherwise it uses local templates.
- Proactive-greeting bubble duration now reads `ui.bubble_durations_ms`: startup greetings use `startup_greeting`, time-period change greetings use `period_greeting`, and normal idle/test greetings use `proactive_greeting`.
- Change scenarios: proactive behavior frequency, line groups, do-not-disturb logic, time-period rules, knowledge greetings, and content ratio.

`desktop_pet/config/app_config.example.json`

- Default configuration template. Runtime first loads `config/app_config.json`; if absent, it loads this example. It includes `ui.show_test_menu` to control test-menu visibility (default `false`), `ui.show_clear_menu` to control cleanup-menu visibility (default `false`), `ui.show_reload_config` to control whether the "reload configuration" menu item is shown (default `true`), and `chat.force_summarize_before_clear` (default `true`) to control whether to force summarization before manual clearing.
- `ui.bubble_durations_ms` configures main bubble display durations: `startup_greeting`, `period_greeting`, `proactive_greeting`, and `assistant_reply`.
- `behavior.enable_scenario_greeting`, `behavior.scenario_greeting_api_enabled`, `behavior.scenario_greeting_max_chars`, `behavior.scenario_greeting_min_memory_items`, `behavior.scenario_greeting_cooldown_minutes`, and `behavior.scenario_greeting_low_interrupt_after_ignored` control scenario-based proactive greetings; defaults are conservative: enabled, limited to 80 characters, requiring at least one usable memory item, 60-minute cooldown, and low-interruption lines after 2 consecutive unanswered greetings.
- `local_lines_refresh` controls API-based periodic refresh of locally generated lines: `enabled` defaults to on, `interval_days` defaults to 7 days, `monthly_refresh` defaults to on and forces one refresh after entering a new month, `knowledge_intro_group` defaults to `knowledge_speak_intro`, and `max_items` / `max_chars` control generated item count and per-item length. The main window checks once immediately after display and `_local_lines_refresh_timer` checks again every 6 hours to see whether refresh is due; when the API is not configured or refresh is not due, it silently skips.
- `memory.enable_mem0` controls whether Mem0 long-term semantic memory is enabled; `memory.inject_mem0_to_prompt` controls whether Mem0 retrieval results are injected into chat prompts; `memory.use_mem0_for_knowledge_speak` controls whether knowledge greetings prefer Mem0; `memory.mem0_search_top_k` controls retrieval count per round; `memory.mem0_llm_provider` defaults to `deepseek`; `memory.mem0_use_app_deepseek_config` defaults to reusing the project DeepSeek config; `memory.mem0_deepseek_model` / `memory.mem0_deepseek_base_url` can override model and base URL; `memory.mem0_embedder_provider` defaults to `dashscope_openai_compatible`, using the DashScope / Alibaba Cloud Bailian OpenAI-compatible embeddings API with `text-embedding-v4` and 1024-dimensional vectors; `memory.dashscope_api_key` / `memory.dashscope_api_key_env` control the DashScope key source; `memory.write_sensitive_memory` defaults to false to avoid automatically saving sensitive long-term memories in emotional companionship scenarios.
- `memory.enable_memory_vectors` controls local vector indexing for `memory.json`; `memory.memory_vector_precision`, `memory.memory_vector_min_text_length`, and `memory.memory_vector_max_items` control vector file size; `memory.enable_semantic_memory_merge`, `memory.semantic_merge_interval_days`, and `memory.semantic_duplicate_similarity_threshold` control the post-startup background semantic duplicate merge.
- `proactive_content_ratio.extra_knowledge` / `regular_greeting` control the initial ratio of knowledge greetings to normal greetings during idle proactive greetings. The current default is 0.35 / 0.65; runtime user responses slightly adjust it through `_adjust_ratio()`, and it remains clamped to the 0.3-0.7 range.
- Change scenarios: when adding configurable items, update this file and confirm the read path.

`desktop_pet/config/app_config.json`

- User-local personalized configuration, which may contain API keys. It is ignored by `.gitignore` and should not be used as a shared default source of truth.

`desktop_pet/config/character_default.json`

- Default character personality, speaking style, catchphrases, and safety switches.

`desktop_pet/config/local_lines.json`

- Local proactive lines and prompt copy. `BehaviorController` checks `first_start.enable` first for startup greetings; when enabled, it prefers `first_start.data`, then writes `enable=false` back automatically after successful use. If not hit, it continues falling back to seasonal/time-period greetings and `startup`. Idle/test greetings mainly use `idle`, `quiet`, and `encourage`, and mix in time-period groups `greeting_morning`, `greeting_noon`, `greeting_afternoon`, `greeting_evening`, and `sleepy`. Seasonal groups `greeting_spring`, `greeting_summer`, `greeting_autumn`, and `greeting_winter` are used for startup cycle greetings and time-period/season change detection. Exit uses `farewell`. Double-click replies use `break_reminder` / `comfort` / `encourage`. Double-click after proactive greetings uses `feedback`. Chat-input waiting timeout uses `waiting`. Test poetry uses `poetry`. Knowledge-greeting lead-in prompts use `knowledge_speak_intro`, and knowledge-greeting confirmation uses `reply`. Scenario greeting local fallback uses `scenario_greeting_templates`, where `{task}` is replaced with a recent task; low-interruption fallback after consecutive unanswered greetings uses `low_interrupt`.

`desktop_pet/tools/import_memory_json_to_mem0.py`

- Optional one-time import tool. It reads legacy structured memories from the current `data/memory.json`, deduplicates them, and writes them into Mem0 through `Mem0MemoryService.add_memory_text()`.
- Run method: after `cd desktop_pet`, execute `py tools/import_memory_json_to_mem0.py`. If Mem0 is not enabled, dependencies are not installed, or initialization fails, it only prints a message and exits without affecting the main program.

`desktop_pet/tools/test_dashscope_embedding.py`

- Optional DashScope embedding connectivity test script. It first reads the key from `memory.dashscope_api_key`; if empty, it reads `DASHSCOPE_API_KEY`. On success it prints only the model name and vector dimension, not the full vector.
- Run method: after `cd desktop_pet`, execute `.\.desktop_pet_venv\Scripts\python.exe tools\test_dashscope_embedding.py`.

`desktop_pet/config/safety_rules.json`

- Safety rules injected into model prompts.

`desktop_pet/utils/dwm_border.py`

- `suppress_dwm_border()`: intercepts `WM_NCCALCSIZE` in `nativeEvent` to remove the thin DWM border added to borderless windows.
- `apply_transparent_window_fixes()`: removes extended edge styles for a window HWND, disables DWM rounded corners, and disables system background rendering.
- `force_window_topmost(hwnd, enabled)`: uses `SetWindowPos(HWND_TOPMOST)` to set or unset always-on-top directly at the Windows API level. Qt's `WindowStaysOnTopHint` may be cleared by the system on transparent layered windows that frequently call `setMask()` / `resize()`; this function is used by `DesktopPetWindow._enforce_topmost()` every 30 seconds to keep the topmost state persistent.
- Change scenarios: adjusting low-level Windows behavior for window transparency, borders, and topmost state.

`desktop_pet/utils/logger.py`

- Configures global logging, writing to the console and `desktop_pet/data/app.log`. File logging uses `RotatingFileHandler`; by default each `app.log` is capped at about 1MB and 5 backups are kept, avoiding unbounded log growth during long-running use.

`desktop_pet/utils/log_sanitizer.py`

- Log privacy helper. Provides API key masking, common `Bearer` / `api_key=` pattern sanitization, long-text truncation, exception summaries, request message structure statistics, and response structure summaries. AI module logs should record structural information such as message_count, chars_count, status_code, and response keys; they should not log full prompts, full user inputs, full model replies, full memory, or full API responses.

`xiaohu_codex_package/xiaohu_codex/`

- Source of early requirements and implementation roadmap, not runtime code. Reading it can help understand product intent, but current behavior should be based on the code under `desktop_pet/`.

## 4. Core Execution Flows

Startup flow:

1. `desktop_pet/main.py` calculates `project_root` and writes `data/startup_bootstrap.log`.
2. Imports `QApplication`, `DesktopPetWindow`, and `configure_logging()`.
3. `configure_logging()` creates `data/app.log`.
4. Creates `QApplication` and sets `setQuitOnLastWindowClosed(False)`.
5. Creates `DesktopPetWindow(project_root)`.
6. The main window initializes config paths, data paths, formal/informal dual stores and dual summarizers, AI client, prompt builder, animation player, bubbles, input box, proactive behavior controller, and autonomous movement timer.
7. Sets up a transparent, borderless, always-on-top window and restores the previous position or places it at the bottom-right of the screen.
8. After `window.show()`, enters `app.exec()`.
9. On first `showEvent()`, starts `BehaviorController.start()`, then attempts a startup greeting after about 1.2 seconds.

User chat request flow:

1. The user left-clicks the character; `_open_chat_input()` shows the input box.
2. `ChatInput` emits the `message_submitted` signal.
3. `_handle_user_message()` records user interaction, writes to `chat_history_formal.json` or `chat_history_informal.json` according to the current `formal_qa_mode`, shows a "thinking" bubble, and switches to the `running` or `review` action.
4. If `api.enable_chat_api` is false, it uses `_generate_local_reply()` and directly displays and saves the local reply.
5. If the API is enabled but no key is configured, it shows a failure prompt and switches to `failed`.
6. If the API is available, it creates a `QThread` and `ChatWorker`.
7. `ChatWorker.run()` reads recent context. If Mem0 is enabled and `memory.inject_mem0_to_prompt` is true, it retrieves long-term semantic memories in the background thread based on the current user input and passes them into `PromptBuilder.build_messages()`; retrieval failure falls back to an empty result and does not affect the original JSON memory flow.
8. `ChatWorker.run()` calls `PromptBuilder.build_messages()`, then calls `DeepSeekClient.chat()`.
9. On success, `_on_chat_success()` saves the assistant reply, switches back to `idle`, displays a bubble or formal Q&A panel depending on mode, and starts the background summarization thread.
10. On failure, `_on_chat_failure()` switches to `failed` and shows the error.

Formal Q&A display flow:

- When `chat.formal_qa_mode` is true, assistant replies do not use the normal bubble and instead go through `_show_formal_answer_panel()`.
- When `chat.formal_answer_display` is `new_panel`, each question creates a new panel.
- When `chat.formal_answer_display` is `append`, replies append to the currently visible panel.
- Panel text is plain-text `QTextEdit`, can be selected and copied, and the main-window reference list removes the panel after it closes.

Proactive behavior flow:

1. After `BehaviorController` starts, it sets an idle check timer that runs every 60 seconds.
2. Startup greetings are constrained by `do_not_disturb` and `startup_greeting`, not by the daily proactive-line limit. Priority is `first_start.data` (only when `first_start.enable` is true) -> seasonal greeting on the first day of each 5-day cycle -> current time-period greeting -> `startup`; successful display is not counted as local proactive-line usage.
3. Idle proactive lines are constrained by `proactive_chat`, `min_proactive_interval_minutes`, `last_proactive_at`, dynamic unanswered interval, and daily limits. If consecutive unanswered greetings reach the low-interruption threshold, one low-interruption greeting is selected from `low_interrupt` first. If scenario greetings are enabled, cooldown is over, and memory context is sufficient, recent task / interaction-style context is built from `memory.json`; when the API is available, `scenario_greeting_requested` is emitted for the background worker; if the API is unavailable or fails, it falls back to `scenario_greeting_templates`.
4. If no scenario greeting is triggered, it continues using `proactive_content_ratio` to choose between knowledge greeting and normal greeting; the normal greeting line pool randomly selects from `idle` / `quiet` / `encourage` / `break_reminder` plus the current time-period group.
5. After a local greeting triggers, it emits `speak_requested(text, duration_ms, action_name)`; scenario API greetings return to the main thread and display after `ScenarioGreetingWorker` succeeds.
6. `DesktopPetWindow._handle_behavior_speak()` / `_handle_scenario_greeting()` display the bubble and switch action when not chatting and the input box is not visible.

Auto-movement and test action flow:

- When `ui.enable_free_move` is true, `auto_move_timer` randomly triggers every 15 to 28 seconds.
- Auto-movement randomly triggers left-run, right-run, and jump at roughly a 4:4:2 ratio.
- The test menu can trigger action playback, move left, move right, jump, local proactive speaking, and API proactive speaking.
- Current auto-movement still skips when `_chat_in_progress()` is true or during dragging. Test left, right, and jump use `_movement_locked()` to avoid movement during exit or dragging.

Configuration loading flow:

- `DesktopPetWindow._load_app_config()` uses `load_json_prefer_primary(config/app_config.json, config/app_config.example.json, {})`.
- If the primary config exists, it reads the primary config; if not, it reads the example config; if neither exists, it creates the primary config with default values.
- `DesktopPetWindow` initializes `ConfigService(self.app_config)` for safe dot-path configuration reads; after reloading configuration, it calls `config_service.update(self.app_config)` so the service points to the latest in-memory configuration.
- `DeepSeekClient` and `ContextManager` use the same primary-first, example-fallback strategy.

Build flow:

- There is currently no build or packaging script. The first-version goal is local machine execution, with no packaging requirement.
- Assumption: if a Windows executable is needed in the future, PyInstaller could be considered, but the project currently has no related configuration.

Test flow:

- The project currently uses `unittest` regression tests under `desktop_pet/tests/`; there is no pytest, CI, or formatter configuration.
- Recommended command with the project-local virtual environment: `desktop_pet\.desktop_pet_venv\Scripts\python.exe -m unittest discover -s desktop_pet\tests`.
- Configuration read service regression tests live in `test_config_service.py`, covering dot-path reads, missing-field defaults, type conversion, and reference updates after reload.
- Chat-flow controller regression tests live in `test_chat_flow_controller.py`, covering local replies, missing API config, formal Q&A, worker arguments, and duplicate chat-task decisions.
- Local line service and refresh tests live in `test_local_lines_service.py`, covering legacy array format, fallback, controlled generated updates, deduplication, first-start line consumption, seven-day due checks, cross-month refresh, not-due skips, worker writes, and missing-API skips.
- Message splitting tests live in `test_message_splitter.py`, covering full-stop splitting, short-first-sentence merging, single-sentence preservation, question/exclamation marks, and whitespace normalization.
- Memory-system regression tests include `test_memory_schema.py`, `test_summarizer_memory_updates.py`, `test_prompt_builder_memory_sections.py`, and `test_memory_vector_store.py`, covering memory schema compatibility, relationship-memory extraction, prompt memory sections, and local vector indexing. Scenario-based proactive greeting tests include `test_proactive_context.py`, `test_scenario_greeting_config.py`, `test_scenario_greeting_worker.py`, and scenario-routing cases in `test_behavior_controller.py`.
- Common lightweight checks also include Python AST parsing, JSON validity checks, and manual startup.
- In this environment, `py_compile` may fail because writing `__pycache__` is not permitted, so it should not be the only verification method.

## 5. Important Module Relationships

- `main.py` is only responsible for startup and early diagnostics; business logic is concentrated in `DesktopPetWindow`.
- `DesktopPetWindow` owns and connects `SpritePlayer`, `SpeechBubble`, `ChatInput`, `FormalAnswerPanel`, `BehaviorController`, `ChatStore`, `UsageStore`, `MemoryStore`, `DeepSeekClient`, `PromptBuilder`, `ContextManager`, and `Summarizer`.
- `SpritePlayer` only handles action frames and pixmaps; it does not move the window directly. Window movement is handled by `DesktopPetWindow` with `QPropertyAnimation`.
- `PromptBuilder` does not call the API directly; it only assembles messages. `DeepSeekClient` only sends requests.
- `ChatStore` is the shared source for context, summaries, and chat records.
- `Summarizer` depends on `ChatStore`, `MemoryStore`, and `DeepSeekClient`, but summary failures should log and exit without blocking chat.
- `BehaviorController` does not operate on UI directly; it only emits signals to the main window.

## 6. Recommended Reading and Edit Paths for Common Development Tasks

Adding a right-click menu item:

1. Read `app/context_menu.py` and its `build_context_menu()`.
2. Read callback injection in `DesktopPetWindow._show_context_menu()`.
3. Add a handler function in the main window and confirm whether it needs to be saved to `app_config`.
4. If a new config key is added, update `config/app_config.example.json` and this file.

Modifying chat or API behavior:

1. Read `DesktopPetWindow._handle_user_message()`.
2. Read `ChatWorker.run()`, `ai/prompt_builder.py`, and `ai/deepseek_client.py`.
3. If context or summarization is affected, also read `ai/context_manager.py` and `ai/summarizer.py`.
4. After changes, verify at least three branches: local reply, missing API key, and configured API key.

Modifying formal Q&A mode:

1. Read `DesktopPetWindow._show_answer_output()` and `_show_formal_answer_panel()`.
2. Read `app/formal_answer_panel.py`.
3. Check reference cleanup after panel close to avoid leftover objects.
4. If adding a display mode, update `chat.formal_answer_display` config and the right-click menu.

Modifying actions or assets:

1. Read `assets/sprite_config.json` and `xiaohu_codex_package/xiaohu_codex/SPRITE_SHEET_SPEC.md`.
2. Read `animation/sprite_player.py`.
3. Read all `set_action()` calls in the main window.
4. Confirm action names are consistent across config, asset rows, menu test items, and call sites.

Modifying window display, transparent background, position, or movement:

1. Read `DesktopPetWindow._setup_window()`, mouse events, `_restore_position()`, `_trigger_auto_move()`, `_start_horizontal_move_test()`, and `_start_jump_auto_move()`.
2. Be especially careful with multi-monitor and off-screen recovery; preserve the `window_state.json` visibility check first.
3. After changes, manually test dragging, position persistence, initial bottom-right position, left movement, right movement, jump, and exit.

Modifying proactive lines:

1. Read `character/behavior_controller.py`.
2. Read `config/local_lines.json`.
3. Read `storage/usage_store.py`.
4. Confirm do-not-disturb, daily limits, and waiting-for-user-reply logic are not bypassed.

Modifying persistent data structures:

1. Read `storage/json_store.py`.
2. Read the corresponding store file.
3. Read all modules that reference that JSON.
4. You must consider compatibility with old data files, because `data/` is user-local runtime data.

## 7. Code Style and Project Conventions

- Python code generally uses `from __future__ import annotations`.
- Class names use PascalCase; functions and methods use snake_case.
- Qt event methods keep Qt naming, such as `mousePressEvent`, and use `# noqa: N802`.
- JSON files use UTF-8; `save_json()` uses `ensure_ascii=False` and `indent=2`.
- Missing runtime JSON files should be created automatically, preferably through `storage/json_store.py`.
- API keys must not be hard-coded in code or shared files outside examples. Real keys belong in ignored `config/app_config.json`.
- UI and business logic are not clearly separated into MVC right now; the main window carries coordination responsibilities. Small features can follow the existing pattern; larger features should consider module extraction.
- Background API requests use `QThread + QObject worker`; do not request the network directly on the UI thread.
- Summaries run in a normal `threading.Thread` in the background; exceptions should be swallowed and logged.
- The current code has many Chinese user-facing strings and comments. New user-facing copy should use Chinese and pay attention to file encoding.

## 8. High-Risk Modification Areas

`DesktopPetWindow`

- Highest risk. Chat, window, actions, state, menu, and background threads are all concentrated here.
- Before modifying it, locate related signals and state variables; do not change only one branch.

`main.py` early startup logging

- Used to diagnose silent exits before and after PySide6 import. Do not casually remove `_write_boot_log()`.

`json_store.py`

- Affects all configuration and runtime data. When modifying default creation, parse-failure handling, backup restore, temp-file cleanup, or save behavior, consider old user data, Windows file handles, permissions, and crash/interruption scenarios.

`app_config.example.json`

- Fallback configuration when `app_config.json` is absent. If a new config key is only added in code and not in the example, behavior will differ on new devices.

`DeepSeekClient` and `PromptBuilder`

- Affect external requests, model output, safety rules, and context. When modifying them, handle no-key, local-reply, API-error, and formal-Q&A branches.

`SpritePlayer` and `sprite_config.json`

- Action names, frame counts, rows/columns, frame rate, and scaling are coupled. When adding actions, synchronize menu items, call sites, and assets.

`FormalAnswerPanel`

- Close/destroy and reference cleanup are the memory-safety focus. Do not let a closed panel remain in `formal_answer_panels`.

`.gitignore`

- Used to upload only the program body. Do not unignore `desktop_pet/data/`, logs, caches, or real `app_config.json`.

## 9. Common Commands

Install dependencies:

```powershell
cd desktop_pet
py -m pip install -r requirements.txt
```

Start the program:

```powershell
cd desktop_pet
py main.py
```

Quick startup script:

```powershell
cd desktop_pet
.\setup_env.bat
wscript.exe .\start_main.vbs
```

View early startup log:

```powershell
Get-Content .\data\startup_bootstrap.log -Tail 80
```

View application log:

```powershell
Get-Content .\data\app.log -Tail 80
```

Check where Python commands point:

```powershell
py -V
Get-Command python | Format-List Name,Source,Path,CommandType
where.exe python
```

Lightweight syntax and AST check without writing `__pycache__`:

```powershell
@'
import ast
from pathlib import Path
for path in Path("desktop_pet").rglob("*.py"):
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    print(f"OK {path}")
'@ | py -3 -B -
```

JSON validity check:

```powershell
@'
import json
from pathlib import Path
for path in Path("desktop_pet").rglob("*.json"):
    json.loads(path.read_text(encoding="utf-8"))
    print(f"OK {path}")
'@ | py -3 -B -
```

View current changes:

```powershell
git status --short
```

The following commands or configurations do not currently exist:

- No pytest configuration.
- No formatter configuration.
- No lint configuration.
- No packaging script.
- No CI configuration.

## 10. Important Dependencies and External Services

Python dependencies are listed in `desktop_pet/requirements.txt`:

- `PySide6-Essentials`: provides the required `PySide6.QtCore`, `PySide6.QtGui`, and `PySide6.QtWidgets` modules for desktop windows, Qt widgets, timers, signals, animations, and image display. Do not install full `PySide6` / `PySide6_Addons` by default, to avoid pulling in large unused Qt components such as WebEngine, QML, Quick, Charts, and 3D.
- `requests`: calls the DeepSeek API and is used by the standalone DashScope embedding test script.
- `mem0ai==2.0.2`: optional base SDK for the Mem0 long-term semantic memory layer. Code must use optional imports and failure fallback; do not assume it is installed or initializes successfully. Do not install `mem0ai[nlp]`, CLI, Server, OpenMemory, Docker, self-hosted services, spaCy models, or other extras by default.

External services:

- DeepSeek API, default `base_url` is `https://api.deepseek.com`.
- Request path is `/chat/completions`, and the request body includes `model`, `messages`, and `temperature`.
- API key is read from `config/app_config.json` or the example config's `api.api_key`. The example config defaults to an empty key.
- DashScope / Alibaba Cloud Bailian OpenAI-compatible embeddings API, default base URL is `https://dashscope.aliyuncs.com/compatible-mode/v1`. The Mem0 embedder calls `/embeddings`, with default model `text-embedding-v4` and dimension 1024. The DashScope API key is read from `memory.dashscope_api_key` or `DASHSCOPE_API_KEY`.

## 11. Open Questions

- There is currently no automated testing. Human confirmation is needed on whether to introduce pytest, Qt testing tools, or a minimal smoke test.
- There is currently no build and packaging plan. The first version is presumed to require only source-code execution; whether PyInstaller or an installer is needed remains to be confirmed.
- `ai/safety_filter.py` exists but is not wired into the main flow. Whether local high-risk request pre-filtering is needed remains to be confirmed.
- `UsageStore` supports API proactive usage counting, but the current API proactive speaking test flow does not show complete integration of a daily API proactive limit. Whether a limit is needed remains to be confirmed.
- `character/character_profile.py` and `character/emotion_state.py` currently look like reserved structures, and the main flow does not clearly depend on them. Whether to develop a character-state system later remains to be confirmed.
- Many Chinese comments and strings in the current project display as mojibake in PowerShell output. Human confirmation is needed on whether this is only terminal encoding display, or the source text itself has become mojibake. If actual UI text is garbled, fix encoding and copy first.
- Some early tasks in `README.md` and `xiaohu_codex_package/` mention a "clear chat history" menu. The current right-click menu is controlled by the `show_clear_menu` config and provides two separate entries: "clear informal chat history" and "clear formal Q&A history".
- Auto-movement currently still skips while chat is in progress, while test movement only avoids dragging and exit. Whether this difference matches product expectations remains to be confirmed.

## 12. Documentation Maintenance Rules

- After each code change by an agent, check whether `AGENTS.md` needs to be updated.
- If a change touches directory structure, core flows, APIs, data structures, configuration keys, dependencies, test methods, build methods, or project conventions, update `AGENTS.md`.
- Documentation updates must be based on actual code, configuration, tests, and comments; do not write unimplemented requirements as implemented facts.
- If design intent can only be inferred, explicitly write "assumption".
- If something cannot be confirmed, put it in the "Open Questions" section.
- Every update must append an entry to the "Documentation Sync Log" below, describing the code-change summary and the documentation update.

## Documentation Sync Log

- 2026-05-11: Created `AGENTS.md`. Based on the current project entry point, configuration, dependencies, requirements documents, core business directories, and existing code, documented the project structure, run flow, module relationships, common edit paths, risk areas, common commands, dependent services, and open questions. Also allowed root `AGENTS.md` through `.gitignore` so this agent document can be committed with the program body. No program code was changed.
- 2026-05-11: `BehaviorController` added `_time_greeting_key()` to return time-period greeting groups based on local time (morning/noon/evening/late night). Startup greetings now prefer time-period lines, and idle/test line pools mix in time-period groups. Added `pick_farewell_line()` to select from the `farewell` group on exit. `DesktopPetWindow.request_exit()` now plays `waving` and displays a goodbye bubble on exit. Updated `AGENTS.md` descriptions for behavior_controller, local_lines, proactive behavior flow, and DesktopPetWindow.
- 2026-05-11: Added double-click recognition. `DesktopPetWindow` added `mouseDoubleClickEvent`; double-clicking the character triggers `pick_reply_line()` to randomly select a line from `break_reminder` / `comfort` / `encourage` and play `waving`. `mouseReleaseEvent` now uses `_click_timer` to delay and distinguish single-click from double-click, avoiding accidentally opening the chat input on double-click. `BehaviorController` added `pick_reply_line()`.
- 2026-05-11: Added seasonal cycle greetings. `BehaviorController` added `_season_key()` to divide seasons by month and `_is_cycle_start()` to detect the first day of each 5-day cycle by day-of-year. `_startup_greeting()` now prefers seasonal greetings on cycle-start days, then time-period greetings, then `startup`. `local_lines.json` added the four seasonal line groups `greeting_spring` / `greeting_summer` / `greeting_autumn` / `greeting_winter`.
- 2026-05-11: Added window always-on-top toggle. The right-click menu added a checkable "window always on top" item, and `_toggle_always_on_top()` controls `WindowStaysOnTopHint` and persists it to `ui.always_on_top`. When disabling topmost, a line is randomly selected from `return_after_idle` and displayed. `BehaviorController` added `pick_ignored_line()`.
- 2026-05-11: Added chat-input waiting prompts. `DesktopPetWindow` added `_waiting_timer`; if the input box is open for 30 seconds without submission, it selects and displays a line from `waiting`, then repeats every 25 seconds. The timer stops when the user submits. `BehaviorController` added `pick_waiting_line()`.
- 2026-05-11: Added test-menu visibility configuration. Added `show_test_menu` under `ui` in `app_config.example.json` (default `false`). `context_menu.py`'s `build_context_menu()` added a parameter with the same name, and the entire test submenu is skipped when the condition is not met. `DesktopPetWindow._show_context_menu()` reads and passes the config value.
- 2026-05-11: Fixed two window topmost issues. (1) `SpeechBubble` added `set_always_on_top()`, and `_display_message()` synchronizes the main-window topmost state before every display, eliminating the issue where bubbles were not controlled by the topmost toggle. (2) Corrected line mapping: `_toggle_always_on_top()` now calls `pick_return_after_idle_line()` for `return_after_idle` when enabling topmost and `pick_ignored_line()` for `ignored` when disabling topmost.
- 2026-05-11: Added automatic greetings when time period changes. `BehaviorController` added `period_check_timer` (every 60 seconds) and `_check_period_change()`, tracking `_last_time_key` and `_last_season_key`. When time period (morning/noon/evening/late night) or season changes, it immediately pops the corresponding new time-period line.
- 2026-05-11: Added feedback after proactive greetings via double-click. `BehaviorController` added `is_within_proactive_reply_window()` to check a 60-second response window, and `pick_feedback_line()` to select from the `feedback` group. `mouseDoubleClickEvent` prioritizes `feedback` lines when double-clicked inside the response window, otherwise it falls back to normal double-click reply. `local_lines.json` added the `feedback` group.
- 2026-05-11: Added poetry test feature. The right-click test menu added "recite a poem"; `_test_poetry()` randomly selects from the `poetry` group, plays `waving`, and displays it. `local_lines.json` added the `poetry` group. `BehaviorController` added `pick_poetry_line()`.
- 2026-05-11: Added poetry keyword detection in chat input. `_handle_user_message()` detects poetry-related keywords under specific conditions (API off, formal Q&A off, autonomous movement off, window topmost off); when matched, it directly replies with a local `poetry` line and plays the `running` action.
- 2026-05-11: Chat input box now follows topmost state. `ChatInput` added `set_always_on_top()`, and `_open_chat_input()` plus `_toggle_always_on_top()` synchronize the input box topmost state with the main window.
- 2026-05-11: Split chat history into formal/informal tracks. `ChatStore` added a `last_cleaned_at` field and `update_last_cleaned_at()` method; `ContextManager` now receives two stores and selects based on mode; `PromptBuilder` now receives two summary paths and selects based on mode; `Summarizer.maybe_summarize()` added a `force` parameter; `DesktopPetWindow` added dual stores / dual summary instances, a `_pending_was_formal` snapshot to prevent routing errors, and an `_active_chat_store()` helper. `app_config.example.json` added `formal_cleanup_months` and `informal_cleanup_months` (later removed after 2026-05-11).
- 2026-05-11: Added right-click menu for clearing chat history. `app_config.example.json` added `ui.show_clear_menu` (default `false`); `context_menu.py` added two menu entries, "clear informal chat history" and "clear formal Q&A history"; `DesktopPetWindow` added `_clear_informal_chat_history()` and `_clear_formal_chat_history()`.
- 2026-05-11: Summarize before clearing history. `_clear_informal_chat_history()` and `_clear_formal_chat_history()` call `maybe_summarize(force=True)` before clearing, then clear messages and update `last_cleaned_at`. `app_config.example.json` added `chat.force_summarize_before_clear` (default `true`) to control whether to force summarization.
- 2026-05-11: Removed time-based cleanup. Deleted `DesktopPetWindow._check_time_based_cleanup()` and `_cleanup_timer`, `ChatStore.should_trigger_time_cleanup()` and `last_cleaned_at()`, and `chat.formal_cleanup_months` / `chat.informal_cleanup_months` from `app_config.example.json`. The old cleanup strategy was redundant (hourly check for 90/180-day thresholds) and overlapped with incremental summarization. Kept `update_last_cleaned_at()` for marking manual clearing. Updated `AGENTS.md`.
- 2026-05-11: Added dynamic proactive-greeting frequency adjustment. `BehaviorController` added `_consecutive_unanswered`; the greeting interval adjusts based on consecutive unanswered count (first 15min -> second 15min -> third 30min -> fourth 30-60min random -> max 60min). `notify_user_interaction()` resets the counter on user interaction. `_maybe_idle_prompt()` removed the hard `awaiting_user_reply` block and now relies on the dynamic interval.
- 2026-05-11: Added knowledge greetings and content-ratio system. `BehaviorController` added the `knowledge_speak_requested` signal, `_has_memory_content()` memory check, and `_proactive_ratio()` / `_adjust_ratio()` for greeting-type ratios. `_maybe_idle_prompt()` randomly chooses normal greeting or knowledge greeting based on `proactive_content_ratio`. `DesktopPetWindow` added `KnowledgeSpeakWorker` (calls API based on memory.json to generate content) and `_handle_knowledge_speak()` for display and `pick_reply_ack_line()` confirmation replies. `mouseDoubleClickEvent` calls `notify_proactive_response()` inside the response window to adjust ratios. `local_lines.json` added the `reply` group (10 short acknowledgement lines). `app_config.example.json` added `proactive_content_ratio` (initially 1:1).
- 2026-05-11: Added test button for knowledge greetings. The right-click test menu added "test proactive greeting knowledge content", and `DesktopPetWindow._test_knowledge_speak_once()` directly calls `_handle_knowledge_speak()` to trigger a memory-enhanced greeting. `context_menu.py` added the `on_test_knowledge_speak` callback parameter.
- 2026-05-11: Added test button for idle greeting logic. `BehaviorController` added `trigger_test_idle_prompt()` to bypass time interval limits and directly call `_maybe_idle_prompt()`, while preserving do-not-disturb, proactive-chat, and daily-limit guards, making content-ratio routing easy to test. The right-click test menu added "test idle greeting logic", and `DesktopPetWindow._test_idle_prompt_once()` handles it. `context_menu.py` added the `on_test_idle_prompt` callback parameter.
- 2026-05-11: Reworked the right-side reply bubble for knowledge greetings. `speech_bubble.py` added the `ReplyBubble` class: an independent rounded rectangle bubble, no tail, green color scheme, `PointingHandCursor`, positioned on the right side of the character, and emits a `clicked` signal. `_on_knowledge_speak_success()` now uses `reply_bubble` to display the `reply` acknowledgement line. `_handle_reply_bubble_clicked()` calls `notify_user_interaction()` and `notify_proactive_response()` to count the user's response into the greeting-interval mechanism. `closeEvent`, `_toggle_always_on_top`, and `_sync_floating_widgets` were adapted.
- 2026-05-12: Clamped content ratio to 3:7. `_adjust_ratio()` upper bound changed from 1.0 to 0.7 and lower bound from 0.0 to 0.3, so the knowledge-greeting and normal-greeting ratio always remains between 3:7 and 7:3.
- 2026-05-12: `trigger_test_idle_prompt()` return type changed to str, returning the current ratio and the triggered greeting type (knowledge/normal/not triggered). `_test_idle_prompt_once()` only displays the result bubble when not triggered, avoiding overwriting already popped normal greeting lines.
- 2026-05-12: Optimized the knowledge-greeting prompt. `KnowledgeSpeakWorker.run()` now uses `random.choice(preferences)` to randomly select one preference direction and generate 3-4 focused sentences, starting conversationally with phrases such as "did you know" or "speaking of which".
- 2026-05-12: `_maybe_idle_prompt()` now resets `_consecutive_unanswered = 0` after every successful greeting, so the next interval returns to 15 minutes.
- 2026-05-12: Fixed `ReplyBubble` positioning. In `show_message()`, `show()` now runs before `_reposition()` to avoid `height()` not being ready and causing y coordinates to fall into the middle of the character. Added public `reposition(anchor_rect)`, and `_sync_floating_widgets` now uses it with the latest anchor coordinates.
- 2026-05-12: Fixed window topmost handling. `_toggle_always_on_top` now calls `_reapply_window_flags()` to rebuild all flags at once and reset transparency attributes, then calls `raise_()` + `apply_transparent_window_fixes()` after `show()` to restore Z-order. `_reload_config` adds `self.show()` + `raise_()` + `apply_transparent_window_fixes()` after `_setup_window()`, fixing the issue where the character disappeared after reloading configuration.
- 2026-05-13: After single-clicking the character to open the chat input box, play one cycle of the `waiting` action. `DesktopPetWindow._open_chat_input()` now calls `sprite_player.set_action("waiting", fallback_action="idle", force_single_cycle=True)` after `chat_input.show_near()`. The action returns to `idle` after finishing; later message submission is still handled by the chat flow switching to `running` / `review` and other actions.
- 2026-05-13: Startup greetings no longer count toward local proactive-line usage. `BehaviorController._startup_greeting()` removed `usage_store.increment_local_line()` before successful display, while preserving do-not-disturb, the `startup_greeting` switch, and daily-limit checks. Idle proactive lines and time-period change greetings still count as before.
- 2026-05-13: Reduced the proactive content-ratio adjustment magnitude after user responses. `BehaviorController._adjust_ratio()` now changes response type by +0.005 and mutually exclusive type by -0.001, while still keeping the knowledge/normal greeting ratio within 0.3-0.7.
- 2026-05-13: Added empty-chat protection for summaries and memory updates. `Summarizer.maybe_summarize()` added `_has_summarizable_history()` and only continues generating summaries and merging `memory_updates` when non-empty user messages exist. Even with `force=True`, empty history or history containing only empty content/assistant messages is skipped, preventing the model from writing erroneous memories such as "the user does not want to be summarized or recorded" based on an empty transcript.
- 2026-05-13: Split quick startup and environment preparation scripts. `desktop_pet/setup_env.bat` is responsible for finding or installing Python with `pip` (preferring Miniforge and avoiding MSYS Python without pip), installing and verifying that `PySide6-Essentials` provides the `PySide6` module and `requests`, then writing the final interpreter path to `data/runtime_python.txt`. `desktop_pet/start_main.vbs` is the default terminal-free startup entry; it reads that path and runs `main.py` hidden, opening a terminal to show `data/start_main_error.log` on error, avoiding implicit dependency-environment changes during daily startup.
- 2026-05-13: Fixed terminal-free startup failing to read the Python path. `setup_env.bat` now writes `runtime_python.txt` as a plain path without a trailing newline; `start_main.vbs` added path normalization that removes carriage returns, newlines, tabs, and BOM after reading, avoiding `FileExists()` misclassifying Python as missing because of a trailing newline.
- 2026-05-13: Improved compatibility of quick startup scripts with new environments. `start_main.bat --console` also cleans BOM, carriage returns, newlines, tabs, and spaces via PowerShell when reading `runtime_python.txt`; after `setup_env.bat` installs Python through `winget`, if the current terminal still cannot find a usable interpreter, it prompts to rerun the script, and if it still fails, to reopen the terminal or restart the system.
- 2026-05-14: Fixed persistent window topmost behavior. `utils/dwm_border.py` added `force_window_topmost(hwnd, enabled)`, which directly sets the topmost style at the Windows API level through `SetWindowPos(HWND_TOPMOST)`. `DesktopPetWindow` added `_topmost_enforcement_timer` (every 30 seconds) and `_enforce_topmost()`, starting it in `showEvent` and managing start/stop in `_toggle_always_on_top`, preventing frequent `setMask()` calls from causing the system to clear `WS_EX_TOPMOST`. Updated `AGENTS.md` with the `desktop_pet_window.py` description and a new `dwm_border.py` section.
- 2026-05-14: Added smart bubble positioning and mutual avoidance. `speech_bubble.py` added module-level `_find_bubble_position(bubble_width, bubble_height, anchor_rect, candidates, exclusion_rects)`, a screen-aware positioning function that supports extra avoidance areas. `SpeechBubble.reposition()` and `ReplyBubble._reposition()` now use this function, with candidate directions covering up/down/left/right. `DesktopPetWindow._sync_floating_widgets()` passes the other visible bubble's `geometry()` as `exclusion_rects` when repositioning, so the two bubbles avoid overlapping. `_on_knowledge_speak_success()` calls `_sync_floating_widgets()` after both bubbles are shown to trigger mutual avoidance. Updated `AGENTS.md` descriptions for `speech_bubble.py` and `desktop_pet_window.py`.
- 2026-05-15: Startup script added a code update step. `desktop_pet/start_main.vbs` switches to the repository root and runs `git pull --ff-only` before starting `main.py`, writing output to `data/start_main_error.log`; if Git is unavailable, the current branch has no upstream, pull conflicts occur, or the network fails, it only writes a warning and continues startup, avoiding blocking the desktop pet at boot when the network is not yet connected.
- 2026-05-15: Environment setup script moved to a project-local virtual environment strategy. `setup_env.bat` no longer installs project dependencies into the global/Miniforge base environment. Instead, it creates `desktop_pet/.desktop_pet_venv`, installs dependencies into that local virtual environment, and writes `.desktop_pet_venv/Scripts/python.exe` to `data/runtime_python.txt` for `start_main.vbs`. To handle the current machine's temporary directory/proxy issues, the script clears pip-related environment variables and uses project-local `.pip_tmp`; dependency installation disables pip cache and cleans old `.pip_cache` left by earlier scripts.
- 2026-05-15: Added a configuration switch for the "reload configuration" menu item. `context_menu.py`'s `build_context_menu()` added `show_reload_config`; `DesktopPetWindow._show_context_menu()` reads `ui.show_reload_config` and passes it in; `app_config.example.json` added the same key, default `true`, to control whether the right-click menu shows the "reload configuration" button.
- 2026-05-15: Added an "afternoon" group for time-period greetings. `BehaviorController._time_greeting_key()` now divides 24 hours into `7-11` morning, `11-14` noon, `14-18` afternoon, `18-22` evening, and all other times `sleepy`; `local_lines.json` added local `greeting_afternoon` lines. Updated `AGENTS.md` descriptions for behavior_controller, local_lines, and proactive behavior flow.
- 2026-05-18: Fixed model memory mixing in character replies. `Summarizer` split "conversation summary" and "memory extraction" into two independent flows: summaries still use the recent full conversation, but model `memory_updates` only receive user messages for extraction; on failure, they fall back to local rules that also only inspect user messages. `conversation_summary_*.json` no longer persists `memory_updates`. Updated `AGENTS.md` description for `summarizer.py`.
- 2026-05-19: Added optional Mem0 long-term semantic memory layer. Added `ai/mem0_memory_service.py` to wrap Mem0 initialization, write, retrieval, and prompt formatting. Added `tools/import_memory_json_to_mem0.py` to import old `memory.json` into Mem0 once. `Summarizer` side-writes to Mem0 while preserving the `memory.json` merge logic. `ChatWorker` can retrieve Mem0 memories in a background thread based on the current user input and pass them into `PromptBuilder`. Knowledge greetings can prefer Mem0 through `memory.use_mem0_for_knowledge_speak`. `app_config.example.json` added `memory.*` config keys. `requirements.txt` added `mem0ai`. Mem0 defaults to off, degrades on exceptions, and does not block the desktop pet main flow.
- 2026-05-19: Pinned the Mem0 dependency to the minimal base SDK version `mem0ai==2.0.2` and installed that base package in the project-local virtual environment. CLI, Server, OpenMemory, Docker, self-hosted services, `mem0ai[nlp]`, spaCy models, and other extras were not installed. Updated the `AGENTS.md` dependency description.
- 2026-05-19: Adjusted Mem0 initialization to `Memory.from_config(config)`. The LLM provider uses Mem0's official DeepSeek provider, defaults to reusing project `api.api_key`, `api.base_url`, and `api.model`, and allows `memory.mem0_deepseek_model` / `memory.mem0_deepseek_base_url` overrides. `app_config.example.json` and local `app_config.json` added `mem0_llm_provider`, `mem0_use_app_deepseek_config`, `mem0_deepseek_model`, `mem0_deepseek_base_url`, `mem0_temperature`, `mem0_max_tokens`, `mem0_top_p`, and `mem0_embedder_provider`. Embeddings were not changed to DeepSeek by default; follow-up still needs OpenAI, Ollama, or another embedder configured according to Mem0 requirements.
- 2026-05-19: Moved normal greeting and normal chat-reply bubble durations into configuration. `app_config.example.json` and local `app_config.json` added `ui.bubble_durations_ms`, including `startup_greeting`, `period_greeting`, `proactive_greeting`, and `assistant_reply`. `BehaviorController` now emits bubble durations for startup/time-period/normal greetings based on config, and `DesktopPetWindow._show_answer_output()` controls normal chat-reply bubble duration based on config. Updated `AGENTS.md` descriptions for `behavior_controller.py` and `app_config.example.json`.
- 2026-05-20: Connected the Mem0 embedder to DashScope / Alibaba Cloud Bailian OpenAI-compatible embeddings. `mem0_memory_service.py` now configures DeepSeek LLM, DashScope embedding, 1024-dimensional local Qdrant, and project-local `data/mem0_history.db` when constructing `Memory.from_config()`. `app_config.example.json` and local `app_config.json` added `dashscope_embedding_*` and key-source configuration. Added `tools/test_dashscope_embedding.py`, and fixed `test.py` so it no longer uses the literal `Bearer API_KEY` or prints the full vector. Mem0 remains off by default; missing API keys or initialization failures only log warning and degrade.
- 2026-05-21: Adjusted autonomous movement random ratio. `DesktopPetWindow._trigger_auto_move()` now samples actions at a 4:4:2 ratio for left-run, right-run, and jump, and the proactive movement flow documentation was updated.
- 2026-05-22: Added `local_lines.first_start` startup greeting configuration. `local_lines.json` added the `{ "enable": false, "data": [...] }` structure. `BehaviorController._startup_greeting()` startup greeting priority changed to `first_start.data` (only when enabled) -> seasonal greeting -> time-period greeting -> `startup`. After successful use, `first_start` immediately writes back `enable=false`, implementing a one-time first-start greeting. Startup greetings are no longer blocked by the daily proactive-line limit, only by do-not-disturb and the `startup_greeting` switch. Updated startup greeting flow documentation.
- 2026-05-25: Fixed empty memory not landing during forced summarization before clearing chat history. `Summarizer._model_memory_updates()` now continues falling back to local rule extraction when the model returns a valid structure but no non-empty memory text. `maybe_summarize()` only merges `memory.json` and side-writes to Mem0 when `memory_updates` contain actual text, avoiding empty structures refreshing `memory.json.last_updated` without memory content and leaving Mem0 with no text to write. Added `desktop_pet/tests/test_summarizer_memory_updates.py` to cover empty model memory fallback to local extraction and the Mem0 write path. Updated `AGENTS.md` description for `summarizer.py`.
- 2026-05-25: Optimized Mem0 trigger frequency. `Summarizer` now triggers summarization after first reaching `summary_trigger_rounds`, then requires the same number of additional user messages since the previous covered point before summarizing again, avoiding summary and Mem0 writes on every chat turn after round 37. `BehaviorController._maybe_idle_prompt()` now first samples by `proactive_content_ratio.extra_knowledge`; only on hit does it check Mem0/local memory, and `behavior.min_proactive_interval_minutes` is now the lower bound of the dynamic greeting interval. `DesktopPetWindow._has_knowledge_memory()` now performs one retrieval and caches the Mem0 context needed for the knowledge greeting; `KnowledgeSpeakWorker` reuses that context, reducing duplicate retrieval. Default/current `proactive_content_ratio` changed to `extra_knowledge=0.35`, `regular_greeting=0.65`. Added `desktop_pet/tests/test_mem0_trigger_rules.py` to verify summary throttling and no Mem0 lookup when probability misses. Updated `AGENTS.md` descriptions for summarizer, behavior_controller, and app_config settings.
- 2026-05-28: Fixed flows related to Mem0, cleanup threads, exit waiting, and proactive-ratio persistence. `Mem0MemoryService` now directly degrades with info logging when enabled but missing the DashScope embedding key, skipping `mem0` import and Qdrant/history initialization. Added `app/history_clear_worker.py`, moving forced summarization, clearing, and `last_cleaned_at` updates before clearing chat history into a separate background thread. `DesktopPetWindow.closeEvent()` now delays true closing while chat or cleanup threads are still running, waiting for background threads to close before exiting. `BehaviorController` added a `config_saver` callback to persist `proactive_content_ratio` and performs safe integer parsing for `max_local_lines_per_day`. Added regression tests `test_mem0_memory_service.py`, `test_behavior_controller.py`, and `test_history_clear_worker.py`, and updated related module, test-flow, and risk documentation.
- 2026-05-29: Reduced runtime environment footprint. `requirements.txt` replaced `PySide6` with `PySide6-Essentials`; the current project virtual environment uninstalled full `PySide6` / `PySide6_Addons` and reinstalled Essentials, keeping only actually used modules such as `QtCore`, `QtGui`, and `QtWidgets`. `setup_env.bat` no longer creates project-local `.pip_cache`, sets `PIP_NO_CACHE_DIR=1` during dependency installation, and cleans old `.pip_cache` after successful environment validation. Updated dependency description and environment-script cache strategy documentation.
- 2026-05-30: Reordered the display order of the documentation sync log at the bottom of `AGENTS.md`, making it chronological from top to bottom. This change only adjusted documentation record order and did not change program code.
- 2026-05-30: Simplified the daily startup path in `start_main.vbs`, removing the extra startup-time dependency smoke check `python -c "import PySide6, requests"` to avoid starting Python and importing PySide6 twice. Preserved `runtime_python.txt` path existence checks; when dependencies are missing, the true startup failure path in `main.py` writes logs and triggers error display. Added `test_start_main_script.py` regression test and updated startup flow documentation.
- 2026-05-30: Fixed an issue where clearing formal Q&A history could update the summary but not `memory.json`. In formal Q&A mode, `Summarizer._extract_memory()` now uses non-empty user questions as a local fallback memory under `work_study.current_learning_topics`, avoiding a case where model memory extraction returns an empty structure and only `conversation_summary_formal.json` updates while long-term memory has no new text to merge. Added a regression test for formal Q&A cleanup and updated `summarizer.py` documentation.
- 2026-05-30: Expanded local trigger keywords for `work_study.current_learning_topics`, adding question-style expressions such as "question", "how to do", "how to implement", "how", "what is", "why", and "difference"; also fixed `Summarizer._summary_mode()` to check `informal` before `formal`, preventing the `formal` substring in informal summary filenames from triggering formal Q&A fallback logic. Added corresponding regression tests and updated `summarizer.py` documentation.
- 2026-05-30: Moved Mem0 initialization, Mem0 rebuild during config reload, and Mem0 retrieval before proactive knowledge greetings out of the Qt main thread. Added `Mem0InitializationWorker` and `Mem0SearchWorker`, which run `Mem0MemoryService` construction/old service close and `format_for_prompt()` retrieval in separate `QThread`s. `DesktopPetWindow` replaces service references through completion signals and synchronizes them to both summarizers. During proactive greeting retrieval, it returns `None` so `BehaviorController` skips normal greeting fallback for that round; after retrieval succeeds, it triggers the knowledge greeting. Added `test_mem0_threading_boundaries.py` to prevent Mem0 initialization and proactive greeting retrieval from returning to the main thread.
- 2026-05-30: Added local semantic vector indexing for `memory.json`. `MemoryStore` now best-effort syncs `data/memory_vectors.json` after saves/merges, using the existing DashScope embedding config. `DesktopPetWindow` starts a `MemorySemanticMergeWorker` after the window is shown; it runs in a separate `QThread`, checks the two-month cadence, and merges only same-field high-similarity duplicates so UI display and normal Q&A are not blocked.
- 2026-05-30: Strengthened the first round of the memory system. `MemoryStore` added `normalize_memory_schema()`, preserving compatibility with old `memory.json` and filling `relationship_memory` plus `memory_meta.schema_version=2`. `Summarizer` model/local memory extraction now supports relationship memory and records communication preferences, interaction style, and recent interaction patterns only from user messages. `PromptBuilder` split local fact memory, interaction-style memory, and Mem0 semantic memory into independent prompt blocks and added expression constraints to avoid mechanical memory repetition or exposing implementation details such as memory.json/Mem0. Added `test_memory_schema.py` and `test_prompt_builder_memory_sections.py`, and extended `test_summarizer_memory_updates.py` to cover relationship memory extraction and not inferring user preferences from assistant replies.
- 2026-05-30: Strengthened the second round of scenario-based proactive greetings. Added `character/proactive_context.py`, responsible for building compact scenario context from `memory.json`, local template fallback, and API prompts. `BehaviorController._maybe_idle_prompt()` now prioritizes low-interruption greetings after consecutive unanswered greetings after basic guards, then triggers `memory_context_greeting` when cooldown is over and memory is sufficient; when the API is enabled and quota is available it emits `scenario_greeting_requested`, otherwise it uses local templates. `DesktopPetWindow` added `ScenarioGreetingWorker`, which generates short greetings in a separate `QThread`; failures or mechanical memory expressions silently fall back to local templates. `app_config.example.json` added `behavior.scenario_greeting_*` config keys, `local_lines.json` added `scenario_greeting_templates` and `low_interrupt`, and corresponding regression tests were added.
- 2026-06-08: Improved reliability of JSON storage in `storage/json_store.py`. `save_json()` now performs same-directory `.tmp` atomic writes, preserves `.bak` for non-empty target files before writing, then uses `os.replace` after `flush` + `os.fsync`. When `load_json()` encounters a damaged main file, it isolates it as `.corrupt.<timestamp>` and prefers recovery from `.bak`; only when the backup is also damaged does it fall back to a deep copy of the default value. Added `cleanup_tmp_json_files()` to clean leftover temporary files. Added `test_json_store.py` covering missing-file creation, normal read/write, backup recovery, double-damage fallback, and failed writes not leaving half-written JSON.
- 2026-06-08: Improved long-running stability and privacy safety of the logging system. `utils/logger.py` changed `app.log` file output to `RotatingFileHandler`, limiting single-file size and keeping finite backups. Added `utils/log_sanitizer.py`, providing API key sanitization, common secret-pattern cleanup, long-text truncation, exception summaries, messages statistics, and response structure summaries. Error logs in `DeepSeekClient`, `Summarizer`, and `Mem0MemoryService` now record status code, message count, character count, response keys, and truncated exceptions instead of full payloads, prompts, memory, model replies, or API responses. Added `test_logging_privacy.py` covering log creation, rotation configuration, API key sanitization, and long-text truncation.
- 2026-06-08: Compressed `data/memory_vectors.json` size. `MemoryVectorStore` now saves the vector index as compact JSON, compresses floating-point precision according to `memory.memory_vector_precision` before writing embeddings, skips texts shorter than `memory.memory_vector_min_text_length`, and limits index entries through `memory.memory_vector_max_items`, preserving important fields and newer entries first when over limit. `embedding_signature` now includes precision configuration, so model, dimension, or precision changes rebuild the index. `app_config.example.json` added corresponding configuration keys, and `test_memory_vector_store.py` was extended to cover compact size, default config, short-text skipping, old-signature rebuilds, and maximum-entry trimming. Semantic deduplication logic remained unchanged.
- 2026-06-08: Added context budget controls for Prompt / Context / Summarizer. Added `desktop_pet/ai/context_budget.py`, centralizing defaults for `max_prompt_chars`, `max_history_messages`, `max_user_message_chars`, `max_history_message_chars`, `max_summary_chars`, `max_memory_chars`, `max_mem0_chars`, `summary_max_input_chars`, and `memory_extract_max_input_chars`; the `api` section of `app_config.example.json` added the same config keys. `PromptBuilder` now separately limits user input, history messages, summaries, normal memory, relationship memory, and Mem0 retrieval results, and under global `max_prompt_chars` trims by priority: safety rules, character settings, current user input, recent conversation, and high-value memory. `ContextManager` now limits both history message count and single-message length. `Summarizer` now builds summary / memory extraction transcripts from recent messages backward according to character budgets, guaranteeing inputs do not exceed config budgets. Added `desktop_pet/tests/test_context_budget_controls.py`, rewrote `test_prompt_builder_memory_sections.py`, and injected a `requests` stub in `test_summarizer_memory_updates.py`, covering long-history prompt trimming, oversized user-input limits, summary input budgets, and default fallback when new config keys are absent.
- 2026-06-08: Consolidated background task and `QThread` lifecycle management. Added `desktop_pet/app/background_task_registry.py`, centrally registering, querying, removing, and stopping `QThread`/worker pairs, and handling `quit()`, bounded `wait()`, necessary `terminate()`, `deleteLater()`, and cleanup callbacks. `DesktopPetWindow` connected chat tasks, history clearing, Mem0 initialization/search, and semantic memory maintenance to the registry; duplicate tasks with the same name are rejected, and closing the window centrally stops background threads with bounded waits while avoiding worker callbacks updating UI during shutdown. `memory.mem0_init_timeout_seconds` was connected to Mem0 initialization thread wait timeout. Added `desktop_pet/tests/test_background_task_registry.py` covering registration/removal, duplicate registration rejection, exit cleanup, and timeout termination.
- 2026-06-08: First low-risk phase splitting window-position logic out of `DesktopPetWindow`. Added `desktop_pet/app/window_position_service.py`, centrally responsible for reading/saving `window_state.json`, multi-monitor visibility checks, and default-position fallback for off-screen coordinates. `DesktopPetWindow._restore_position()`, `_save_window_position()`, and `_position_visible_on_any_screen()` kept their original method names and delegate to the service. Chat, bubbles, proactive greetings, animations, menu logic, and the `window_state.json` structure were not changed. Added `desktop_pet/tests/test_window_position_service.py` covering first startup, position saving, next-run restore, multi-monitor visibility, and off-screen fallback.
- 2026-06-09: Second low-risk phase splitting bubble-position calculation logic out of `DesktopPetWindow`. Added `desktop_pet/app/bubble_position_service.py`, centrally responsible for candidate positions for normal bubbles and knowledge-greeting reply bubbles, available-screen avoidance, avoiding covering the desktop pet, and mutual exclusion through bubble `exclusion_rects`. `DesktopPetWindow._sync_floating_widgets()` kept its original method name and visibility checks, only calling the service to calculate coordinates before moving bubbles. Bubble style, display timing, chat flow, proactive greeting flow, input box, and formal Q&A panel were not changed. Added `desktop_pet/tests/test_bubble_position_service.py` covering screen center, left edge, right edge, bottom, and mutual bubble avoidance.
- 2026-06-09: Completed the third-phase background task registry interfaces. `BackgroundTaskRegistry` added `unregister()`, supports `request_quit_all(timeout_ms)` returning tasks that are still running, and added `clear_finished()` to clean references to ended threads. Original thread cleanup method names in `DesktopPetWindow` were preserved, with internals changed to call `unregister()`. `_request_background_workers_quit()` now performs a bounded 1000ms wait. Business logic for `ChatWorker`, Mem0 initialization/search workers, semantic memory maintenance workers, and history-clear workers was not changed. Extended `test_background_task_registry.py` to cover the new interfaces.
- 2026-06-11: Fourth low-risk phase splitting configuration read helpers out of `DesktopPetWindow`. Added `desktop_pet/app/config_service.py`, providing dot-path `get()`, `get_bool()`, `get_int()`, `get_str()`, and missing-field default fallbacks. `DesktopPetWindow` only migrated low-risk read-only configuration reads such as right-click menu state, always-on-top / click-to-chat / autonomous movement, summarize-before-clear, Mem0 timeout, semantic memory maintenance switch, summary rounds, formal Q&A display, and bubble duration; the original configuration file structure, configuration key names, and write-back paths were preserved. Added `desktop_pet/tests/test_config_service.py` covering configuration service behavior, and updated configuration loading and test documentation.
- 2026-06-11: Fifth low-risk phase splitting user chat-flow coordination out of `DesktopPetWindow`. Added `desktop_pet/app/chat_flow_controller.py`, which helps manage normal/formal Q&A mode snapshots, user and assistant message persistence, local-reply / missing-API-config / API-worker branching, `ChatWorker` argument preparation, and pending state after success/failure. `DesktopPetWindow` preserved method names such as `_handle_user_message()`, `_start_chat_worker()`, `_on_chat_success()`, and `_on_chat_failure()`, and remains responsible for bubbles, formal Q&A panels, action switching, mouse/menu handling, and `QThread` lifecycle. Added `desktop_pet/tests/test_chat_flow_controller.py` covering local replies, missing API config, formal Q&A, worker arguments, and duplicate chat-task decisions.
- 2026-06-11: Added the local line service interface. `desktop_pet/storage/local_lines_service.py` provides `LocalLinesService`, centralizing local line random selection, first-start line consumption, manual append, controlled generated-line replacement, deduplication, length limits, and mechanical memory expression filtering. `BehaviorController` now reads normal lines and `first_start` through this service, and `DesktopPetWindow._handle_knowledge_speak()` now randomly selects a knowledge-greeting lead-in from `knowledge_speak_intro`, falling back to local defaults when absent. `local_lines.json` added the `knowledge_speak_intro` line group, and `test_local_lines_service.py` was added to cover legacy array format, fallback, controlled generated updates, deduplication, and first-start line consumption.
- 2026-06-12: Added periodic refresh for `knowledge_speak_intro`. `LocalLinesService` added `should_refresh_generated_lines()` and `group_metadata()`, using `data/local_lines_generated_meta.json` to determine seven-day cadence and month-start refresh. `DesktopPetWindow` added `LocalLinesRefreshWorker`; after the window is shown, it checks once immediately and `_local_lines_refresh_timer` checks again every 6 hours. When due and the DeepSeek API is configured, it generates short lines and calls `replace_generated_lines("knowledge_speak_intro", ...)` to write them back to local lines; when not due or the API is missing, it silently skips. `app_config.example.json` added the `local_lines_refresh` config section, and `test_local_lines_service.py` covers seven-day due checks, cross-month refresh, not-due skips, worker writes, and missing-API skips.
- 2026-06-12: Added local segmented display for knowledge-greeting bubbles. `desktop_pet/app/message_splitter.py` provides `split_knowledge_bubble_text()`, which splits knowledge-greeting replies into at most two segments by sentence-ending punctuation such as full stops, question marks, exclamation marks, and semicolons, merging the next sentence when the first sentence is too short. `DesktopPetWindow._on_knowledge_speak_success()` now displays the first segment immediately, delays the second segment, and only shows the right-side `ReplyBubble` confirmation bubble after the final segment. Added `test_message_splitter.py` covering full-stop splitting, short-first-sentence merging, single-sentence preservation, question/exclamation marks, and whitespace normalization.
