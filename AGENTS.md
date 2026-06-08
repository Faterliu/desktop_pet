# AGENTS.md

面向未来 AI 编程智能体的项目接手文档。它不是普通 README，而是为了让第一次进入本仓库的智能体在 5 分钟内知道先读哪里、改哪里、哪些地方不要贸然动。

## 5 分钟快速概览

- 一句话概览：这是一个基于 Python 和 PySide6 的 Windows 桌面 AI 宠物原型，角色通过像素 spritesheet 显示在桌面上，可聊天、主动问候、保存本地 JSON 数据，并可调用 DeepSeek API。
- 实际可运行程序在 `desktop_pet/` 目录内，入口是 `desktop_pet/main.py`。根目录的 `README.md` 是更新日志，`xiaohu_codex_package/xiaohu_codex/` 是早期需求、任务和素材说明。
- 启动建议第一次先运行 `desktop_pet/setup_env.bat` 创建项目本地虚拟环境并安装依赖，之后日常双击 `desktop_pet/start_main.vbs` 无终端启动。手动启动仍可 `cd desktop_pet` 后执行 `py -m pip install -r requirements.txt` 和 `py main.py`。不要默认信任 `python` 或 `pip`，它们在 Windows 上可能指向应用商店别名或旧解释器。
- 主协调器是 `desktop_pet/app/desktop_pet_window.py`。多数 UI、聊天、配置、动作、自动移动、正式问答、退出流程都从这里串起来。
- 运行时个性化数据不应提交：`desktop_pet/config/app_config.json`、`desktop_pet/data/`、日志和缓存都由 `.gitignore` 忽略。默认配置模板是 `desktop_pet/config/app_config.example.json`。
- 当前没有独立测试框架、构建脚本或打包流程，但 `desktop_pet/tests/` 已有 `unittest` 回归测试。常用校验是项目本地虚拟环境执行 `python -m unittest discover -s desktop_pet/tests`、JSON 合法性、Python AST/语法检查、手动运行桌宠。
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

快速启动：

```powershell
cd desktop_pet
.\setup_env.bat
wscript.exe .\start_main.vbs
```

注意：

- `python main.py` 只有在 `python` 指向真实解释器时才可靠。此前移植排查中，`python` 指到 `Microsoft\WindowsApps\python.exe` 时会出现无输出、无窗口、无 `data/` 的情况。
- `pip install -r requirements.txt` 可能命中旧版 Python 的坏掉 `pip.exe` 启动器。优先使用 `py -m pip install -r requirements.txt`。
- `setup_env.bat` 负责环境准备：只接受能运行 `python -m pip --version` 且支持 `venv` 的解释器，优先查找 Miniforge，其次查找 `uv` 安装的 CPython 3.13、`py -3.13`、`py -3`、当前 `python`；如果都不可用，会尝试通过 `winget install --id Python.Python.3.13 -e --source winget --accept-package-agreements --accept-source-agreements` 安装 Python。随后创建项目本地 `desktop_pet/.desktop_pet_venv`，依赖安装进该本地环境，并把 `.desktop_pet_venv/Scripts/python.exe` 无换行保存到 `data/runtime_python.txt`。该脚本不再向全局 Python 安装项目依赖。
- `start_main.vbs` 是默认无终端启动入口：先在仓库根目录执行 `git pull --ff-only` 尝试拉取当前分支最新代码，再读取并清理 `data/runtime_python.txt` 中的回车、换行、制表符和 BOM，确认对应 Python 路径存在后直接隐藏执行 `main.py`，输出写入 `data/start_main_error.log`；拉取失败只写入 warning 并继续启动，只有缺环境或 `main.py` 非零退出时，才打开错误终端并显示日志。依赖完整性由 `setup_env.bat` 负责校验，日常启动不再额外执行 `import PySide6, requests` smoke check。
- 程序启动后应创建 `desktop_pet/data/startup_bootstrap.log` 和 `desktop_pet/data/app.log`。前者在导入 PySide6 前写入，用于早期启动排查。

## 3. 关键目录和文件说明

`desktop_pet/main.py`

- 程序入口。先写 `data/startup_bootstrap.log`，再导入 PySide6、配置日志、创建 `QApplication` 和 `DesktopPetWindow`。
- 修改场景：启动失败诊断、Qt 应用生命周期、窗口显示和事件循环策略。
- 风险：过早导入业务模块会削弱早期日志的诊断价值。

`desktop_pet/app/desktop_pet_window.py`

- 核心协调器。负责窗口属性、鼠标事件（单击聊天、双击回复/打招呼、拖拽移动、右键菜单，含置顶开关）、聊天流程、后台线程、正式问答面板、自动移动、位置恢复和退出动画（退出时播放 waving 并显示 `farewell` 道别气泡）。
- `_enforce_topmost()` 由 `_topmost_enforcement_timer` 每 30 秒驱动，通过 `force_window_topmost()` 在 Windows API 级别强制 `WS_EX_TOPMOST`，防止频繁 `setMask()` 导致置顶样式被系统清除。
- `_sync_floating_widgets()` 在气泡/输入框跟随角色位置时，将对方可见气泡的 `geometry()` 作为 `exclusion_rects` 传入 `reposition()`，使两个气泡互相避让不重叠。
- 空闲主动问候命中场景化生成时，`BehaviorController` 发出 `scenario_greeting_requested`，主窗口创建 `ScenarioGreetingWorker` 放入独立 `QThread` 调用 DeepSeek 生成一句短问候；API 不可用、线程忙或生成失败时静默回退到本地模板，不向用户显示错误。
- 清理正式/非正式聊天记录时不再在 UI 线程中强制摘要，而是创建 `ChatHistoryClearWorker` 放到独立 `QThread` 执行摘要、清空和 `last_cleaned_at` 更新；主窗口只接收完成/失败信号并在后台操作结束后决定是否显示结果。
- 退出时若聊天请求或清理线程仍在运行，`closeEvent()` 会延迟真正关闭，等待后台线程 `finished` 后再重新调用 `close()`，避免销毁仍在运行的 `QThread`。
- 修改场景：几乎所有用户可见行为的入口都在这里接线。
- 风险：文件较大，多个状态互相影响，例如 `chat_thread`、`clear_history_thread`、`move_animation`、`behavior_controller`、`formal_answer_panels`、`exit_animation_in_progress`、`_close_after_workers_finished`、`_click_timer`、`_suppress_click`、`_waiting_timer`、`_pending_was_formal`、`_topmost_enforcement_timer`。

`desktop_pet/app/history_clear_worker.py`

- 后台清理 worker。`ChatHistoryClearWorker.run()` 在非 UI 线程中按配置强制摘要、清空对应 `ChatStore`，并更新 `last_cleaned_at`。
- 修改场景：清理聊天历史、清空前摘要、清理失败降级。
- 风险：worker 不应直接操作任何 QWidget 或气泡；UI 展示必须留在 `DesktopPetWindow` 的信号回调中。

`desktop_pet/app/context_menu.py`

- 构建右键菜单，包括测试菜单（由 `ui.show_test_menu` 控制，默认关闭）、清理菜单（由 `ui.show_clear_menu` 控制，默认关闭，可分别清除非正式和正式聊天记录）、重新加载配置（由 `ui.show_reload_config` 控制，默认开启）、人物缩放、免打扰、窗口置顶、自主移动、聊天 API 开关、正式问答模式和退出。
- 修改场景：新增菜单项或调整菜单可见入口。
- 注意：菜单回调由 `DesktopPetWindow._show_context_menu()` 注入，新增菜单通常要同步改两处。

`desktop_pet/app/chat_input.py`

- 悬浮聊天输入框，跟随角色位置，Enter 或发送按钮提交，关闭按钮隐藏。
- 修改场景：输入框布局、提交行为、关闭行为、跟随位置。

`desktop_pet/app/speech_bubble.py`

- 短消息气泡，自动关闭，跟随角色位置。`show_message()` 前由主窗口调用 `set_always_on_top()` 同步置顶状态。
- 模块级 `_find_bubble_position()` 为两个气泡提供屏幕感知定位：遍历候选方位列表，选取第一个完全在屏幕可用区域内、不与角色锚点重叠、且不与 `exclusion_rects` 交叉的位置；所有候选不满足时 clamp 首选到屏幕内。
- `SpeechBubble.reposition()` 和 `ReplyBubble._reposition()` 均通过 `_find_bubble_position()` 实现多方位自动避让（上/下/左/右），避免气泡超出屏幕或覆盖人物。
- `ReplyBubble`：知识问候右侧独立应答气泡，可点击、无尾巴、绿色配色，点击发出 `clicked` 信号供主窗口处理用户回应。
- 修改场景：本地提示、普通聊天回复、系统提示的展示样式和定位；新增气泡方位或避让规则。

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

`desktop_pet/ai/mem0_memory_service.py`

- 可选 Mem0 长期语义记忆封装层。负责初始化 Mem0、写入摘要提取出的长期记忆、根据当前用户输入检索相关记忆，并格式化为 Prompt 可注入文本。
- 由 `config/app_config.json` / `app_config.example.json` 中的 `memory.enable_mem0`、`memory.inject_mem0_to_prompt`、`memory.use_mem0_for_knowledge_speak`、`memory.mem0_search_top_k`、`memory.write_sensitive_memory` 等配置控制；默认关闭。
- 若 `memory.enable_mem0` 为 true 但 DashScope embedding key 为空，服务会记录 info 后直接降级为不可用，不导入 `mem0`，也不创建 Qdrant/history 目录，避免启动 warning、额外目录创建和初始化延迟。只有存在 `memory.dashscope_api_key` 或 `memory.dashscope_api_key_env` 指向的环境变量时，才继续 `Memory.from_config()` 初始化。主窗口不再在 UI 线程中直接构造或重建 Mem0；启动和重新加载配置时通过 `Mem0InitializationWorker` 放入独立 `QThread` 执行，完成后再回到主线程替换 `mem0_memory_service` 并同步给两个 `Summarizer`。
- 初始化使用 `Memory.from_config(config)`，LLM provider 固定走 Mem0 官方支持的 `deepseek` provider。默认复用项目现有 `api.api_key`、`api.base_url`、`api.model`；若 `memory.mem0_deepseek_model` 或 `memory.mem0_deepseek_base_url` 非空，则优先使用 memory 节点下的覆盖值。
- Mem0 embedder 使用 DashScope / 阿里云百炼 OpenAI-compatible embeddings 接口，内部通过 Mem0 的 OpenAI embedder 传入 `openai_base_url` 和 `embedding_dims`。默认 base URL 为 `https://dashscope.aliyuncs.com/compatible-mode/v1`，模型为 `text-embedding-v4`，维度为 1024。
- DashScope API Key 优先从 `memory.dashscope_api_key` 读取，若为空则读取 `memory.dashscope_api_key_env` 指定的环境变量，默认 `DASHSCOPE_API_KEY`。示例配置和文档不得写入真实 key。
- 默认 Qdrant 向量库路径为 `desktop_pet/data/mem0_qdrant`，history sqlite 路径为 `desktop_pet/data/mem0_history.db`，并显式使用 1024 维，避免与 Mem0 默认 1536 维不匹配。
- 修改场景：更换记忆后端、调整检索 top_k、配置 LLM/embedder/vector store、增加记忆删除或导出功能。
- 风险：Mem0 可能依赖外部 LLM 或 embedding 服务，异常必须降级，不得阻断聊天、摘要、启动或退出主流程。

`desktop_pet/ai/prompt_builder.py`

- 组装系统提示、角色设定、安全规则、正式/非正式模式说明、`memory.json` 记忆、可选 Mem0 检索记忆、摘要（按正式/非正式模式选择对应文件）和上下文消息。`build_messages()` 支持 `relevant_memories` 可选参数，用于在系统提示中注入与当前用户输入相关的长期语义记忆。
- 本地 `memory.json` 注入已拆成三个明确区块：`【用户事实记忆】` 用于项目、偏好、背景和当前任务；`【相处方式记忆】` 用于语气、详细程度、确认频率、陪伴边界等关系/风格记忆，并明确要求不要直接复述给用户；`【当前问题相关的长期语义记忆】` 用于 Mem0 检索结果，只在与当前问题直接相关时参考。随后追加 `【表达约束】`，要求不要频繁使用“你之前说过”、不要暴露 memory.json/Mem0/数据库等实现细节、旧记忆与当前表达冲突时以当前表达为准。
- 正式问答模式下，事实记忆可用于理解项目背景，关系记忆只用于回答结构、详细程度和确认频率，减少闲聊和陪伴式铺垫；普通陪伴聊天模式下，关系记忆可以自然影响语气和建议，但不应表现为读取档案。
- 修改场景：人格、回复风格、安全规则优先级、正式问答回答策略。
- 风险：安全规则必须优先于角色 `custom_prompt`。

`desktop_pet/ai/context_manager.py`

- 根据配置读取最近聊天上下文（按正式/非正式模式选择对应 store），并判断是否达到摘要触发条件。
- 修改场景：上下文长度、摘要轮数策略。

`desktop_pet/ai/summarizer.py`

- 在聊天后尝试摘要历史。若 API 可用，会要求模型输出 JSON；失败时退回本地简化摘要，并合并记忆。`maybe_summarize()` 支持 `force` 参数，为 True 时跳过轮数检查，供手动清空聊天记录前使用；但若历史中没有非空用户消息，会直接跳过，避免空聊天记录生成错误记忆。
- 当前模型摘要与模型记忆提取已拆分：摘要仍基于最近完整对话生成，但 `memory_updates` 只基于用户发言单独提取，避免把人物/助手回答混入 `memory.json`；摘要文件本身不再落盘 `memory_updates`。模型记忆提取 schema 兼容旧的 `user_profile`/`work_study` 输出，也支持新增 `relationship_memory` 输出，用于记录沟通偏好、相处方式和近期互动模式。关系记忆规则强调只记录互动偏好和相处方式，不输出心理诊断、医学判断或人格标签。
- 若模型记忆提取返回合法但没有任何实际文本的空结构，`Summarizer` 会继续回退到本地规则提取；正式问答模式下，本地规则会把用户的非空问题作为 `work_study.current_learning_topics` 兜底保存。非正式/正式模式判断需先判 `informal` 再判 `formal`，避免 `conversation_summary_informal.json` 因文件名包含 `formal` 子串被误判。当前本地 `current_learning_topics` 关键词包括：`学习`、`复习`、`知识`、`课程`、`算法`、`请问`、`怎么做`、`如何实现`、`如何`、`怎么`、`是什么`、`为什么`、`区别`。关系记忆本地兜底只覆盖少量明确表达：不要/别/不用确认会写入 `confirmation_preference=avoid_unnecessary_confirmation`；“直接给”“可执行方案”会写入 `preferred_response_style=direct_actionable`；“详细一点”等会写入 `detail_level=high`；“数据库/数据存储器/机械化记忆/像工具”等会写入避免机械化记忆表达。只有包含非空记忆文本时才合并 `memory.json` 并旁路写入 Mem0，避免清理聊天时只刷新空记忆时间戳。
- 若启用 Mem0，`Summarizer` 在保留原 `memory.json` 合并逻辑的同时，会将提取出的 `memory_updates` 旁路写入 Mem0，作为长期语义检索数据源；Mem0 写入失败只记录 warning，不得影响摘要或聊天主流程。摘要触发以新增用户消息批次为准：首次达到 `api.summary_trigger_rounds` 后触发，之后需自上次 `covered_message_count` 以来再新增同等数量的用户消息才会再次摘要，避免达到阈值后每轮聊天都重摘要。
- 修改场景：摘要结构、记忆提取、失败兜底。
- 风险：摘要在线程中触发，异常不能影响正常聊天。

`desktop_pet/ai/safety_filter.py`

- 简单关键词高风险检测函数。当前未在主聊天流程中直接使用。
- 修改场景：接入本地安全预过滤。
- 待确认：是否计划把它接到 `_handle_user_message()` 或 `PromptBuilder` 前置流程。

`desktop_pet/character/proactive_context.py`

- 场景化主动问候的纯逻辑模块。`build_proactive_context()` 从 `memory.json` 中挑选少量近期任务、沟通偏好、陪伴边界和互动模式，避免把完整记忆原样塞给模型；`build_local_scenario_greeting()` 使用 `scenario_greeting_templates` 或 `low_interrupt` 本地模板回退；`build_scenario_greeting_messages()` 构造 API prompt，要求只输出一句短中文，不说“根据记忆”“你之前说过”，不暴露 memory.json、Mem0、数据库或配置细节。
- 修改场景：主动问候上下文选择、本地模板回退、场景化问候 Prompt 规则。
- 风险：不要在这里引入 UI、QThread 或网络请求；它应保持可单元测试的纯逻辑。

`desktop_pet/storage/*.py`

- `json_store.py`：JSON 读写基础设施，缺文件时自动创建父目录和默认文件；保存时先写同目录 `.tmp`，`flush` + `os.fsync` 后用 `os.replace` 原子替换目标文件，并在目标文件非空时保留 `.bak`；读取遇到损坏 JSON 时会先把主文件重命名为 `.corrupt.<timestamp>`，再优先读取 `.bak`，备份也不可用时返回默认值深拷贝。`cleanup_tmp_json_files()` 用于清理中断写入留下的 `.tmp` 文件。
- `chat_store.py`：保存和读取正式/非正式聊天记录（`chat_history_formal.json` / `chat_history_informal.json`），记录 `last_cleaned_at` 时间戳供手动清空时标记。
- `memory_store.py`：保存和合并 `data/memory.json`。读取、保存和合并时会通过 `normalize_memory_schema()` 兼容旧结构并补齐 v2 默认字段：`relationship_memory.communication_style`、`relationship_memory.companionship_style`、`relationship_memory.interaction_patterns` 和 `memory_meta.schema_version=2`；补齐时保留未知旧字段，不会清空用户已有记忆。保存/合并仍写入 UTF-8 JSON，并同步更新顶层 `last_updated` 与 `memory_meta.last_updated`；合并关系记忆时会为被更新的关系子区块写入 `last_updated` 或 `last_observed_at`。
- `memory_vector_store.py`: maintains compact machine-written `data/memory_vectors.json` for eligible `memory.json` text leaves. It uses the existing DashScope OpenAI-compatible embedding config, rounds embeddings according to `memory.memory_vector_precision`, skips texts shorter than `memory.memory_vector_min_text_length`, limits stored entries with `memory.memory_vector_max_items`, includes precision in `embedding_signature`, skips cleanly when no key or `requests` is unavailable, and supports same-field semantic duplicate merging on a two-month cadence.
- `usage_store.py`：每日主动话术和 API 主动次数计数。
- 修改场景：数据结构、持久化策略、运行时数据兼容。

`desktop_pet/character/behavior_controller.py`

- 管理启动问候、空闲主动话术和时段变化检测。用 `QTimer` 每 60 秒检查空闲和时段，受免打扰、每日上限、空闲时间和等待用户回复状态约束。
- `_startup_greeting()` 会先读取 `local_lines.json` 的 `first_start.enable`；为 true 时从 `first_start.data` 随机取一句启动问候，并在成功取到后立刻写回 `enable=false`，使其只触发一次。若未命中，则保留原优先级：每 5 天周期首日优先季节问候（`greeting_spring`/`greeting_summer`/`greeting_autumn`/`greeting_winter`），其次当前时段问候（`greeting_morning`/`greeting_noon`/`greeting_afternoon`/`greeting_evening`/`sleepy`），最后回退到 `startup`。启动问候受免打扰和 `startup_greeting` 开关控制，但不受每日主动话术上限拦截，也不递增 `local_proactive_lines_used`。
- `_maybe_idle_prompt()` 和 `trigger_test_speak()` 的话术池会混入当前时段分组。`trigger_test_idle_prompt()` 绕过时间限制测试完整空闲逻辑，返回触发类型和比例字符串。
- `_check_period_change()` 由 `period_check_timer` 每 60 秒驱动，检测时段或季节是否变化，变化时立即弹出新时段问候。
- `pick_farewell_line()` 从 `farewell` 分组随机抽取道别语，供退出流程使用。
- `pick_reply_line()` 从 `break_reminder`/`comfort`/`encourage` 三组随机选取回应话术，供普通双击回复使用。
- `pick_feedback_line()` 从 `feedback` 分组随机选取，用于用户在主动问候窗口内双击回应。
- `is_within_proactive_reply_window(window_seconds=60)` 判断当前是否在上次主动问候后 60 秒内。
- `pick_ignored_line()` 从 `ignored` 分组随机选取话术，供关闭置顶时使用。
- `pick_return_after_idle_line()` 从 `return_after_idle` 分组随机选取话术，供开启置顶时使用。
- `pick_waiting_line()` 从 `waiting` 分组随机选取等待提示话术，供聊天输入框长时间无输入时使用。
- `pick_reply_ack_line()` 从 `reply` 分组随机选取简短应答话术，供知识问候展示后确认。
- `_consecutive_unanswered` 计数器驱动动态问候间隔：首次 15min → 第二次 15min → 第三次 30min → 第四次起 30-60min 随机（最高 60min），并受 `behavior.min_proactive_interval_minutes` 作为下限约束。`notify_user_interaction()` 和每次 `_maybe_idle_prompt()` 成功触发问候后均重置计数。
- `_has_memory_content()` 检查 `memory.json` 是否有可用记忆信息。`_proactive_ratio()` / `_adjust_ratio()` 管理主动问候内容类型比例。`notify_proactive_response()` 在用户回应时调用比例调整：回应类型 +0.005，互斥类型 -0.001，并继续受 0.3-0.7 钳制；主窗口传入 `config_saver` 时会把调整后的 `proactive_content_ratio` 持久化回 `app_config.json`。
- `behavior.max_local_lines_per_day` 通过安全整数解析读取，非法、空值或非正数会回退到 10，避免本地配置错误导致 QTimer 回调异常。
- 当 `memory.use_mem0_for_knowledge_speak` 为 true 时，`_has_memory_content()` 会在知识问候概率命中后，优先通过主窗口传入的 Mem0 检索回调判断是否存在长期语义记忆；主窗口会用 `Mem0SearchWorker` 在独立 `QThread` 中一次性取回 `top_k=3` 的 Mem0 上下文并暂存给 `KnowledgeSpeakWorker` 复用，避免判断和生成阶段重复检索，也避免主动问候计时器回调阻塞 UI。检索进行中时返回 `None`，`BehaviorController._maybe_idle_prompt()` 会跳过本轮普通问候兜底，待检索成功后由主窗口触发知识问候；Mem0 不可用或无结果时回退到原 `memory.json` 检查。
- 场景化主动问候由 `behavior.enable_scenario_greeting` 控制，默认开启但带 60 分钟冷却。基础守卫（免打扰、主动聊天开关、每日上限、动态间隔）通过后，若连续未回应达到 `scenario_greeting_low_interrupt_after_ignored`，优先使用 `low_interrupt` 低打扰话术；否则在冷却结束且 `memory.json` 中有足够近期任务或关系记忆时，构造场景上下文。`scenario_greeting_api_enabled` 为 true 且 API 主动额度可用时发出 `scenario_greeting_requested` 交给主窗口后台 worker，否则使用本地模板。
- 主动问候气泡停留时间改为读取 `ui.bubble_durations_ms`：启动问候取 `startup_greeting`，时段变化问候取 `period_greeting`，普通空闲/测试问候取 `proactive_greeting`。
- 修改场景：主动行为频率、话术分组、免打扰逻辑、时段判断规则、知识问候与内容比例。

`desktop_pet/config/app_config.example.json`

- 默认配置模板。运行时优先加载 `config/app_config.json`，没有时加载此示例。包含 `ui.show_test_menu` 控制测试菜单显隐（默认 `false`）、`ui.show_clear_menu` 控制清理菜单显隐（默认 `false`）、`ui.show_reload_config` 控制“重新加载配置”菜单项显隐（默认 `true`）、`chat.force_summarize_before_clear`（默认 `true`）控制手动清空前是否强制摘要。
- `ui.bubble_durations_ms` 用于配置主要气泡停留时长：`startup_greeting`、`period_greeting`、`proactive_greeting`、`assistant_reply`。
- `behavior.enable_scenario_greeting`、`behavior.scenario_greeting_api_enabled`、`behavior.scenario_greeting_max_chars`、`behavior.scenario_greeting_min_memory_items`、`behavior.scenario_greeting_cooldown_minutes`、`behavior.scenario_greeting_low_interrupt_after_ignored` 控制场景化主动问候；默认保守启用，限制为 80 字、至少 1 条可用记忆、60 分钟冷却，连续 2 次未回应后走低打扰话术。
- `memory.enable_mem0` 控制是否启用 Mem0 长期语义记忆；`memory.inject_mem0_to_prompt` 控制是否将 Mem0 检索结果注入聊天 Prompt；`memory.use_mem0_for_knowledge_speak` 控制知识问候是否优先使用 Mem0；`memory.mem0_search_top_k` 控制每轮检索数量；`memory.mem0_llm_provider` 默认 `deepseek`，`memory.mem0_use_app_deepseek_config` 默认复用项目 DeepSeek 配置，`memory.mem0_deepseek_model` / `memory.mem0_deepseek_base_url` 可覆盖模型和 base URL；`memory.mem0_embedder_provider` 默认 `dashscope_openai_compatible`，通过 DashScope / 阿里云百炼 OpenAI-compatible embeddings 接口使用 `text-embedding-v4` 和 1024 维向量；`memory.dashscope_api_key` / `memory.dashscope_api_key_env` 控制 DashScope key 来源；`memory.write_sensitive_memory` 默认 false，用于避免情绪陪伴场景下自动保存敏感长期记忆。
- `memory.enable_memory_vectors` controls local vector indexing for `memory.json`; `memory.memory_vector_precision`, `memory.memory_vector_min_text_length`, and `memory.memory_vector_max_items` control vector file size; `memory.enable_semantic_memory_merge`, `memory.semantic_merge_interval_days`, and `memory.semantic_duplicate_similarity_threshold` control the post-startup background semantic duplicate merge.
- `proactive_content_ratio.extra_knowledge` / `regular_greeting` 控制空闲主动问候中知识问候与普通问候的初始比例，当前默认 0.35 / 0.65；运行中用户回应会按 `_adjust_ratio()` 轻微调整，并持续钳制在 0.3-0.7 范围内。
- 修改场景：新增可配置项时必须同步更新此文件，并确认读取路径。

`desktop_pet/config/app_config.json`

- 用户本地个性化配置，可能含 API key。被 `.gitignore` 忽略，不应作为共享默认事实来源。

`desktop_pet/config/character_default.json`

- 默认角色人格、说话风格、口头禅和安全开关。

`desktop_pet/config/local_lines.json`

- 本地主动话术和提示文案。`BehaviorController` 启动问候先看 `first_start.enable`，开启时优先使用 `first_start.data`，成功取用后自动写回 `enable=false`，未命中时继续回退到季节/时段问候和 `startup`；空闲/测试问候主要使用 `idle`、`quiet`、`encourage`，并混入时段分组 `greeting_morning`、`greeting_noon`、`greeting_afternoon`、`greeting_evening`、`sleepy`；季节分组 `greeting_spring`、`greeting_summer`、`greeting_autumn`、`greeting_winter` 用于启动周期问候和时段/季节变化检测。退出时使用 `farewell`。双击回复使用 `break_reminder`/`comfort`/`encourage`，主动问候后双击使用 `feedback`。聊天输入等待超时使用 `waiting`。测试念诗使用 `poetry`。知识问候确认使用 `reply`。场景化问候本地回退使用 `scenario_greeting_templates`，其中 `{task}` 会被近期任务替换；连续未回应后的低打扰回退使用 `low_interrupt`。

`desktop_pet/tools/import_memory_json_to_mem0.py`

- 可选一次性导入工具。读取当前 `data/memory.json` 中的旧结构化记忆，去重后通过 `Mem0MemoryService.add_memory_text()` 写入 Mem0。
- 运行方式：`cd desktop_pet` 后执行 `py tools/import_memory_json_to_mem0.py`。Mem0 未启用、依赖未安装或初始化失败时只打印提示并退出，不影响主程序。

`desktop_pet/tools/test_dashscope_embedding.py`

- 可选 DashScope embedding 连通性测试脚本。优先从 `memory.dashscope_api_key` 读取 key，若为空再读取 `DASHSCOPE_API_KEY`，成功时只打印模型名和向量维度，不打印完整向量。
- 运行方式：`cd desktop_pet` 后执行 `.\.desktop_pet_venv\Scripts\python.exe tools\test_dashscope_embedding.py`。

`desktop_pet/config/safety_rules.json`

- 注入模型提示的安全规则。

`desktop_pet/utils/dwm_border.py`

- `suppress_dwm_border()`：在 `nativeEvent` 中拦截 `WM_NCCALCSIZE` 消除 DWM 为无边框窗口添加的细线边框。
- `apply_transparent_window_fixes()`：对窗口 HWND 移除扩展边缘样式、禁用 DWM 圆角和系统背景渲染。
- `force_window_topmost(hwnd, enabled)`：通过 `SetWindowPos(HWND_TOPMOST)` 直接在 Windows API 级别设置/取消窗口置顶。Qt 的 `WindowStaysOnTopHint` 在频繁 `setMask()`/`resize()` 的透明分层窗口上可能被系统清除，此函数供 `DesktopPetWindow._enforce_topmost()` 每 30 秒周期性调用以确保置顶持久生效。
- 修改场景：窗口透明/边框/置顶在 Windows 侧的底层行为调整。

`desktop_pet/utils/logger.py`

- 配置全局日志，写入控制台和 `desktop_pet/data/app.log`。文件日志使用 `RotatingFileHandler`，默认单个 `app.log` 最多约 1MB，并保留 5 份备份，避免长期运行时日志无限增长。

`desktop_pet/utils/log_sanitizer.py`

- 日志隐私辅助工具。提供 API key 掩码、常见 `Bearer` / `api_key=` 形态脱敏、长文本截断、异常摘要、请求 messages 结构统计和响应结构摘要；AI 模块日志应记录 message_count、chars_count、status_code、响应 keys 等结构信息，不应记录完整 prompt、完整用户输入、完整模型回复、完整 memory 或完整 API response。

`xiaohu_codex_package/xiaohu_codex/`

- 早期需求和实现路线图来源，不是运行时代码。读它可以理解产品意图，但当前行为以 `desktop_pet/` 代码为准。

## 4. 核心执行流程

启动流程：

1. `desktop_pet/main.py` 计算 `project_root`，写入 `data/startup_bootstrap.log`。
2. 导入 `QApplication`、`DesktopPetWindow`、`configure_logging()`。
3. `configure_logging()` 创建 `data/app.log`。
4. 创建 `QApplication`，设置 `setQuitOnLastWindowClosed(False)`。
5. 创建 `DesktopPetWindow(project_root)`。
6. 主窗口初始化配置路径、数据路径、正式/非正式双存储与双摘要器、AI 客户端、提示词构建器、动画播放器、气泡、输入框、主动行为控制器、自主移动计时器。
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
7. `ChatWorker.run()` 读取最近上下文；若启用 Mem0 且 `memory.inject_mem0_to_prompt` 为 true，会在后台线程中按当前用户输入检索长期语义记忆，并传入 `PromptBuilder.build_messages()`；检索失败回退为空结果，不影响原 JSON 记忆流程。
8. `ChatWorker.run()` 调用 `PromptBuilder.build_messages()`，再调用 `DeepSeekClient.chat()`。
9. 成功时 `_on_chat_success()` 保存助手回复，切回 `idle`，按模式显示气泡或正式问答面板，并启动后台摘要线程。
10. 失败时 `_on_chat_failure()` 切到 `failed` 并显示错误。

正式问答显示流：

- `chat.formal_qa_mode` 为 true 时，助手回复不走普通气泡，而走 `_show_formal_answer_panel()`。
- `chat.formal_answer_display` 为 `new_panel` 时，每题新建面板。
- `chat.formal_answer_display` 为 `append` 时，追加到当前可见面板。
- 面板文本是纯文本 `QTextEdit`，可选择复制，关闭后主窗口引用列表会移除。

主动行为流：

1. `BehaviorController` 启动后设置空闲检查计时器，每 60 秒检查一次。
2. 启动问候受 `do_not_disturb` 和 `startup_greeting` 约束，不受每日主动话术上限约束；优先级为 `first_start.data`（仅当 `first_start.enable` 为 true）→ 每 5 天周期首日季节问候 → 当前时段问候 → `startup`；成功展示后不计入本地主动话术次数。
3. 空闲主动话术受 `proactive_chat`、`min_proactive_interval_minutes`、`last_proactive_at`、动态未回应间隔和每日上限约束。若连续未回应达到低打扰阈值，优先从 `low_interrupt` 取一句低打扰问候；若场景化问候开启、冷却结束且记忆上下文足够，则从 `memory.json` 构造近期任务/相处方式上下文，API 可用时发出 `scenario_greeting_requested` 交给后台 worker，API 不可用或失败时回退 `scenario_greeting_templates`。
4. 若未触发场景化问候，继续按 `proactive_content_ratio` 决定知识问候或普通问候；普通问候话术池从 `idle`/`quiet`/`encourage`/`break_reminder` 加当前时段分组中随机选取。
5. 本地问候触发后发出 `speak_requested(text, duration_ms, action_name)`；场景化 API 问候由 `ScenarioGreetingWorker` 成功后回到主线程显示。
6. `DesktopPetWindow._handle_behavior_speak()` / `_handle_scenario_greeting()` 在未聊天且输入框不可见时显示气泡并切动作。

自动移动和测试动作流：

- `ui.enable_free_move` 为 true 时，`auto_move_timer` 每 15 到 28 秒随机触发一次。
- 自动移动按左跑、右跑、跳跃约 4:4:2 的比例随机触发。
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

- 当前使用 `desktop_pet/tests/` 下的 `unittest` 回归测试，没有 pytest、CI、格式化器配置。
- 推荐使用项目本地虚拟环境运行：`desktop_pet\.desktop_pet_venv\Scripts\python.exe -m unittest discover -s desktop_pet\tests`。
- 记忆系统相关回归测试包括 `test_memory_schema.py`、`test_summarizer_memory_updates.py`、`test_prompt_builder_memory_sections.py` 和 `test_memory_vector_store.py`，分别覆盖 memory schema 兼容、关系记忆提取、Prompt 记忆分区与本地向量索引。场景化主动问候测试包括 `test_proactive_context.py`、`test_scenario_greeting_config.py`、`test_scenario_greeting_worker.py` 和 `test_behavior_controller.py` 中的场景化分流用例。
- 常用轻量校验方式还包括 Python AST 解析、JSON 合法性检查和手动启动。
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

- 影响所有配置和运行时数据。修改默认创建、解析失败、备份恢复、临时文件清理或保存行为时，要考虑用户旧数据、Windows 文件句柄、权限和崩溃中断场景。

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

快速启动脚本：

```powershell
cd desktop_pet
.\setup_env.bat
wscript.exe .\start_main.vbs
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

- `PySide6-Essentials`：提供运行所需的 `PySide6.QtCore`、`PySide6.QtGui`、`PySide6.QtWidgets`，用于桌面窗口、Qt 控件、定时器、信号、动画和图像显示；不要默认安装完整 `PySide6` / `PySide6_Addons`，避免引入未使用的 WebEngine、QML、Quick、Charts、3D 等大型 Qt 组件。
- `requests`：调用 DeepSeek API，以及独立 DashScope embedding 测试脚本。
- `mem0ai==2.0.2`：可选 Mem0 长期语义记忆层基础 SDK。代码必须使用可选导入和失败降级，不能假设一定安装或初始化成功；不要默认安装 `mem0ai[nlp]`、CLI、Server、OpenMemory、Docker、自托管服务或 spaCy 模型等额外扩展。

外部服务：

- DeepSeek API，默认 `base_url` 为 `https://api.deepseek.com`。
- 请求路径为 `/chat/completions`，请求体包含 `model`、`messages`、`temperature`。
- API key 从 `config/app_config.json` 或示例配置的 `api.api_key` 读取。示例配置默认空 key。
- DashScope / 阿里云百炼 OpenAI-compatible embeddings API，默认 base URL 为 `https://dashscope.aliyuncs.com/compatible-mode/v1`，Mem0 embedder 会调用 `/embeddings`，默认模型 `text-embedding-v4`、维度 1024。DashScope API key 从 `memory.dashscope_api_key` 或 `DASHSCOPE_API_KEY` 读取。

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
- 2026-05-11：聊天历史分裂为正式/非正式双轨。`ChatStore` 新增 `last_cleaned_at` 字段和 `update_last_cleaned_at()` 方法；`ContextManager` 改为接收两个 store 并按模式选择；`PromptBuilder` 改为接收两个 summary 路径按模式选择；`Summarizer.maybe_summarize()` 新增 `force` 参数；`DesktopPetWindow` 新增双 store/双 summary 实例、`_pending_was_formal` 快照防止路由错乱、`_active_chat_store()` 辅助方法。`app_config.example.json` 新增 `formal_cleanup_months`、`informal_cleanup_months`（已于 2026-05-11 后续移除）。
- 2026-05-11：新增清理聊天记录右键菜单。`app_config.example.json` 新增 `ui.show_clear_menu` 配置（默认 `false`）；`context_menu.py` 新增"清除非正式聊天记录""清理正式问答记录"两个菜单项；`DesktopPetWindow` 新增 `_clear_informal_chat_history()`、`_clear_formal_chat_history()` 方法。
- 2026-05-11：清理记录前先总结。`_clear_informal_chat_history()` 和 `_clear_formal_chat_history()` 在清空前先调用 `maybe_summarize(force=True)` 生成摘要，再清空消息并更新 `last_cleaned_at`。`app_config.example.json` 新增 `chat.force_summarize_before_clear` 配置（默认 `true`）控制是否强制总结。
- 2026-05-11：移除时间清理功能。删除 `DesktopPetWindow._check_time_based_cleanup()` 和 `_cleanup_timer`、`ChatStore.should_trigger_time_cleanup()` 和 `last_cleaned_at()`、`app_config.example.json` 中 `chat.formal_cleanup_months` 和 `chat.informal_cleanup_months` 配置项。原清理策略冗余（每小时检查 90/180 天阈值）、与摘要增量处理重叠。保留 `update_last_cleaned_at()` 供手动清空时标记。同步更新 `AGENTS.md`。
- 2026-05-11：主动问候频率动态调整。`BehaviorController` 新增 `_consecutive_unanswered` 计数器，根据连续未回应次数调整问候间隔（首次 15min → 第二次 15min → 第三次 30min → 第四次 30-60min 随机 → 最高 60min）。用户交互时 `notify_user_interaction()` 重置计数。`_maybe_idle_prompt()` 移除 `awaiting_user_reply` 硬阻断，改为依赖动态间隔。
- 2026-05-11：新增知识问候与内容比例系统。`BehaviorController` 新增 `knowledge_speak_requested` 信号、`_has_memory_content()` 检查记忆、`_proactive_ratio()` / `_adjust_ratio()` 管理问候类型比例。`_maybe_idle_prompt()` 按 `proactive_content_ratio` 随机选择普通问候或知识问候。`DesktopPetWindow` 新增 `KnowledgeSpeakWorker`（基于 memory.json 调用 API 生成内容）和 `_handle_knowledge_speak()` 处理展示及 `pick_reply_ack_line()` 回复确认。`mouseDoubleClickEvent` 在回复窗口内调用 `notify_proactive_response()` 调整比例。`local_lines.json` 新增 `reply` 分组（10 条简短应答话术）。`app_config.example.json` 新增 `proactive_content_ratio`（初始 1:1）。
- 2026-05-11：新增测试知识问候按钮。右键测试菜单增加"测试主动问候知识内容"，`DesktopPetWindow._test_knowledge_speak_once()` 直接调用 `_handle_knowledge_speak()` 触发记忆增强问候。`context_menu.py` 新增 `on_test_knowledge_speak` 回调参数。
- 2026-05-11：新增测试空闲问候逻辑按钮。`BehaviorController` 新增 `trigger_test_idle_prompt()` 绕过时间间隔限制直接调用 `_maybe_idle_prompt()`，保留免打扰/主动聊天/每日上限守卫，便于测试内容比例分流。右键测试菜单增加"测试空闲问候逻辑"，`DesktopPetWindow._test_idle_prompt_once()` 处理。`context_menu.py` 新增 `on_test_idle_prompt` 回调参数。
- 2026-05-11：知识问候右侧应答气泡改造。`speech_bubble.py` 新增 `ReplyBubble` 类：独立圆角矩形气泡，无尾巴、绿色配色、`PointingHandCursor`，位于角色右侧，点击时发出 `clicked` 信号。`_on_knowledge_speak_success()` 改用 `reply_bubble` 展示 `reply` 应答话术。`_handle_reply_bubble_clicked()` 调用 `notify_user_interaction()` 和 `notify_proactive_response()` 将用户回应计入问候间隔机制。`closeEvent`、`_toggle_always_on_top`、`_sync_floating_widgets` 同步适配。
- 2026-05-12：内容比例钳制 3:7。`_adjust_ratio()` 上界从 1.0 改为 0.7，下界从 0.0 改为 0.3，知识问候与普通问候比例始终在 3:7 到 7:3 之间。
- 2026-05-12：`trigger_test_idle_prompt()` 返回类型改为 str，返回当前比例和触发的问候类型（知识/普通/未触发）。`_test_idle_prompt_once()` 仅在未触发时显示结果气泡，避免覆盖已弹出的普通问候话术。
- 2026-05-12：知识问候提示词优化。`KnowledgeSpeakWorker.run()` 改为 `random.choice(preferences)` 随机选取一个偏好方向聚焦生成 3-4 句针对性内容，以「你知道吗」「说起来」等口语化开头。
- 2026-05-12：`_maybe_idle_prompt()` 每次成功触发问候后重置 `_consecutive_unanswered = 0`，使下一轮间隔回到 15 分钟。
- 2026-05-12：`ReplyBubble` 定位修复。`show_message()` 中 `show()` 提前到 `_reposition()` 之前，避免 `height()` 未就绪导致 y 坐标落入角色正中。新增公开 `reposition(anchor_rect)` 方法，`_sync_floating_widgets` 改用此方法传入最新锚点坐标。
- 2026-05-12：窗口置顶修复。`_toggle_always_on_top` 改为调用 `_reapply_window_flags()` 一次性重建所有 flags 并重新设置透明属性，`show()` 后调用 `raise_()` + `apply_transparent_window_fixes()` 恢复 Z-order。`_reload_config` 在 `_setup_window()` 后补充 `self.show()` + `raise_()` + `apply_transparent_window_fixes()`，修复重新加载配置后人物消失问题。
- 2026-05-13：单击人物打开聊天输入框后播放一遍 `waiting` 动作。`DesktopPetWindow._open_chat_input()` 在 `chat_input.show_near()` 后调用 `sprite_player.set_action("waiting", fallback_action="idle", force_single_cycle=True)`，动作结束后回到 `idle`，后续提交消息时仍由聊天流程切换到 `running` / `review` 等动作。
- 2026-05-13：启动问候不再计入本地主动话术次数。`BehaviorController._startup_greeting()` 移除成功展示前的 `usage_store.increment_local_line()`，保留免打扰、`startup_greeting` 开关和每日上限检查；空闲主动话术和时段变化问候仍按原逻辑计入 `local_proactive_lines_used`。
- 2026-05-13：主动问候回应后的内容比例微调幅度降低。`BehaviorController._adjust_ratio()` 改为回应类型 +0.005、互斥类型 -0.001，仍保持知识问候与普通问候比例在 0.3-0.7 范围内。
- 2026-05-13：摘要和记忆更新增加空聊天保护。`Summarizer.maybe_summarize()` 新增 `_has_summarizable_history()` 检查，只有存在非空用户消息时才继续生成摘要和合并 `memory_updates`；即使 `force=True`，空历史或仅有空内容/助手消息也会跳过，避免模型基于空 transcript 写入“用户不希望被总结或记录”等错误记忆。
- 2026-05-13：拆分快速启动与环境准备脚本。`desktop_pet/setup_env.bat` 负责查找或安装带 `pip` 的 Python（优先 Miniforge，避免无 pip 的 MSYS Python 被误选）、安装并校验 `PySide6-Essentials` 提供的 `PySide6` 模块和 `requests`，再把最终解释器路径写入 `data/runtime_python.txt`；`desktop_pet/start_main.vbs` 作为默认无终端启动入口，读取该路径隐藏运行 `main.py`，错误时打开终端显示 `data/start_main_error.log`，避免日常启动阶段隐式改动依赖环境。
- 2026-05-13：修复无终端启动读取 Python 路径失败。`setup_env.bat` 改为将 `runtime_python.txt` 写成无换行的纯路径；`start_main.vbs` 新增路径规范化，读取后移除回车、换行、制表符和 BOM，避免 `FileExists()` 因路径尾部换行误判 Python 不存在。
- 2026-05-13：增强快速启动脚本的新环境兼容性。`start_main.bat --console` 读取 `runtime_python.txt` 时也通过 PowerShell 清理 BOM、回车、换行、制表符和空格；`setup_env.bat` 在 `winget` 安装 Python 后若当前终端还找不到可用解释器，会提示重新运行脚本，仍失败再重开终端或重启系统。
- 2026-05-14：窗口置顶持久化修复。`utils/dwm_border.py` 新增 `force_window_topmost(hwnd, enabled)`，通过 `SetWindowPos(HWND_TOPMOST)` 在 Windows API 级别直接设置置顶样式。`DesktopPetWindow` 新增 `_topmost_enforcement_timer`（每 30 秒）和 `_enforce_topmost()` 方法，在 `showEvent` 中启动并在 `_toggle_always_on_top` 中管理启停，防止频繁 `setMask()` 导致 `WS_EX_TOPMOST` 被系统清除。同步更新 `AGENTS.md` 中 `desktop_pet_window.py` 描述和新增 `dwm_border.py` 章节。
- 2026-05-14：气泡智能定位与互斥避让。`speech_bubble.py` 新增模块级 `_find_bubble_position(bubble_width, bubble_height, anchor_rect, candidates, exclusion_rects)` 屏幕感知定位函数，支持额外避让区域。`SpeechBubble.reposition()` 和 `ReplyBubble._reposition()` 改用此函数，候选方位覆盖上/下/左/右。`DesktopPetWindow._sync_floating_widgets()` 在重定位时将对方可见气泡的 `geometry()` 作为 `exclusion_rects` 传入，使两个气泡互相避让不重叠。`_on_knowledge_speak_success()` 在两个气泡均显示后调用 `_sync_floating_widgets()` 触发互相避让。同步更新 `AGENTS.md` 中 `speech_bubble.py` 和 `desktop_pet_window.py` 描述。
- 2026-05-15：启动脚本增加代码更新步骤。`desktop_pet/start_main.vbs` 在启动 `main.py` 前切到仓库根目录执行 `git pull --ff-only`，将输出写入 `data/start_main_error.log`；若 Git 不可用、当前分支无上游、拉取冲突或网络失败，仅写入 warning 并继续启动，避免开机自启时因网络尚未连接而阻止桌宠运行。
- 2026-05-15：环境配置脚本改为项目本地虚拟环境策略。`setup_env.bat` 不再对全局/Miniforge base 环境执行项目依赖安装，而是创建 `desktop_pet/.desktop_pet_venv`，将依赖安装到本地虚拟环境，并把 `.desktop_pet_venv/Scripts/python.exe` 写入 `data/runtime_python.txt` 供 `start_main.vbs` 使用；为兼容当前机器的临时目录/代理问题，脚本会清理 pip 相关环境变量并使用项目内 `.pip_tmp`，但安装依赖时禁用 pip 缓存，并会清理旧版脚本遗留的 `.pip_cache`。
- 2026-05-15：`重新加载配置` 菜单项增加配置开关。`context_menu.py` 的 `build_context_menu()` 新增 `show_reload_config` 参数，`DesktopPetWindow._show_context_menu()` 从 `ui.show_reload_config` 读取并传入；`app_config.example.json` 新增同名配置项，默认 `true`，用于控制右键菜单中的“重新加载配置”按钮是否显示。
- 2026-05-15：时段问候新增“下午”分组。`BehaviorController._time_greeting_key()` 改为按 24 小时划分为 `7-11` 早晨、`11-14` 中午、`14-18` 下午、`18-22` 晚上、其余时间 `sleepy`；`local_lines.json` 新增 `greeting_afternoon` 本地问候话术，并同步更新 `AGENTS.md` 中 behavior_controller、local_lines 和主动行为流说明。
- 2026-05-18：修复模型记忆混入人物回答的问题。`Summarizer` 将“对话摘要”和“记忆提取”拆为两次独立流程：摘要继续基于最近完整对话生成，但模型 `memory_updates` 改为只喂用户发言单独提取，失败时退回仅看用户消息的本地规则提取；同时 `conversation_summary_*.json` 不再落盘 `memory_updates`。同步更新 `AGENTS.md` 中 `summarizer.py` 描述。
- 2026-05-19：新增可选 Mem0 长期语义记忆层。新增 `ai/mem0_memory_service.py` 封装 Mem0 初始化、写入、检索和 Prompt 格式化；新增 `tools/import_memory_json_to_mem0.py` 可将旧 `memory.json` 一次性导入 Mem0；`Summarizer` 在保留 `memory.json` 合并逻辑的同时旁路写入 Mem0；`ChatWorker` 可在后台线程中按当前用户输入检索 Mem0 记忆并传入 `PromptBuilder`；知识问候可通过 `memory.use_mem0_for_knowledge_speak` 优先使用 Mem0；`app_config.example.json` 新增 `memory.*` 配置项；`requirements.txt` 新增 `mem0ai`。Mem0 默认关闭，异常降级，不阻断桌宠主流程。
- 2026-05-19：将 Mem0 依赖固定为最小基础 SDK 版本 `mem0ai==2.0.2`，并在项目本地虚拟环境中安装该基础包；未安装 CLI、Server、OpenMemory、Docker、自托管服务、`mem0ai[nlp]`、spaCy 模型或其他 extras。同步更新 `AGENTS.md` 依赖说明。
- 2026-05-19：调整 Mem0 初始化为 `Memory.from_config(config)`，LLM provider 使用 Mem0 官方 DeepSeek provider，默认复用项目 `api.api_key`、`api.base_url`、`api.model`，并允许 `memory.mem0_deepseek_model` / `memory.mem0_deepseek_base_url` 覆盖；`app_config.example.json` 和本地 `app_config.json` 新增 `mem0_llm_provider`、`mem0_use_app_deepseek_config`、`mem0_deepseek_model`、`mem0_deepseek_base_url`、`mem0_temperature`、`mem0_max_tokens`、`mem0_top_p`、`mem0_embedder_provider`。embedding 未默认改为 DeepSeek，后续仍需按 Mem0 要求配置 OpenAI、Ollama 或其他 embedder。
- 2026-05-19：将普通问候与普通聊天回答的气泡停留时间改为配置项。`app_config.example.json` 和本地 `app_config.json` 新增 `ui.bubble_durations_ms`，包含 `startup_greeting`、`period_greeting`、`proactive_greeting`、`assistant_reply`；`BehaviorController` 改为按配置发出启动/时段/普通问候的气泡时长，`DesktopPetWindow._show_answer_output()` 改为按配置控制普通聊天回答气泡停留时间。同步更新 `AGENTS.md` 中 `behavior_controller.py` 与 `app_config.example.json` 描述。
- 2026-05-20：Mem0 embedder 接入 DashScope / 阿里云百炼 OpenAI-compatible embeddings。`mem0_memory_service.py` 构造 `Memory.from_config()` 时同时配置 DeepSeek LLM、DashScope embedding、1024 维本地 Qdrant 和项目内 `data/mem0_history.db`；`app_config.example.json` 和本地 `app_config.json` 新增 `dashscope_embedding_*` 与 key 来源配置；新增 `tools/test_dashscope_embedding.py`，并修正 `test.py` 不再使用字面量 `Bearer API_KEY` 或打印完整向量。Mem0 仍默认关闭，缺少 API key 或初始化失败时仅记录 warning 并降级。
- 2026-05-21：调整自主移动随机比例。`DesktopPetWindow._trigger_auto_move()` 改为按左跑、右跑、跳跃 4:4:2 抽取动作，并同步更新主动移动流程说明。
- 2026-05-22：新增 `local_lines.first_start` 启动问候配置。`local_lines.json` 新增 `{ "enable": false, "data": [...] }` 结构；`BehaviorController._startup_greeting()` 启动问候优先级调整为 `first_start.data`（仅当开启）→ 季节问候 → 时段问候 → `startup`；`first_start` 成功取用后会立即写回 `enable=false`，实现一次性首启问候；启动问候不再受每日主动话术上限拦截，只受免打扰和 `startup_greeting` 开关控制；同步更新启动问候流程说明。
- 2026-05-25：修复清理聊天记录前强制摘要时空记忆不落地的问题。`Summarizer._model_memory_updates()` 在模型返回合法但无任何非空记忆文本时，改为继续回退到本地规则提取；`maybe_summarize()` 只有在 `memory_updates` 含实际文本时才合并 `memory.json` 并旁路写入 Mem0，避免空结构导致 `memory.json.last_updated` 刷新但没有记忆内容、且 Mem0 无文本可写。新增 `desktop_pet/tests/test_summarizer_memory_updates.py` 覆盖空模型记忆回退本地提取并触发 Mem0 写入路径；同步更新 `AGENTS.md` 中 `summarizer.py` 描述。
- 2026-05-25：优化 Mem0 触发频率。`Summarizer` 改为首次达到 `summary_trigger_rounds` 后，需自上次摘要覆盖点以来再新增同等数量用户消息才再次摘要，避免 37 轮后每轮聊天都触发摘要和 Mem0 写入；`BehaviorController._maybe_idle_prompt()` 改为先按 `proactive_content_ratio.extra_knowledge` 抽签，命中后才检查 Mem0/本地记忆，并让 `behavior.min_proactive_interval_minutes` 成为动态问候间隔下限；`DesktopPetWindow._has_knowledge_memory()` 改为一次性检索并暂存知识问候所需 Mem0 上下文，`KnowledgeSpeakWorker` 复用该上下文，减少重复检索；`proactive_content_ratio` 默认/当前配置改为 `extra_knowledge=0.35`、`regular_greeting=0.65`；新增 `desktop_pet/tests/test_mem0_trigger_rules.py` 验证摘要节流和概率未命中时不查 Mem0。同步更新 `AGENTS.md` 中 summarizer、behavior_controller、app_config 配置说明。
- 2026-05-28：修复 Mem0、清理线程、退出等待和主动比例持久化相关流程。`Mem0MemoryService` 在启用但缺少 DashScope embedding key 时直接 info 降级，跳过 `mem0` 导入和 Qdrant/history 初始化；新增 `app/history_clear_worker.py`，将清理聊天记录前的强制摘要、清空和 `last_cleaned_at` 更新放到独立后台线程；`DesktopPetWindow.closeEvent()` 在聊天或清理线程仍运行时延迟真正关闭，等待后台线程收口后再退出；`BehaviorController` 新增 `config_saver` 回调以持久化 `proactive_content_ratio`，并对 `max_local_lines_per_day` 做安全整数解析。新增 `test_mem0_memory_service.py`、`test_behavior_controller.py`、`test_history_clear_worker.py` 回归测试，并同步更新相关模块、测试流程和风险说明。
- 2026-05-29：精简运行环境占用。`requirements.txt` 将 `PySide6` 替换为 `PySide6-Essentials`，当前项目虚拟环境卸载完整 `PySide6` / `PySide6_Addons` 后重装 Essentials，仅保留 `QtCore`、`QtGui`、`QtWidgets` 等实际使用模块；`setup_env.bat` 不再创建项目内 `.pip_cache`，安装依赖时设置 `PIP_NO_CACHE_DIR=1`，并在环境校验成功后清理旧版 `.pip_cache`。同步更新依赖说明和环境脚本缓存策略说明。
- 2026-05-30：整理 `AGENTS.md` 底部文档同步记录的展示顺序，改为自上而下按日期由先到后排列；本次仅调整文档记录顺序，不改变程序代码。
- 2026-05-30：精简 `start_main.vbs` 日常启动路径，移除启动前额外执行的 `python -c "import PySide6, requests"` 依赖 smoke check，避免重复启动 Python 并重复导入 PySide6；保留 `runtime_python.txt` 路径存在性检查，缺依赖时由 `main.py` 的真实启动失败路径写入日志并触发错误提示。新增 `test_start_main_script.py` 回归测试，并同步更新启动流程说明。
- 2026-05-30：修复正式问答记录清理时摘要更新但 `memory.json` 可能不更新的问题。`Summarizer._extract_memory()` 在正式问答模式下会把非空用户问题作为 `work_study.current_learning_topics` 的本地兜底记忆，避免模型记忆提取返回空结构时只有 `conversation_summary_formal.json` 更新、长期记忆没有任何新增文本可合并。新增正式问答清理场景回归测试，并同步更新 `summarizer.py` 说明。
- 2026-05-30：扩展 `work_study.current_learning_topics` 本地触发关键词，新增 `请问`、`怎么做`、`如何实现`、`如何`、`怎么`、`是什么`、`为什么`、`区别` 等问题式表达；同时修正 `Summarizer._summary_mode()` 先判 `informal` 再判 `formal`，避免非正式摘要文件名中的 `formal` 子串触发正式问答兜底逻辑。新增对应回归测试并同步更新 `summarizer.py` 说明。
- 2026-05-30：将 Mem0 初始化、重新加载配置时的 Mem0 重建、主动知识问候前的 Mem0 检索移出 Qt 主线程。新增 `Mem0InitializationWorker` 和 `Mem0SearchWorker`，分别在独立 `QThread` 中执行 `Mem0MemoryService` 构造/旧服务关闭和 `format_for_prompt()` 检索；`DesktopPetWindow` 通过完成信号替换服务引用并同步给两个摘要器，主动问候检索中返回 `None` 让 `BehaviorController` 跳过本轮普通问候兜底，检索成功后再触发知识问候。新增 `test_mem0_threading_boundaries.py` 防止 Mem0 初始化和主动问候检索回到主线程。
- 2026-05-30: Added local semantic vector indexing for `memory.json`. `MemoryStore` now best-effort syncs `data/memory_vectors.json` after saves/merges, using the existing DashScope embedding config. `DesktopPetWindow` starts a `MemorySemanticMergeWorker` after the window is shown; it runs in a separate `QThread`, checks the two-month cadence, and merges only same-field high-similarity duplicates so UI display and normal Q&A are not blocked.
- 2026-05-30：增强第一轮记忆系统。`MemoryStore` 新增 `normalize_memory_schema()`，兼容旧 `memory.json` 并补齐 `relationship_memory` 与 `memory_meta.schema_version=2`；`Summarizer` 的模型/本地记忆提取支持关系记忆，只基于用户发言记录沟通偏好、相处方式和近期互动模式；`PromptBuilder` 将本地事实记忆、相处方式记忆和 Mem0 相关语义记忆拆分为独立 Prompt 区块，并加入表达约束，避免机械复述记忆或暴露 memory.json/Mem0 等实现细节。新增 `test_memory_schema.py` 和 `test_prompt_builder_memory_sections.py`，扩展 `test_summarizer_memory_updates.py` 覆盖关系记忆提取与不使用助手回答推断用户偏好。
- 2026-05-30：增强第二轮场景化主动问候。新增 `character/proactive_context.py` 负责从 `memory.json` 构造精简场景上下文、本地模板回退和 API prompt；`BehaviorController._maybe_idle_prompt()` 在基础守卫后优先处理连续未回应的低打扰问候，其次在冷却结束且记忆足够时触发 `memory_context_greeting`，API 启用且额度可用时发出 `scenario_greeting_requested`，否则使用本地模板；`DesktopPetWindow` 新增 `ScenarioGreetingWorker`，在独立 `QThread` 中生成短问候，失败或输出机械记忆表达时静默回退本地模板。`app_config.example.json` 新增 `behavior.scenario_greeting_*` 配置，`local_lines.json` 新增 `scenario_greeting_templates` 和 `low_interrupt`，并新增对应回归测试。
- 2026-06-08：增强 `storage/json_store.py` 的 JSON 存储可靠性。`save_json()` 改为同目录 `.tmp` 原子写入，写入前为非空目标文件保留 `.bak`，完成 `flush` + `os.fsync` 后使用 `os.replace` 替换；`load_json()` 遇到主文件损坏时将其隔离为 `.corrupt.<timestamp>` 并优先从 `.bak` 恢复，备份也损坏时才回退默认值深拷贝；新增 `cleanup_tmp_json_files()` 清理遗留临时文件。新增 `test_json_store.py` 覆盖缺文件创建、正常读写、备份恢复、双损坏回退和失败写入不留下半截 JSON。
- 2026-06-08：优化日志系统长期运行稳定性和隐私安全。`utils/logger.py` 将 `app.log` 文件输出改为 `RotatingFileHandler`，限制单文件大小并保留有限备份；新增 `utils/log_sanitizer.py`，提供 API key 脱敏、常见密钥形态清理、长文本截断、异常摘要、messages 统计和响应结构摘要；`DeepSeekClient`、`Summarizer`、`Mem0MemoryService` 的错误日志改为记录状态码、消息数量、字符数、响应 keys 和截断异常，不再输出完整 payload、prompt、memory、模型回复或 API 响应。新增 `test_logging_privacy.py` 覆盖日志创建、轮转配置、API key 脱敏和超长文本截断。
- 2026-06-08：压缩 `data/memory_vectors.json` 体积。`MemoryVectorStore` 改为使用紧凑 JSON 保存向量索引，embedding 写入前按 `memory.memory_vector_precision` 做浮点精度压缩，跳过短于 `memory.memory_vector_min_text_length` 的文本，并通过 `memory.memory_vector_max_items` 限制索引条目数，超限时优先保留重要字段和较新条目；`embedding_signature` 纳入精度配置，模型、维度或精度变化时会重建索引。`app_config.example.json` 新增对应配置项，扩展 `test_memory_vector_store.py` 覆盖紧凑体积、默认配置、短文本跳过、旧签名重建和最大条目裁剪，语义去重逻辑保持不变。
- 2026-06-08：为 Prompt / Context / Summarizer 新增上下文预算控制。新增 `desktop_pet/ai/context_budget.py` 集中提供 `max_prompt_chars`、`max_history_messages`、`max_user_message_chars`、`max_history_message_chars`、`max_summary_chars`、`max_memory_chars`、`max_mem0_chars`、`summary_max_input_chars` 和 `memory_extract_max_input_chars` 的缺省值；`app_config.example.json` 的 `api` 节新增同名配置项。`PromptBuilder` 改为对用户输入、历史消息、摘要、普通记忆、关系记忆和 Mem0 检索结果分别做长度限制，并在全局 `max_prompt_chars` 下按“安全规则/角色设定/当前用户输入/最近对话/高价值记忆”的优先级裁剪；`ContextManager` 改为同时限制历史消息条数和单条长度；`Summarizer` 改为按字符预算从最近消息向前构建 summary / memory extraction transcript，并保证输入不超过配置预算。新增 `desktop_pet/tests/test_context_budget_controls.py`，重写 `test_prompt_builder_memory_sections.py`，并在 `test_summarizer_memory_updates.py` 中注入 `requests` stub，覆盖长历史 prompt 裁剪、超长用户输入限制、摘要输入预算和缺少新配置项时的默认回退。
