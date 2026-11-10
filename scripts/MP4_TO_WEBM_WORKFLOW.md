# 小桃 MP4 → 透明 WebM 工作流

适用于当前角色的 **720×960、24 fps、至少 1 秒的纯绿背景 MP4**（原脚本每秒抽样背景）。源文件保持原样，导出完整动作，不自动剪辑挥手或制作无缝循环。

## 新动作默认走完整流程

收到新的动作 MP4 后，默认一并完成转码、程序映射和测试菜单接入。交付前按以下顺序检查：

1. 去角标、抠绿幕，检查轮廓和衣料，按需要校正整体色偏。以程序内的待机视频为基准检查动作首尾的肤色，有明显差异时做局部校色。生成透明无损母版和通过逐帧验收的有损播放版。
2. 将母版和播放版分别归档到 `C:\file\pet-image\webm\lossless` 和 `compressed`，预览归档到 `previews`，保留对应的验收报告。
3. 将播放版复制到程序素材目录，登记 `video.clips` 和 `video.actions`。检查 `compressed` 中是否还有已验收但未登记的动作，一并补齐。
4. 在测试菜单加入新动作，并检查已登记动作是否都有测试入口。左右行走沿用专用移动测试。验证新动作可以播放完整一轮并回到待机；替换现有素材时复查原入口。

## 用到的脚本

| 脚本 | 作用 |
| --- | --- |
| `run_trial.py` | 统一入口：生成角标遮罩、调用以下脚本、验证 Alpha 和帧数、生成预览 |
| `watermark_step01.py` | 填充角标区域，输出中间 MP4 |
| `fill_nn.py` | 上一步依赖的第 5 近邻背景取色算法 |
| `chroma_step02.py` | 绿幕抠像，输出 VP9 Alpha WebM |
| `refine_walking_colors.py` | 按需以待机素材为参考校色，输出无损 WebM |
| `match_skin_colors.py` | 以待机为基准校正脸颊、手和腿的肤色，保留动作时序与母版 Alpha |
| `compress_webm.py` | 从无损 WebM 生成有损播放版，逐帧验证并输出报告 |

抠像统一通过 `run_trial.py` 执行。`watermark_step01.py`、`fill_nn.py` 和 `chroma_step02.py` 来自本地 `dsh-pet/scripts`。入口会设置尺寸、路径和抠像参数，适配当前竖版素材。

## 安装处理依赖

在项目根目录运行一次；这些是素材加工依赖，不需要加入程序运行依赖：

```powershell
cd C:\file\desktop_pet
.\desktop_pet\.desktop_pet_venv\Scripts\python.exe -m pip install numpy scipy opencv-python pillow imageio-ffmpeg==0.6.0
```

FFmpeg 由 `imageio-ffmpeg` 提供，不需要依赖 `C:\file\dsh-pet` 或系统 PATH 中的 FFmpeg。

## 导出

仍在项目根目录运行：

```powershell
.\desktop_pet\.desktop_pet_venv\Scripts\python.exe -B .\scripts\run_trial.py --source "C:\file\pet-image\待机动作.mp4" --action idle
.\desktop_pet\.desktop_pet_venv\Scripts\python.exe -B .\scripts\run_trial.py --source "C:\file\pet-image\挥手动作.mp4" --action waving
.\desktop_pet\.desktop_pet_venv\Scripts\python.exe -B .\scripts\run_trial.py --source "C:\file\pet-image\思考动作.mp4" --action running
.\desktop_pet\.desktop_pet_venv\Scripts\python.exe -B .\scripts\run_trial.py --source "C:\file\pet-image\左右行走 3.mp4" --action running_right --sat-min 0.5 --work-dir .\desktop_pet\tmp_work\video_export\walking_right
.\desktop_pet\.desktop_pet_venv\Scripts\python.exe -B .\scripts\run_trial.py --source "C:\file\pet-image\开心动作.mp4" --action happy --sat-min 0.5 --lossless --work-dir .\desktop_pet\tmp_work\video_export\happy
```

`running` 是项目沿用的“思考”动作键，`running_right` / `running_left` 表示朝右 / 朝左行走。默认输出到 `desktop_pet/tmp_work/video_export/<action>`；也可追加 `--work-dir "指定目录"`。不同源视频请使用不同处理目录，避免覆盖。

每个处理目录包含：

```text
video/                  逐帧角标遮罩
step01/                 角标填充后的 MP4
step02/                 <action>_refined.webm，抠像后的透明 WebM
preview_refined/        棋盘格 MP4/GIF、深浅底对照图、透明抽样 PNG
report_refined.json     帧数、抠像参数和衣服区域透明度检查结果
```

已完成一次导出后，若只调整抠像参数，可在原命令末尾追加 `--reuse-cleaned`，复用**同一源视频、同一处理目录**的 `step01` 和报告。

## 检查与调参

- 先看 `preview_refined/<action>_checker.mp4` 和 `alpha_contact.png`，检查发梢、手臂、枫叶和衣服是否正常。预览带棋盘格，正式 WebM 才是真实透明背景。
- 入口使用修正后的 HSV 参数：`GREEN_HUE_MIN=96`、`GREEN_HUE_MAX=160`、`SAT_MIN=0.35`。不要恢复原脚本的宽松阈值，否则橄榄灰衣服可能出现透明空洞。
- 朝右行走原片的深色头发有偏绿阴影，使用 `--sat-min 0.5` 保护这些像素；默认仍为 `0.35`。更换阈值后要同时检查发丝边缘是否残留绿幕。
- 不加 `--lossless` 时，抠像脚本以 CRF 30 输出有损版，可用于快速试导。正式素材按下节从无损母版生成。
- 入口强制用 `libvpx-vp9` 重新解码，核对帧数、透明背景，并逐帧检查衣服核心区域 `(300,510)–(420,615)`。检查报错时先看预览，不要直接接入程序。
- 当前角标遮罩覆盖四角，兼容角标位置变化。更换构图后，必须确认角标区域不碰到人物，且固定衣服检查区域仍位于衣料内部；其他尺寸或角色需要重新适配。

## 生成无损母版和有损播放版

项目里说的“非压缩版”指 VP9 无损编码的透明 WebM，作为后续剪辑、校色和压缩的母版。先在项目根目录以 `--lossless` 导出，例如从抱叶子原片生成母版：

```powershell
$python = '.\desktop_pet\.desktop_pet_venv\Scripts\python.exe'
$work = '.\desktop_pet\tmp_work\video_export\leaf-hug_export'
& $python -B .\scripts\run_trial.py --source 'C:\file\pet-image\抱叶子.mp4' --action leaf-hug --lossless --sat-min 0.5 --work-dir $work
```

每次加工使用独立处理目录。`--action` 从 `run_trial.py` 的 `choices` 中取值，全新动作名需先加入该列表。按预览确定 `--sat-min`，上例使用已验证的 `0.5`。有偏色时，先按文末 `refine_walking_colors.py --reference` 的方法校色，再以校色后的无损文件作为母版。需要剪辑或修整循环时也在这一步完成。

剪辑和整体校色完成后，用程序当前的待机首帧对照新动作首尾的脸颊、手背和小腿。如果有色差，且首尾都是同构图的正面站姿，可在独立目录生成肤色匹配后的母版。将 `--frames` 设为源片实际帧数：

```powershell
& $python -B .\scripts\match_skin_colors.py --source "$work\step02\leaf-hug_refined.webm" --reference .\desktop_pet\assets\videos\idle.webm --output "$work\skin_matched\leaf-hug.webm" --frames 241
```

已有整体校色定稿时，`--source` 指向该定稿。脚本按皮肤色度加权调整，首尾校色量在全片平滑过渡。若首尾姿势或构图改变，先检查采样框是否仍落在对应皮肤内部。验收时对照待机首帧和动作首尾，抽看抬手、侧身等中段姿势，检查衣袖、枫叶和透明轮廓，然后再压缩。

将验收后的母版以正式文件名备份到项目外，例如 `C:\file\pet-image\webm\lossless\leaf-hug.webm`。从母版目录单独生成播放版，`--files` 填文件名，可在素材登记前运行：

```powershell
& $python -B .\scripts\compress_webm.py --source-dir 'C:\file\pet-image\webm\lossless' --output-dir "$work\compressed" --crf 20 --files leaf-hug.webm
```

`compress_webm.py` 保留 720×960、24 fps、实际帧数、透明背景和原动作时序，输出无音轨的 VP9 有损版（`lossless=0`）。默认 CRF 20。查看 `compression_report.json` 中的 `clips[].frames`、透明度检查结果和深浅底对比图 `compression_comparison.png`。若透明度验收失败，可降低该动作的 CRF 单独重导，例如 `review.webm` 使用 CRF 18。待机还需检查连续循环的衔接。

素材根目录 `C:\file\pet-image` 的文件仅保留 MP4 原片。六份早期无损母版也统一归档到 `webm\lossless`，角色立绘和参考图位于 `webm\reference-images`。使用 `compress_webm.py` 指定文件名导出 VP9 有损播放版：

```powershell
.\desktop_pet\.desktop_pet_venv\Scripts\python.exe -B .\scripts\compress_webm.py --source-dir C:\file\pet-image\webm\lossless --output-dir .\desktop_pet\tmp_work\lossy_playback --crf 20 --files idle.webm thinking.webm waving.webm happy.webm left-walking.webm right-walking.webm
```

`deep-breath`、`failed`、`leaf-hug`、`review` 的成品备份位于 `C:\file\pet-image\webm\lossless` 和 `C:\file\pet-image\webm\compressed`，预览位于同级 `previews`。项目的正式资源目录仅保存验收通过的有损播放版，母版备份后可清理项目内的无损中间文件。

## 将 WebM 接入程序

1. 将压缩验收通过的 WebM 复制到 `desktop_pet/assets/videos/`，文件名使用 `leaf-hug.webm`、`deep-breath.webm` 这样的正式名称。
2. 在 `desktop_pet/assets/sprite_config.json` 的 `video.clips` 下登记素材键、相对程序根目录的 `file`、实际 `frames` 和 `fps`。例如 `deep-breath` 的条目为 `"deep-breath": {"file": "assets/videos/deep-breath.webm", "frames": 241, "fps": 24}`。帧数以压缩报告的实际解码结果为准。
3. 在同一文件的 `video.actions` 下登记「逻辑动作键 → 素材键」，例如 `"deep-breath": "deep-breath"`。已有业务键继续沿用，例如 `"running": "thinking"` 指向 `thinking.webm`。根级 `actions` 留给旧图集；仅提供 WebM 的动作登记在 `video` 下即可。
4. 新增的可选单次动作使用同名逻辑键和素材键，并加入 `desktop_pet/animation/video_player.py` 的 `OPTIONAL_SINGLE_ACTIONS`。该集合用于配置校验、单轮播放和旧配置回待机。需要循环的新动作需单独确认播放器规则。业务代码通过 `_set_pet_action()` 请求逻辑动作键，异步动作结束仍通过 `_finish_pet_action_if_owned()` 处理。

替换已有素材时，沿用原文件名和映射。如果重新剪辑改变了帧数，同步更新 `frames`，行走动作还需核对 `movement_frames`。登记后的文件须随程序交付，文件缺失或解码异常会触发整套图集回退。

## 加入测试动作列表

在 `desktop_pet/app/context_menu.py` 的 `test_actions` 动作名称列表中加入一项。第一项对应 `video.actions` 中的逻辑动作键，第二项是菜单显示名，优先沿用原片的中文动作名称。例如：

```python
("listen-nod", "测试动作：倾听点头"),
```

菜单沿用 `test_action_handler` 和 `_handle_test_action()`，对 `idle` 以外的动作请求单次播放，完成后回待机。这个入口只用于手动测试，业务触发按需要单独接入。

在本地 `desktop_pet/config/app_config.json` 的 `ui` 下将 `show_test_menu` 设为 `true`，重启程序后从 **右键 → 设置 → 测试** 选择动作。确认菜单能触发对应视频、背景透明、颜色与待机衔接自然，单次播放完成后回到待机。若出现旧图集，先核对文件路径、帧数和播放器日志。

提交前运行 `desktop_pet/tests/test_video_player.py` 和 `test_pet_context_menu.py` 对应的单元测试，覆盖真实解码、菜单回调、单次结束回待机和旧配置回退。

## 待机循环修整（可选）

当前待机原片首尾不一致；`make_idle_loop.py` 保留 `[0,163)`，将尾部 8 帧（约 0.33 秒）平滑收回首帧，生成约 6.79 秒的循环版。它使用预乘 Alpha 混合和 VP9 无损编码，体积会比普通导出大；其他动作需重新选择剪辑点，不要直接套用默认值。

```powershell
.\desktop_pet\.desktop_pet_venv\Scripts\python.exe -B .\scripts\make_idle_loop.py --source .\desktop_pet\tmp_work\video_export\idle\step02\idle_refined.webm --output .\desktop_pet\tmp_work\idle_loop\idle_loop.webm
```

先执行上面的 `idle` 导出命令并加上 `--lossless`，生成 241 帧的 `step02/idle_refined.webm`。自定义处理目录时请相应替换路径。可用 `--end-frame`（不包含此帧）和 `--blend-frames` 调整截止点与尾部过渡长度。检查多轮循环和透明度，通过压缩验收后再以 `idle.webm` 更新正式素材。

## 当前行走定稿的色彩修整（可选）

`refine_walking_colors.py` 不带 `--reference` 时，**只适配本次 720×960、24 fps、269 帧、站定保留 4 帧的右行回正版**。它以中段衣料色度校正首尾黄绿偏色，清理轮廓残绿，逐像素保留原 Alpha；可同时输出左行镜像。不要套用于其他剪辑时序，也不要对已修整版本重复处理。

以下为本次使用的加工命令记录；修整前的备份 WebM 已清理，执行前需换成重新生成、符合上述 269 帧时序的未修整原版。输出到独立目录，不自动覆盖正式素材：

```powershell
.\desktop_pet\.desktop_pet_venv\Scripts\python.exe -B .\scripts\refine_walking_colors.py --source .\desktop_pet\tmp_work\video_export\walking_right\color_fixed\before\running_right.webm --output .\desktop_pet\tmp_work\video_export\walking_right\color_reexport\running_right.webm --left-output .\desktop_pet\tmp_work\video_export\walking_right\color_reexport\running_left.webm
```

输出包含两个无损 WebM 和右行同名 JSON 加工记录。检查深浅背景、透明度、首尾一致性及与待机的衔接，压缩验收后再更新 `desktop_pet/assets/videos/`。

独立生成的新版左行有整体偏黄时，追加 `--reference` 参照待机。该模式按当前角色裙装提取逐帧色度，以待机整段的中位色度为目标，平滑校正全片，保留亮度、枫叶高饱和橙色和原 Alpha，不使用旧右行的 269 帧曲线：

```powershell
.\desktop_pet\.desktop_pet_venv\Scripts\python.exe -B .\scripts\refine_walking_colors.py --source .\desktop_pet\tmp_work\video_export\walking_left_new\step02\running_left_clean.webm --reference .\desktop_pet\assets\videos\idle.webm --output .\desktop_pet\tmp_work\video_export\walking_left_new\color_reexport\running_left_matched.webm
```

此参考区域仅适用于当前角色和构图。请始终从未匹配过的导出原版处理，避免重复校色。输出到独立目录，按上文流程压缩验收后再替换正式素材。

当前正面开心动作也可使用同一待机参考模式，先按上面的 `happy` 命令完成抠像，再执行：

```powershell
.\desktop_pet\.desktop_pet_venv\Scripts\python.exe -B .\scripts\refine_walking_colors.py --source .\desktop_pet\tmp_work\video_export\happy\step02\happy_refined.webm --reference .\desktop_pet\assets\videos\idle.webm --output .\desktop_pet\tmp_work\video_export\happy\step02\happy_matched.webm
```

文件名沿用 `refine_walking_colors.py`，有 `--reference` 时不要求行走的帧数或时序，但仍要求当前角色、720×960、24 fps，并须确认裙装采样区域未被手部或其他物体遮挡。该模式同时处理绿边，透明度与动作帧数保持不变。

来源：`dsh-pet` 的三个处理脚本，许可保留在 [DSH_PET_LICENSE.txt](DSH_PET_LICENSE.txt)；`run_trial.py` 是本项目这次实际处理三个动作使用的入口，复制后仅整理了本地调用路径、输入检查和默认输出位置。
