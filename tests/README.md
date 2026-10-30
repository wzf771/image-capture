# tests · 回归自检

这些是开发时用的回归脚本，**不是单元测试**：多数要读真实显微图。公开仓库里没有样本，
所以先把样本根目录告诉它们：

```bat
set IMAGECAPTURE_SAMPLES=D:\samples               :: 默认 E:\XY
set IMAGECAPTURE_SAMPLES_CZI_DIR=D:\samples\czi   :: CZI/LIF 样本，默认 E:\ImageCapture\789
set IMAGECAPTURE_CZI=D:\samples\one.czi           :: sharp_and_bar_check 用
```

样本目录的布局要与脚本里的相对路径对应（例如 `...\亚细胞定位部\4gegene\2\3164p.oib`），
对不上的脚本会自行跳过或提示缺文件。

## 怎么跑

```bat
cd tests
set QT_QPA_PLATFORM=offscreen
python smoke.py
python roi_check.py
python view_switch_check.py
python sharpness_baseline.py save    :: 第一次要先录基线
python sharpness_baseline.py check   :: 之后每次比对（±5%）
```

**顺序跑，不要并行**：脚本都会写 `output/_自检`，并行会互相覆盖。

## 脚本分组

| 组 | 脚本 |
|---|---|
| 主链路 | `smoke.py` `formats_check.py` `export_check.py` `raw_export_check.py` `export_dialog_check.py` |
| 标尺 | `bar_final_check.py` `bar_real_check.py` `bar_detect_check.py` `detect_overlay_check.py` `cand_pick_check.py` `sharpness_baseline.py` `sharp_and_bar_check.py` |
| 界面 | `channel_ui_check.py` `channel_role_check.py` `range_check.py` `lock_dot_check.py` `zoom_check.py` `zoom_thumb_check.py` `view_switch_check.py` |
| 数据/工程 | `project_check.py` `zt_check.py` `zproj_check.py` `process_check.py` `stitch_check.py` |
| 测量 | `roi_check.py` `roi_panel_check.py` `analysis_check.py` |
| 截图工具 | `gui_shot.py` `preview_bar.py` `bar_sharp.py`（不是断言，只出图） |

脚本头部注释写明了各自验什么、需要哪些样本。
