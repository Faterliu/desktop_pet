# 小桃 MP4 → 透明 WebM 工作流

适用于当前角色的 **720×960、24 fps、至少 1 秒的纯绿背景 MP4**（原脚本每秒抽样背景）。源文件保持原样，导出完整动作，不自动剪辑挥手或制作无缝循环。

## 用到的脚本

| 脚本 | 作用 |
| --- | --- |
| `run_trial.py` | 统一入口：生成角标遮罩、调用以下脚本、验证 Alpha 和帧数、生成预览 |
| `watermark_step01.py` | 填充角标区域，输出中间 MP4 |
| `fill_nn.py` | 上一步依赖的第 5 近邻背景取色算法 |
| `chroma_step02.py` | 绿幕抠像，输出 VP9 Alpha WebM |

日常只运行 `run_trial.py`。另外三个从本地 `dsh-pet/scripts` 复制，`chroma_step02.py` 在原算法上增加了可选无损编码；入口会覆盖它们的尺寸、路径和抠像参数，不要直接使用原脚本的横版默认值。

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
step02/                 <action>_refined.webm，正式透明视频
preview_refined/        棋盘格 MP4/GIF、深浅底对照图、透明抽样 PNG
report_refined.json     帧数、抠像参数和衣服区域透明度检查结果
```

已完成一次导出后，若只调整抠像参数，可在原命令末尾追加 `--reuse-cleaned`，复用**同一源视频、同一处理目录**的 `step01` 和报告。

## 检查与调参

- 先看 `preview_refined/<action>_checker.mp4` 和 `alpha_contact.png`，检查发梢、手臂、枫叶和衣服是否正常。预览带棋盘格，正式 WebM 才是真实透明背景。
- 入口使用修正后的 HSV 参数：`GREEN_HUE_MIN=96`、`GREEN_HUE_MAX=160`、`SAT_MIN=0.35`。不要恢复原脚本的宽松阈值，否则橄榄灰衣服可能出现透明空洞。
- 朝右行走原片的深色头发有偏绿阴影，使用 `--sat-min 0.5` 保护这些像素；默认仍为 `0.35`。更换阈值后要同时检查发丝边缘是否残留绿幕。
- 对透明轮廓要求较高时可加 `--lossless`，使用 VP9 无损编码，避免有损 Alpha 压缩让衣缘少量像素透明度下降；体积会增大，默认仍使用原 CRF 30。
- 入口强制用 `libvpx-vp9` 重新解码，核对帧数、透明背景，并逐帧检查衣服核心区域 `(300,510)–(420,615)`。检查报错时先看预览，不要直接接入程序。
- 当前角标遮罩只覆盖左上角和右下角。更换构图后，必须确认角标区域不碰到人物，且固定衣服检查区域仍位于衣料内部；其他尺寸或角色需要重新适配。
- 验收后手动将所需 WebM 放入 `desktop_pet/assets/videos/`，再登记素材配置。脚本不会自动替换程序素材或修改运行配置。

正式目录仅保留六个验收文件，统一使用 `idle.webm`、`thinking.webm`、`waving.webm`、`happy.webm`、`left-walking.webm`、`right-walking.webm`。新加工文件可使用 `_refined`、`_matched` 后缀，入库时按动作命名。程序内部的 `running`、`running_left`、`running_right` 等逻辑动作键保持兼容，通过素材配置映射到正式文件。

## 正式播放版压缩

六份无损母版由用户保存在项目外的 `C:\file\pet-image`，采用上述六个文件名。使用 `compress_webm.py` 统一导出 VP9 有损播放版：

```powershell
.\desktop_pet\.desktop_pet_venv\Scripts\python.exe -B .\scripts\compress_webm.py --source-dir C:\file\pet-image --output-dir .\desktop_pet\tmp_work\lossy_playback --crf 20
```

保持 720×960、24 fps、原帧数与动作剪辑、真实 Alpha 和无音轨；默认 CRF 20、`lossless=0`。脚本逐帧核对透明背景、实体内部透明度和可见区域压缩误差，生成 `compression_report.json` 及深浅底对比图。待机首尾按逻辑尺寸下的视觉一致性验收，有损编码不再要求首尾 RGBA 逐字节相同。

验收后将输出的六个 WebM 替换到 `desktop_pet/assets/videos/`，文件名不变，无需修改动作映射。项目内仅保留有损播放版；无损版本留在外部母版目录，制作步骤中的无损临时文件完成使用后应移出项目或清理。

本次历史加工、备份和重复 WebM，以及预览、帧缓存、角标遮罩、去角标中间 MP4 和临时依赖已清理；原始视频、正式素材、加工脚本与参数报告保留。下面的命令示例需要对应步骤先生成输入文件，历史备份路径仅作制作记录，不能直接复用已删除的中间文件。

## 待机循环修整（可选）

当前待机原片首尾不一致；`make_idle_loop.py` 保留 `[0,163)`，将尾部 8 帧（约 0.33 秒）平滑收回首帧，生成约 6.79 秒的循环版。它使用预乘 Alpha 混合和 VP9 无损编码，体积会比普通导出大；其他动作需重新选择剪辑点，不要直接套用默认值。

```powershell
.\desktop_pet\.desktop_pet_venv\Scripts\python.exe -B .\scripts\make_idle_loop.py --source .\desktop_pet\tmp_work\video_export\idle\step02\idle_refined.webm --output .\desktop_pet\tmp_work\idle_loop\idle_loop.webm
```

先执行上面的 `idle` 导出命令，生成 241 帧的 `step02/idle_refined.webm`；自定义处理目录时请相应替换路径。可用 `--end-frame`（不包含此帧）和 `--blend-frames` 调整截止点与尾部过渡长度。先检查多轮循环和透明度，再以 `idle.webm` 更新正式素材。

## 当前行走定稿的色彩修整（可选）

`refine_walking_colors.py` 不带 `--reference` 时，**只适配本次 720×960、24 fps、269 帧、站定保留 4 帧的右行回正版**。它以中段衣料色度校正首尾黄绿偏色，清理轮廓残绿，逐像素保留原 Alpha；可同时输出左行镜像。不要套用于其他剪辑时序，也不要对已修整版本重复处理。

以下为本次使用的加工命令记录；修整前的备份 WebM 已清理，执行前需换成重新生成、符合上述 269 帧时序的未修整原版。输出到独立目录，不自动覆盖正式素材：

```powershell
.\desktop_pet\.desktop_pet_venv\Scripts\python.exe -B .\scripts\refine_walking_colors.py --source .\desktop_pet\tmp_work\video_export\walking_right\color_fixed\before\running_right.webm --output .\desktop_pet\tmp_work\video_export\walking_right\color_reexport\running_right.webm --left-output .\desktop_pet\tmp_work\video_export\walking_right\color_reexport\running_left.webm
```

输出包含两个 WebM 和右行同名 JSON 加工记录。检查深浅背景、透明度、首尾一致性及与待机的衔接后，再更新 `desktop_pet/assets/videos/`。

独立生成的新版左行有整体偏黄时，追加 `--reference` 参照待机。该模式按当前角色裙装提取逐帧色度，以待机整段的中位色度为目标，平滑校正全片，保留亮度、枫叶高饱和橙色和原 Alpha，不使用旧右行的 269 帧曲线：

```powershell
.\desktop_pet\.desktop_pet_venv\Scripts\python.exe -B .\scripts\refine_walking_colors.py --source .\desktop_pet\tmp_work\video_export\walking_left_new\step02\running_left_clean.webm --reference .\desktop_pet\assets\videos\idle.webm --output .\desktop_pet\tmp_work\video_export\walking_left_new\color_reexport\running_left_matched.webm
```

此参考区域仅适用于当前角色和构图，不能直接用于其他角色；请始终从未匹配过的导出原版处理，避免重复校色。输出到独立目录，检查后再替换正式素材。

当前正面开心动作也可使用同一待机参考模式，先按上面的 `happy` 命令完成抠像，再执行：

```powershell
.\desktop_pet\.desktop_pet_venv\Scripts\python.exe -B .\scripts\refine_walking_colors.py --source .\desktop_pet\tmp_work\video_export\happy\step02\happy_refined.webm --reference .\desktop_pet\assets\videos\idle.webm --output .\desktop_pet\tmp_work\video_export\happy\step02\happy_matched.webm
```

文件名沿用 `refine_walking_colors.py`，有 `--reference` 时不要求行走的帧数或时序，但仍要求当前角色、720×960、24 fps，并须确认裙装采样区域未被手部或其他物体遮挡。该模式同时处理绿边，透明度与动作帧数保持不变。

来源：`dsh-pet` 的三个处理脚本，许可保留在 [DSH_PET_LICENSE.txt](DSH_PET_LICENSE.txt)；`run_trial.py` 是本项目这次实际处理三个动作使用的入口，复制后仅整理了本地调用路径、输入检查和默认输出位置。
