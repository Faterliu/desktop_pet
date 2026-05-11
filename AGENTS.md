# AGENTS.md

面向未来 AI 编程智能体的项目接手文档。它不是普通 README，而是为了让第一次进入本仓库的智能体在 5 分钟内知道先读哪里、改哪里、哪些地方不要贸然动。

## 5 分钟快速概览

- 一句话概览：这是一个基于 Python 和 PySide6 的 Windows 桌面 AI 宠物原型，角色通过像素 spritesheet 显示在桌面上，可聊天、主动问候、保存本地 JSON 数据，并可调用 DeepSeek API。
- 实际可运行程序在 `desktop_pet/` 目录内，入口是 `desktop_pet/main.py`。根目录的 `README.md` 是更新日志，`xiaohu_codex_package/xiaohu_codex/` 是早期需求、任务和素材说明。
- 启动建议使用 Windows Python Launcher：`cd desktop_pet` 后执行 `py -m pip install -r requirements.txt` 和 `py main.py`。不要默认信任 `python` 或 `pip`，它们在 Windows 上可能指向应用商店别名或旧解释器。
- 主协调器是 `desktop_pet/app/desktop_pet_window.py`。多数 UI、聊天、配置、动作、自动移动、正式问答、退出流程都从这里串起来。
- 运行时个性化数据不应提交：`desktop_pet/config/app_config.json`、`desktop_pet/data/`、日志和缓存都由 `.gitignore` 忽略。默认配置模板是 `desktop_pet/config/app_config.example.json`。
- 当前没有专门的测试框架、构建脚本或打包流程。常用校验是 JSON 合法性、Python AST/语法检查、手动运行桌宠。
- 每次智能体修改代码后，必须检查本文件是否需要同步更新。涉及目录结构、核心流程、API、数据结构、配置项、依赖、测试方式、构建方式或项目约定时，必须更新本文件底部的“文档同步记录”。

## 1. 项目一句话概览

`desktop_pet` 是一个 Windows 本地桌面 AI 伴随宠物应用：用 PySide6 创建透明、无边框、置顶窗口显示像素角色，并通过本地话术或 DeepSeek Chat Completions API 与用户互动。

## 2. 主要目标和运行方式

主要目标来自 `xiaohu_codex_package/xiaohu_codex/PROJECT_REQUIREMENTS.md` 和当前代码实现：

- 显示透明背景的桌面角色窗口，支持拖拽、位置保存、右键菜单和退出。
- 从 `assets/spritesheet.webp` 与 `assets/sprite_config.json` 裁切并播放动作帧。
- 点击角色弹出聊天输入框，支持本地回复或 DeepSeek API 回复。
- 保存聊天记录、摘要、记忆、每日使用量和窗口位置到 `desktop_pet/data/`。
- 支持启动问候、空闲主动话术、免打扰模式、自主移动、人物缩放、正式问答模式。

运行方式：

```powershell
cd desktop_pet
py -m pip install -r requirements.txt
py main.py
```

注意：

- `python main.py` 只有在 `python` 指向真实解释器时才可靠。此前移植排查中，`python` 指到 `Microsoft\WindowsApps\python.exe` 时会出现无输出、无窗口、无 `data/` 的情况。
- `pip install -r requirements.txt` 可能命中旧版 Python 的坏掉 `pip.exe` 启动器。优先使用 `py -m pip install -r requirements.txt`。
- 程序启动后应创建 `desktop_pet/data/startup_bootstrap.log` 和 `desktop_pet/data/app.log`。前者在导入 PySide6 前写入，用于早期启动排查。

## 3. 关键目录和文件说明

`desktop_pet/main.py`

- 程序入口。先写 `data/startup_bootstrap.log`，再导入 PySide6、配置日志、创建 `QApplication` 和 `DesktopPetWindow`。
- 修改场景：启动失败诊断、Qt 应用生命周期、窗口显示和事件循环策略。
- 风险：过早导入业务模块会削弱早期日志的诊断价值。

`desktop_pet/app/desktop_pet_window.py`

- 核心协调器。负责窗口属性、鼠标事件（单击聊天、双击回复/打招呼、拖拽移动、右键菜单，含置顶开关）、聊天流程、后台线程、正式问答面板、自动移动、位置恢复和退出动画（退出时播放 waving 并显示 `farewell` 道别气泡）。
- 修改场景：几乎所有用户可见行为的入口都在这里接线。
- 风险：文件较大，多个状态互相影响，例如 `chat_thread`、`move_animation`、`behavior_controller`、`formal_answer_panels`、`exit_animation_in_progress`、`_click_timer`、`_suppress_click`、`_waiting_timer`、`_pending_was_formal`、`_cleanup_timer`。

`desktop_pet/app/context_menu.py`

- 构建右键菜单，包括测试菜单（由 `ui.show_test_menu` 控制，默认关闭）、清理菜单（由 `ui.show_clear_menu` 控制，默认关闭，可分别清除非正式和正式聊天记录）、人物缩放、免打扰、窗口置顶、自主移动、聊天 API 开关、正式问答模式、重新加载配置和退出。
- 修改场景：新增菜单项或调整菜单可见入口。
- 注意：菜单回调由 `DesktopPetWindow._show_context_menu()` 注入，新增菜单通常要同步改两处。

`desktop_pet/app/chat_input.py`

- 悬浮聊天输入框，跟随角色位置，Enter 或发送按钮提交，关闭按钮隐藏。
- 修改场景：输入框布局、提交行为、关闭行为、跟随位置。

`desktop_pet/app/speech_bubble.py`

- 短消息气泡，自动关闭，跟随角色位置。`show_message()` 前由主窗口调用 `set_always_on_top()` 同步置顶状态。
- 修改场景：本地提示、普通聊天回复、系统提示的展示样式和定位。

`desktop_pet/app/formal_answer_panel.py`

- 正式问答模式使用的可拖动、可复制、可关闭文本面板。
- 修改场景：完整回答展示、多回答追加、面板生命周期和复制体验。
- 风险：关闭后应完全释放对象。当前通过 `WA_DeleteOnClose` 和 `destroyed` 回调让主窗口移除引用。

`desktop_pet/animation/sprite_player.py`

- 读取 sprite 配置和图集，裁切动作帧，用 `QTimer` 推进帧并发出 `frame_changed`。
- 修改场景：动作播放、帧率、缩放、素材缺失兜底。
- 当前动作帧间隔最小为 `400ms`。

`desktop_pet/assets/sprite_config.json`

- 定义 `spritesheet.webp` 的裁切参数和动作行：`idle`、`running_right`、`running_left`、`waving`、`jumping`、`failed`、`waiting`、`running`、`review`。
- 修改场景：新增动作、改帧数、改行列、换素材。
- 风险：必须与实际 spritesheet 排布一致。

`desktop_pet/ai/deepseek_client.py`

- 使用 `requests.post()` 调用 OpenAI-compatible `base_url + /chat/completions`。
- 修改场景：模型服务参数、超时、错误提示、响应结构兼容。
- 依赖配置：`api.base_url`、`api.model`、`api.api_key`、`api.timeout_seconds`。

`desktop_pet/ai/prompt_builder.py`

- 组装系统提示、角色设定、安全规则、摘要（按正式/非正式模式选择对应文件）、记忆、正式问答模式提示和上下文消息。
- 修改场景：人格、回复风格、安全规则优先级、正式问答回答策略。
- 风险：安全规则必须优先于角色 `custom_prompt`。

`desktop_pet/ai/context_manager.py`

- 根据配置读取最近聊天上下文（按正式/非正式模式选择对应 store），并判断是否达到摘要触发条件。
- 修改场景：上下文长度、摘要轮数策略。

`desktop_pet/ai/summarizer.py`

- 在聊天后尝试摘要历史。若 API 可用，会要求模型输出 JSON；失败时退回本地简化摘要，并合并记忆。`maybe_summarize()` 支持 `force` 参数，为 True 时跳过轮数检查，供时间清理流程使用。
- 修改场景：摘要结构、记忆提取、失败兜底、时间清理。
- 风险：摘要在线程中触发，异常不能影响正常聊天。

`desktop_pet/ai/safety_filter.py`

- 简单关键词高风险检测函数。当前未在主聊天流程中直接使用。
- 修改场景：接入本地安全预过滤。
- 待确认：是否计划把它接到 `_handle_user_message()` 或 `PromptBuilder` 前置流程。

`desktop_pet/storage/*.py`

- `json_store.py`：JSON 读写基础设施，缺文件时自动创建父目录和默认文件，解析失败时记录日志并尽量返回默认值。
- `chat_store.py`：保存和读取正式/非正式聊天记录（`chat_history_formal.json` / `chat_history_informal.json`），记录 `last_cleaned_at` 时间戳，提供 `should_trigger_time_cleanup()` 判断是否达到清理间隔。
- `memory_store.py`：保存和合并 `data/memory.json`。
- `usage_store.py`：每日主动话术和 API 主动次数计数。
- 修改场景：数据结构、持久化策略、运行时数据兼容。

`desktop_pet/character/behavior_controller.py`

- 管理启动问候、空闲主动话术和时段变化检测。用 `QTimer` 每 60 秒检查空闲和时段，受免打扰、每日上限、空闲时间和等待用户回复状态约束。
- `_startup_greeting()` 优先使用时段问候（`greeting_morning`/`greeting_noon`/`greeting_evening`/`sleepy`），对应分组为空时回退到 `startup`。每 5 天周期的第一天额外优先季节问候（`greeting_spring`/`greeting_summer`/`greeting_autumn`/`greeting_winter`）。
- `_maybe_idle_prompt()` 和 `trigger_test_speak()` 的话术池会混入当前时段分组。
- `_check_period_change()` 由 `period_check_timer` 每 60 秒驱动，检测时段或季节是否变化，变化时立即弹出新时段问候。
- `pick_farewell_line()` 从 `farewell` 分组随机抽取道别语，供退出流程使用。
- `pick_reply_line()` 从 `break_reminder`/`comfort`/`encourage` 三组随机选取回应话术，供普通双击回复使用。
- `pick_feedback_line()` 从 `feedback` 分组随机选取，用于用户在主动问候窗口内双击回应。
- `is_within_proactive_reply_window(window_seconds=60)` 判断当前是否在上次主动问候后 60 秒内。
- `pick_ignored_line()` 从 `ignored` 分组随机选取话术，供关闭置顶时使用。
- `pick_return_after_idle_line()` 从 `return_after_idle` 分组随机选取话术，供开启置顶时使用。
- `pick_waiting_line()` 从 `waiting` 分组随机选取等待提示话术，供聊天输入框长时间无输入时使用。
- 修改场景：主动行为频率、话术分组、免打扰逻辑、时段判断规则。

`desktop_pet/config/app_config.example.json`

- 默认配置模板。运行时优先加载 `config/app_config.json`，没有时加载此示例。包含 `ui.show_test_menu` 控制测试菜单显隐（默认 `false`）、`ui.show_clear_menu` 控制清理菜单显隐（默认 `false`）、`chat.formal_cleanup_months`（默认 6）和 `chat.informal_cleanup_months`（默认 3）控制时间清理间隔。
- 修改场景：新增可配置项时必须同步更新此文件，并确认读取路径。

`desktop_pet/config/app_config.json`

- 用户本地个性化配置，可能含 API key。被 `.gitignore` 忽略，不应作为共享默认事实来源。

`desktop_pet/config/character_default.json`

- 默认角色人格、说话风格、口头禅和安全开关。

`desktop_pet/config/local_lines.json`

- 本地主动话术和提示文案。`BehaviorController` 当前主要使用 `startup`、`idle`、`quiet`、`encourage`，以及时段分组 `greeting_morning`、`greeting_noon`、`greeting_evening`、`sleepy`，季节分组 `greeting_spring`、`greeting_summer`、`greeting_autumn`、`greeting_winter`。退出时使用 `farewell`。双击回复使用 `break_reminder`/`comfort`/`encourage`，主动问候后双击使用 `feedback`。聊天输入等待超时使用 `waiting`。测试念诗使用 `poetry`。

`desktop_pet/config/safety_rules.json`

- 注入模型提示的安全规则。

`desktop_pet/utils/logger.py`

- 配置全局日志，写入控制台和 `desktop_pet/data/app.log`。

`xiaohu_codex_package/xiaohu_codex/`

- 早期需求和实现路线图来源，不是运行时代码。读它可以理解产品意图，但当前行为以 `desktop_pet/` 代码为准。

## 4. 核心执行流程

启动流程：

1. `desktop_pet/main.py` 计算 `project_root`，写入 `data/startup_bootstrap.log`。
2. 导入 `QApplication`、`DesktopPetWindow`、`configure_logging()`。
3. `configure_logging()` 创建 `data/app.log`。
4. 创建 `QApplication`，设置 `setQuitOnLastWindowClosed(False)`。
5. 创建 `DesktopPetWindow(project_root)`。
6. 主窗口初始化配置路径、数据路径、正式/非正式双存储与双摘要器、AI 客户端、提示词构建器、动画播放器、气泡、输入框、主动行为控制器、自主移动计时器、时间清理定时器。
7. 设置透明无边框置顶窗口，恢复上次位置或放到屏幕右下角。
8. `window.show()` 后进入 `app.exec()`。
9. `showEvent()` 首次触发 `BehaviorController.start()`，约 1.2 秒后尝试启动问候。

用户聊天请求流：

1. 用户左键点击角色，`_open_chat_input()` 显示输入框。
2. `ChatInput` 提交 `message_submitted` 信号。
3. `_handle_user_message()` 记录用户交互，按当前 `formal_qa_mode` 路由写入 `chat_history_formal.json` 或 `chat_history_informal.json`，显示”思考中”气泡，并切到 `running` 或 `review` 动作。
4. 如果 `api.enable_chat_api` 为 false，走 `_generate_local_reply()`，直接显示和保存本地回复。
5. 如果 API 开启但未配置 key，显示失败提示并切到 `failed`。
6. 如果 API 可用，创建 `QThread` 和 `ChatWorker`。
7. `ChatWorker.run()` 读取最近上下文，调用 `PromptBuilder.build_messages()`，再调用 `DeepSeekClient.chat()`。
8. 成功时 `_on_chat_success()` 保存助手回复，切回 `idle`，按模式显示气泡或正式问答面板，并启动后台摘要线程。
9. 失败时 `_on_chat_failure()` 切到 `failed` 并显示错误。

正式问答显示流：

- `chat.formal_qa_mode` 为 true 时，助手回复不走普通气泡，而走 `_show_formal_answer_panel()`。
- `chat.formal_answer_display` 为 `new_panel` 时，每题新建面板。
- `chat.formal_answer_display` 为 `append` 时，追加到当前可见面板。
- 面板文本是纯文本 `QTextEdit`，可选择复制，关闭后主窗口引用列表会移除。

主动行为流：

1. `BehaviorController` 启动后设置空闲检查计时器，每 60 秒检查一次。
2. 启动问候受 `do_not_disturb`、`startup_greeting`、每日本地话术上限约束，优先使用当前时段对应的问候分组（`greeting_morning`/`greeting_noon`/`greeting_evening`/`sleepy`），该分组为空时回退到 `startup`。
3. 空闲主动话术受 `proactive_chat`、`min_proactive_interval_minutes`、`awaiting_user_reply`、`last_proactive_at` 和每日上限约束，话术池从 `idle`/`quiet`/`encourage` 加当前时段分组中随机选取。
4. 触发后发出 `speak_requested(text, duration_ms, action_name)`。
5. `DesktopPetWindow._handle_behavior_speak()` 在未聊天且输入框不可见时显示气泡并切动作。

自动移动和测试动作流：

- `ui.enable_free_move` 为 true 时，`auto_move_timer` 每 15 到 28 秒随机触发一次。
- 自动移动可能执行左右移动，也可能以约 35% 概率执行 `jumping` 跳跃。
- 测试菜单可触发动作播放、左移、右移、跳跃、本地主动说话和 API 主动说话。
- 当前代码中自动移动仍会在 `_chat_in_progress()` 或拖拽时跳过。测试左移、右移、跳跃使用 `_movement_locked()` 判断，避免退出或拖拽时移动。

配置加载流程：

- `DesktopPetWindow._load_app_config()` 使用 `load_json_prefer_primary(config/app_config.json, config/app_config.example.json, {})`。
- 如果主配置存在，读取主配置；如果不存在，读取示例配置；如果两者都不存在，才按默认值创建主配置。
- `DeepSeekClient` 和 `ContextManager` 也使用相同的主配置优先、示例配置兜底策略。

构建流程：

- 当前没有构建或打包脚本。第一版目标是本机运行，不要求打包。
- 推测：未来若要发布 Windows 可执行文件，可考虑 PyInstaller，但项目中尚无相关配置。

测试流程：

- 当前没有 `tests/` 目录，也没有 pytest、unittest、CI、格式化器配置。
- 已使用过的轻量校验方式是 AST 解析和手动启动。
- `py_compile` 在本环境可能因为 `__pycache__` 写入权限失败，不适合作为唯一验证方式。

## 5. 重要模块之间的关系

- `main.py` 只负责启动和早期诊断，业务集中在 `DesktopPetWindow`。
- `DesktopPetWindow` 持有并连接 `SpritePlayer`、`SpeechBubble`、`ChatInput`、`FormalAnswerPanel`、`BehaviorController`、`ChatStore`、`UsageStore`、`MemoryStore`、`DeepSeekClient`、`PromptBuilder`、`ContextManager` 和 `Summarizer`。
- `SpritePlayer` 只负责动作帧和 pixmap，不直接移动窗口。窗口位移由 `DesktopPetWindow` 的 `QPropertyAnimation` 处理。
- `PromptBuilder` 不直接调用 API；它只组装 messages。`DeepSeekClient` 只发送请求。
- `ChatStore` 是上下文、摘要和聊天记录的共同来源。
- `Summarizer` 依赖 `ChatStore`、`MemoryStore` 和 `DeepSeekClient`，但摘要失败会记录日志并退出，不应阻断聊天。
- `BehaviorController` 不直接操作 UI，只发信号给主窗口。

## 6. 常见开发任务的推荐阅读路径和修改路径

新增右键菜单项：

1. 读 `app/context_menu.py` 的 `build_context_menu()`。
2. 读 `DesktopPetWindow._show_context_menu()` 的回调注入。
3. 在主窗口添加处理函数，并确认是否需要保存到 `app_config`。
4. 如果新增配置项，同步更新 `config/app_config.example.json` 和本文件。

修改聊天或 API 行为：

1. 读 `DesktopPetWindow._handle_user_message()`。
2. 读 `ChatWorker.run()`、`ai/prompt_builder.py`、`ai/deepseek_client.py`。
3. 如果影响上下文或摘要，再读 `ai/context_manager.py` 和 `ai/summarizer.py`。
4. 修改后至少验证本地回复、未配置 API key、配置 API key 三种分支。

修改正式问答模式：

1. 读 `DesktopPetWindow._show_answer_output()` 和 `_show_formal_answer_panel()`。
2. 读 `app/formal_answer_panel.py`。
3. 检查关闭面板后的引用清理，避免残留对象。
4. 若新增显示模式，同步更新 `chat.formal_answer_display` 配置和右键菜单。

修改动作或素材：

1. 读 `assets/sprite_config.json` 和 `xiaohu_codex_package/xiaohu_codex/SPRITE_SHEET_SPEC.md`。
2. 读 `animation/sprite_player.py`。
3. 读主窗口中所有 `set_action()` 调用。
4. 确认动作名与配置、素材行、菜单测试项一致。

修改窗口显示、透明背景、位置、移动：

1. 读 `DesktopPetWindow._setup_window()`、鼠标事件、`_restore_position()`、`_trigger_auto_move()`、`_start_horizontal_move_test()`、`_start_jump_auto_move()`。
2. 多屏和屏幕外恢复要特别小心，先保留 `window_state.json` 可见性检查。
3. 修改后手动测试拖拽、保存位置、右下角初始位置、左移、右移、跳跃、退出。

修改主动话术：

1. 读 `character/behavior_controller.py`。
2. 读 `config/local_lines.json`。
3. 读 `storage/usage_store.py`。
4. 确认免打扰、每日上限和等待用户回复逻辑没有被绕过。

修改持久化数据结构：

1. 读 `storage/json_store.py`。
2. 读对应 store 文件。
3. 读所有引用该 JSON 的模块。
4. 必须考虑旧数据文件兼容，因为 `data/` 是用户本地运行时数据。

## 7. 代码风格和项目约定

- Python 代码普遍使用 `from __future__ import annotations`。
- 类名使用 PascalCase，函数和方法使用 snake_case。
- Qt 事件方法保留 Qt 命名，如 `mousePressEvent`，并用 `# noqa: N802`。
- JSON 文件使用 UTF-8，`save_json()` 使用 `ensure_ascii=False` 和 `indent=2`。
- 运行时缺失 JSON 文件应自动创建，优先使用 `storage/json_store.py`。
- API key 不得写死在代码或示例外的共享文件中。真实 key 放在被忽略的 `config/app_config.json`。
- UI 和业务目前没有明显分层到 MVC，主窗口承担协调职责。小功能可以沿用现有模式，较大功能再考虑拆模块。
- 后台 API 请求使用 `QThread + QObject worker`，不要在 UI 线程中直接请求网络。
- 摘要使用普通 `threading.Thread` 后台运行，异常需吞掉并记录日志。
- 当前代码里有大量中文文案和注释。新增面向用户的文案应使用中文，并注意文件编码。

## 8. 高风险修改区域

`DesktopPetWindow`

- 风险最高。聊天、窗口、动作、状态、菜单和后台线程都集中在这里。
- 修改前先定位信号和状态变量，不要只改一个分支。

`main.py` 早期启动日志

- 用于排查 PySide6 导入前后的静默退出。不要轻易移除 `_write_boot_log()`。

`json_store.py`

- 影响所有配置和运行时数据。修改默认创建、解析失败或保存行为时，要考虑用户旧数据和权限问题。

`app_config.example.json`

- 是无 `app_config.json` 时的兜底配置。新增配置项如果只写代码不写示例，会导致新设备行为不一致。

`DeepSeekClient` 和 `PromptBuilder`

- 影响外部请求、模型输出、安全规则和上下文。修改时要兼顾无 key、本地回复、API 错误、正式问答模式。

`SpritePlayer` 和 `sprite_config.json`

- 动作名、帧数、行列、帧率和缩放互相绑定。新增动作时必须同步菜单、调用点和素材。

`FormalAnswerPanel`

- 关闭销毁和引用清理是内存安全重点。不要让已关闭 panel 继续留在 `formal_answer_panels`。

`.gitignore`

- 用于只上传程序本体。不要把 `desktop_pet/data/`、日志、缓存、真实 `app_config.json` 放开。

## 9. 常用命令

安装依赖：

```powershell
cd desktop_pet
py -m pip install -r requirements.txt
```

启动程序：

```powershell
cd desktop_pet
py main.py
```

查看早期启动日志：

```powershell
Get-Content .\data\startup_bootstrap.log -Tail 80
```

查看应用日志：

```powershell
Get-Content .\data\app.log -Tail 80
```

检查 Python 命令指向：

```powershell
py -V
Get-Command python | Format-List Name,Source,Path,CommandType
where.exe python
```

语法和 AST 轻量检查，不写 `__pycache__`：

```powershell
@'
import ast
from pathlib import Path
for path in Path("desktop_pet").rglob("*.py"):
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    print(f"OK {path}")
'@ | py -3 -B -
```

JSON 合法性检查：

```powershell
@'
import json
from pathlib import Path
for path in Path("desktop_pet").rglob("*.json"):
    json.loads(path.read_text(encoding="utf-8"))
    print(f"OK {path}")
'@ | py -3 -B -
```

查看当前修改：

```powershell
git status --short
```

当前没有以下命令或配置：

- 无 pytest 配置。
- 无格式化器配置。
- 无 lint 配置。
- 无打包脚本。
- 无 CI 配置。

## 10. 重要依赖和外部服务

Python 依赖见 `desktop_pet/requirements.txt`：

- `PySide6`：桌面窗口、Qt 控件、定时器、信号、动画和图像显示。
- `requests`：调用 DeepSeek API。

外部服务：

- DeepSeek API，默认 `base_url` 为 `https://api.deepseek.com`。
- 请求路径为 `/chat/completions`，请求体包含 `model`、`messages`、`temperature`。
- API key 从 `config/app_config.json` 或示例配置的 `api.api_key` 读取。示例配置默认空 key。

## 11. 待确认问题

- 当前没有自动化测试。需要人工确认是否引入 pytest、Qt 测试工具或最小 smoke test。
- 当前没有构建和打包方案。推测第一版只要求源码运行，是否需要 PyInstaller 或安装包仍待确认。
- `ai/safety_filter.py` 已存在但未接入主流程。是否需要本地高风险请求预过滤待确认。
- `UsageStore` 支持 API 主动次数统计，但当前 API 主动说话测试流程未看到每日 API 主动上限的完整接入。是否需要限制待确认。
- `character/character_profile.py`、`character/emotion_state.py` 当前像是预留结构，主流程未明显依赖。后续是否发展角色状态系统待确认。
- 当前项目里大量中文注释和字符串在 PowerShell 输出中显示为乱码。需要人工确认这是终端编码显示问题，还是源码文本已经发生 mojibake。若实际 UI 文案乱码，应优先修复编码和文案。
- `README.md` 和 `xiaohu_codex_package/` 中部分早期任务提到”清空聊天记录”菜单。当前右键菜单通过 `show_clear_menu` 配置控制，提供了”清除非正式聊天记录”和”清理正式问答记录”两个独立入口。
- 自动移动逻辑当前仍在聊天进行中跳过，测试移动逻辑只避开拖拽和退出。这个差异是否符合产品预期待确认。

## 12. 文档维护规则

- 每次智能体修改代码后，必须检查是否需要同步更新 `AGENTS.md`。
- 如果修改涉及目录结构、核心流程、API、数据结构、配置项、依赖、测试方式、构建方式或项目约定，必须同步更新 `AGENTS.md`。
- 更新文档时，要基于实际代码、配置、测试和注释；不能把未实现的需求写成已实现事实。
- 如果只能推断设计意图，必须写明“推测”。
- 如果无法确认，放入“待确认问题”章节。
- 每次更新都要在下方“文档同步记录”追加一条，说明代码变更摘要和文档更新内容。

## 文档同步记录

- 2026-05-11：新建 `AGENTS.md`。基于当前项目入口、配置、依赖、需求文档、核心业务目录和现有代码梳理项目结构、运行流程、模块关系、常见修改路径、风险区域、常用命令、依赖服务和待确认问题；同时在 `.gitignore` 中放行根目录 `AGENTS.md`，确保该智能体文档可随程序本体提交。本次未改变程序代码。
- 2026-05-11：`BehaviorController` 新增 `_time_greeting_key()` 根据本地时间返回时段问候分组（早/午/晚/深夜），启动问候优先时段话术、空闲和测试话术池混入时段分组；新增 `pick_farewell_line()` 退出时从 `farewell` 组抽取道别语。`DesktopPetWindow.request_exit()` 退出时播放 waving 并显示道别气泡。同步更新 `AGENTS.md` 中 behavior_controller、local_lines、主动行为流、DesktopPetWindow 描述。
- 2026-05-11：新增双击识别功能。`DesktopPetWindow` 新增 `mouseDoubleClickEvent`，双击人物触发 `pick_reply_line()` 从 `break_reminder`/`comfort`/`encourage` 随机抽取话术并播放 waving；`mouseReleaseEvent` 改用 `_click_timer` 延迟区分单击与双击，避免双击时误开聊天输入框。`BehaviorController` 新增 `pick_reply_line()`。
- 2026-05-11：新增季节周期问候。`BehaviorController` 新增 `_season_key()` 按月份划分四季、`_is_cycle_start()` 按每年第几天判断 5 天周期首日。`_startup_greeting()` 在周期首日优先季节问候，其次时段问候，最后回退 `startup`。`local_lines.json` 新增 `greeting_spring`/`greeting_summer`/`greeting_autumn`/`greeting_winter` 四组季节话术。
- 2026-05-11：新增窗口置顶开关。右键菜单增加"窗口置顶"可勾选项，`_toggle_always_on_top()` 控制 `WindowStaysOnTopHint` 并持久化到 `ui.always_on_top`。关闭置顶时从 `return_after_idle` 分组随机抽取话术展示。`BehaviorController` 新增 `pick_ignored_line()`。
- 2026-05-11：新增聊天输入等待提示。`DesktopPetWindow` 新增 `_waiting_timer`，打开输入框 30 秒后无提交则从 `waiting` 分组抽取话术展示，之后每 25 秒重复提醒；用户提交时停止计时器。`BehaviorController` 新增 `pick_waiting_line()`。
- 2026-05-11：新增测试菜单显隐配置。`app_config.example.json` 的 `ui` 节新增 `show_test_menu` 项（默认 `false`）。`context_menu.py` 的 `build_context_menu()` 新增同名参数，整个测试子菜单在条件不满足时跳过构建。`DesktopPetWindow._show_context_menu()` 从配置读取并传入。
- 2026-05-11：修复窗口置顶两个问题。(1) `SpeechBubble` 新增 `set_always_on_top()`，`_display_message()` 每次显示前同步主窗口置顶状态，消除气泡不受置顶开关控制的问题。(2) 纠正话术对应关系：`_toggle_always_on_top()` 开启置顶时调用 `pick_return_after_idle_line()` 回复 `return_after_idle`，关闭时调用 `pick_ignored_line()` 回复 `ignored`。
- 2026-05-11：新增时段变化自动问候。`BehaviorController` 新增 `period_check_timer`（每 60 秒）和 `_check_period_change()`，跟踪 `_last_time_key` 和 `_last_season_key`。当时段（早/午/晚/深夜）或季节发生变化时，立即弹出新时段对应的话术问候。
- 2026-05-11：新增主动问候后双击反馈。`BehaviorController` 新增 `is_within_proactive_reply_window()` 判断 60 秒回复窗口、`pick_feedback_line()` 从 `feedback` 分组抽取。`mouseDoubleClickEvent` 在窗口内双点击时优先用 `feedback` 话术，否则回退普通双击回复。`local_lines.json` 新增 `feedback` 分组。
- 2026-05-11：新增念诗测试功能。右键测试菜单增加"念一首诗"，`_test_poetry()` 从 `poetry` 分组随机抽取并播放 waving 展示。`local_lines.json` 新增 `poetry` 分组。`BehaviorController` 新增 `pick_poetry_line()`。
- 2026-05-11：聊天输入念诗关键词检测。`_handle_user_message()` 在特定条件下（API 关闭、正式问答关闭、自主移动关闭、窗口置顶关闭）检测念诗相关关键词，命中时直接从本地 `poetry` 话术回复并播放 `running` 动作。
- 2026-05-11：聊天输入框置顶跟随。`ChatInput` 新增 `set_always_on_top()`，`_open_chat_input()` 和 `_toggle_always_on_top()` 中同步输入框置顶状态与主窗口一致。
- 2026-05-11：聊天历史分裂为正式/非正式双轨。`ChatStore` 新增 `last_cleaned_at` 字段和时间清理判断方法；`ContextManager` 改为接收两个 store 并按模式选择；`PromptBuilder` 改为接收两个 summary 路径按模式选择；`Summarizer.maybe_summarize()` 新增 `force` 参数；`DesktopPetWindow` 新增双 store/双 summary 实例、`_pending_was_formal` 快照防止路由错乱、`_cleanup_timer` 每小时检查时间清理（正式 6 个月/非正式 3 个月）、`_active_chat_store()` 辅助方法。`app_config.example.json` 新增 `formal_cleanup_months`、`informal_cleanup_months`。
- 2026-05-11：新增清理聊天记录右键菜单。`app_config.example.json` 新增 `ui.show_clear_menu` 配置（默认 `false`）；`context_menu.py` 新增"清除非正式聊天记录""清理正式问答记录"两个菜单项；`DesktopPetWindow` 新增 `_clear_informal_chat_history()`、`_clear_formal_chat_history()` 方法。
- 2026-05-11：清理记录前先总结。`_clear_informal_chat_history()` 和 `_clear_formal_chat_history()` 在清空前先调用 `maybe_summarize(force=True)` 生成摘要，再清空消息并更新 `last_cleaned_at`。`app_config.example.json` 新增 `chat.force_summarize_before_clear` 配置（默认 `true`）控制是否强制总结。
