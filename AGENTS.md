# AGENTS.md

本指南适用于仓库根目录及其所有子目录。应用位于 `desktop_pet/`，素材处理脚本位于 `scripts/`。

## 1. 项目介绍

小桃是用 Python 和 PySide6 实现的 Windows 桌面 AI 宠物。它接收鼠标、聊天文本、剪贴板文本、截图和提醒设置，通过透明置顶窗口、角色动画、气泡和正式问答面板反馈。应用支持本地台词和远程模型，并在本地保存会话历史、摘要、记忆与提醒。

## 2. 维护要求

### 项目维护

- 读写源代码、配置和文档时显式指定 UTF-8。PowerShell 读取文本使用 `Get-Content -Encoding UTF8`。通过管道传入内联 Python 时用 Unicode 转义表示中文，或用 `apply_patch` 直接编辑文件。遇到乱码先核对源字节。
- 新增或修改的代码注释和文档字符串使用中文，标识符与外部接口术语保留原文。`.bat` 文件仅使用 ASCII，避免 `cmd.exe` 按 OEM 代码页误读。
- 优先修改现有文件。职责独立且确有需要时再新增文件。纯逻辑留在服务模块，控件创建和信号连接留在界面模块。
- 新增后台任务使用 `BackgroundTaskRegistry` 管理。耗时操作放到后台，结果通过信号回主线程更新界面。退出时限时回收任务和解码器，防止回调访问正在关闭的窗口。
- 角色动作统一经 `_set_pet_action()` 请求，异步完成经 `_finish_pet_action_if_owned()` 收尾。修改动作时验证移动结束、延迟交互和过期回调不会覆盖新动作。
- 修改配置项时同步更新代码与 `desktop_pet/config/app_config.example.json`。保留配置保存路径、存储结构和旧数据兼容性，维护原子写入及损坏文件恢复。
- 保持 `desktop_pet/config/app_config.json`、`desktop_pet/data/`、日志、缓存、虚拟环境和本地生成状态受 Git 忽略。提交内容不得含真实密钥。日志使用脱敏辅助函数，避免记录完整提示词、记忆、模型回复、图像和原始 API 请求或响应。
- 从 `desktop_pet/` 运行 `.\.desktop_pet_venv\Scripts\python.exe -B -m unittest discover -s tests`。Qt 测试统一使用 `desktop_pet/tests/qt_test_app.py` 的 `ensure_app()`，保证进程先创建 `QApplication`。仅检查语法时用 `compile()` 避免写入字节码。若默认临时目录无写权限，将测试临时目录指向 `desktop_pet/tmp_work/`。验证结束后回收本次启动的临时进程。

### 文档维护

- 仅在用户明确要求时修改根目录 `README.md`，含同名大小写变体。专项参数、教程和操作细节归入对应文档，本指南只维护长期约束、接口和代码入口。
- 收到新动作 MP4 时，按 [MP4 转透明 WebM 工作流](scripts/MP4_TO_WEBM_WORKFLOW.md) 默认完成转码验收、母版与播放版归档、程序映射和测试菜单接入，并补齐已验收但遗漏的动作。
- 项目职责或约定变化时直接更新对应章节，避免另设同步日志或变更记录。

## 3. 接口说明

| 接口 | 方向 | 作用 |
| --- | --- | --- |
| `QApplication.clipboard()`、`QScreen.grabWindow()` | 输入 | 读取系统剪贴板文本和屏幕像素，供辅助分析。 |
| `desktop_pet/config/app_config.json` | 双向 | 读取本机运行配置，保存设置变更。缺少本机配置时读取示例模板。 |
| 文本模型 `/chat/completions`、`/responses` | 双向 | 按所选供应商及协议发送文本上下文，接收回复或工具调用。 |
| 视觉模型 `/responses` | 双向 | 使用 `api.openai` 配置发送内存截图的 Data URL，接收文字分析。 |
| 提醒工具 `create_reminder` | 双向 | 校验模型给出的提醒参数并写入本地提醒，返回执行结果。 |
| `desktop_pet/data/` | 双向 | 持久化会话历史、摘要、记忆、提醒和运行状态。 |
| `desktop_pet/assets/sprite_config.json` | 输入 | 定义图集动作，以及视频素材、逻辑动作映射和行走位移区间。 |

配置为 KLD Responses 文本服务时，主备线路对可重试错误依次尝试，两者均不可用后可回退到已配置的 DeepSeek。视觉请求独立于文本供应商。截图只在内存中处理，`screenshot` 历史仅记录成功返回的文本。提醒优先使用原生工具调用，端点不支持时使用严格 JSON 协议。

## 4. 已有功能

环境与启动 → 交互采集与调度 → 回复与工具执行 → 界面与动画呈现 → 本地存储与后台维护。

### 4.1 环境与启动

| 文件 | 功能 |
| --- | --- |
| `desktop_pet/setup_env.bat`、`desktop_pet/requirements.txt` | 创建或复用 `.desktop_pet_venv`，安装 PySide6-Essentials、requests 和提供 FFmpeg 的 imageio-ffmpeg，并记录运行解释器。 |
| `desktop_pet/start_main.vbs` | 读取解释器记录，尝试 `git pull --ff-only`，随后隐藏终端启动程序。 |
| `desktop_pet/main.py` | 在导入 PySide6 和业务模块前写入启动诊断，初始化日志和 Qt 应用，显示桌宠窗口。 |
| `desktop_pet/app/config_service.py` | 以点分隔路径读取已加载的配置。 |

首次配置和日常启动见 [README 的运行说明](README.md)。静默启动失败时先查 `desktop_pet/data/start_main_error.log` 和 `desktop_pet/data/startup_bootstrap.log`，常规运行日志在 `desktop_pet/data/app.log`。

### 4.2 交互采集与调度

| 文件 | 功能 |
| --- | --- |
| `desktop_pet/app/desktop_pet_window.py` | 协调窗口、输入事件、聊天状态、后台任务、动作归属及退出。 |
| `desktop_pet/app/context_menu.py` | 构建右键卡片和子菜单，分派剪贴板、截图、提醒和动作测试入口。 |
| `desktop_pet/app/chat_input.py`、`desktop_pet/app/clipboard_service.py`、`desktop_pet/app/screenshot.py` | 采集聊天输入、读取剪贴板文本、获取全屏或冻结画面选区并提交视觉分析。 |
| `desktop_pet/character/behavior_controller.py`、`desktop_pet/character/proactive_context.py` | 调度启动、空闲、分时段与场景问候，构建场景上下文和本地兜底内容。 |
| `desktop_pet/app/background_task_registry.py` | 注册、去重并清理后台线程与工作对象。 |

### 4.3 回复与工具执行

| 文件 | 功能 |
| --- | --- |
| `desktop_pet/app/chat_flow_controller.py` | 决定本地或 API 回复分支，准备正式与闲聊模式快照及持久化决策。 |
| `desktop_pet/ai/prompt_builder.py`、`desktop_pet/ai/context_manager.py` | 组装角色设定和安全约束，按预算选取近期历史、摘要与记忆。 |
| `desktop_pet/ai/llm_client.py` | 选择模型线路与协议，解析文本、视觉和工具响应，处理超时和服务错误。 |
| `desktop_pet/app/reminder.py`、`desktop_pet/storage/reminder_store.py` | 接收手动或模型创建的提醒，保存提醒状态并调度到期反馈。 |

### 4.4 界面与动画呈现

| 文件 | 功能 |
| --- | --- |
| `desktop_pet/app/speech_bubble.py`、`desktop_pet/app/formal_answer_panel.py`、`desktop_pet/app/bubble_position_service.py` | 展示气泡和正式问答，并计算气泡位置。 |
| `desktop_pet/animation/video_player.py`、`desktop_pet/animation/sprite_player.py` | 播放透明 WebM 或旧图集，通过播放序号隔离过期视频事件。 |

视频校验或播放失败时，本次运行整体回退旧图集。视频行走根据 `frame_presented` 推进位移，裁剪或换片时须核对 `movement_frames` 与真实帧数。测试菜单受 `ui.show_test_menu` 控制，普通动作测试播完一轮回待机，左右行走走专用移动入口。

### 4.5 本地存储与后台维护

| 文件 | 功能 |
| --- | --- |
| `desktop_pet/storage/json_store.py`、`desktop_pet/storage/chat_store.py` | 管理 JSON 持久化和共享 JSONL 历史，按模式隔离读取和清理。 |
| `desktop_pet/app/conversation_maintenance_worker.py`、`desktop_pet/ai/summarizer.py` | 生成模式摘要，在摘要成功后清理对应历史快照。 |
| `desktop_pet/ai/memory_summarizer.py`、`desktop_pet/storage/memory_store.py` | 按每三份同模式摘要更新语义记忆，保存批处理进度。 |
| `desktop_pet/storage/local_lines_service.py` | 管理本地台词及按组配置的 API 刷新。 |

`formal`、`informal` 和 `clipboard` 参与摘要与记忆维护。`remind` 和 `screenshot` 保留独立模式，不进入该流程。
