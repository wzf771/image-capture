# -*- coding: utf-8 -*-
"""主界面。"""
from __future__ import annotations

import os
import math
import time
import traceback
import json

import numpy as np
from PySide6.QtCore import (QElapsedTimer, QEvent, QObject, QRect, QSize, Qt, QThread,
                            QTimer, Signal)
from PySide6.QtGui import (QColor, QCursor, QFont, QIcon, QKeySequence, QPainter,
                           QPixmap, QShortcut)
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QFrame, QHBoxLayout,
                               QDoubleSpinBox, QInputDialog, QLabel, QLineEdit,
                               QMainWindow, QMenu,
                               QMessageBox, QPushButton, QScrollArea, QSizePolicy,
                               QSlider, QSpinBox, QVBoxLayout, QWidget)

import paths
from core import bar as bar_mod
from core import analysis
from core import loader, render
from core import project as proj_mod
from core import raw as raw_mod
from core import roi as roi_mod
from core import stitch as stitch_mod
from core import zproj
from ui.roi_dialog import MeasureDialog, ResultDialog
from core.model import Group, ImageItem, ProcessStep, Settings
from core.model import CHANNEL_COLORS, color_name
from ui.canvas import CropCanvas
from ui import export_dialog
from ui.io_button import ImportButton
from ui.flow import FlowLayout
from ui import theme
from ui.widgets import (BrutalButton, FlipSwitch, IconSlideButton, LoaderBar,
                        RangeSlider, RingDot, SweepButton, ToggleSwitch)
from ui.worker import FnWorker, ThumbWorker, job_calibrate, job_export, job_probe

try:
    from version import VERSION as APP_VERSION
except Exception:                                # noqa: BLE001
    APP_VERSION = "dev"

ACCENT = "#7c5cff"

IMAGE_EXTS = (".png", ".tif", ".tiff", ".jpg", ".jpeg", ".bmp")


def is_image_file(path):
    """图片格式（没有内嵌标定，需要手动画线）：PNG / TIFF / JPG / BMP。"""
    return os.path.splitext(path or "")[1].lower() in IMAGE_EXTS


# ------------------------------------------------------------------ 小工具

class WheelScrollGuard(QObject):
    """侧栏里的控件不吃滚轮：滚轮一律拿来滚页面，避免误改参数。

    鼠标停在下拉框 / 数字框 / 滑条上滚轮时，原来会直接改那个参数；
    现在把这些滚轮事件截下来，转成页面的上下滚动。
    """

    def __init__(self, win, parent=None):
        super().__init__(parent)
        self._win = win

    def eventFilter(self, obj, ev):
        if ev.type() != QEvent.Wheel or not isinstance(obj, QWidget):
            return False
        area = obj
        while area is not None and not isinstance(area, QScrollArea):
            area = area.parentWidget()
        if area is None or area not in (self._win.left_holder, self._win.right_holder):
            return False                      # 中间的控件不归它管
        bar = area.verticalScrollBar()
        if bar.maximum() > 0:                 # 有得滚就滚页面
            step = ev.pixelDelta().y() or int(ev.angleDelta().y() / 120.0 * 60)
            bar.setValue(bar.value() - int(step))
        return True                           # 无论如何都别落到控件自己身上


# 卡片外壳与动画控件已拆到 ui/card.py（2026-09-22）
from ui.card import ClickLabel, CardFrame, SlideHolder, SlideAnim, card

class SquareBox(QWidget):
    """把里面的控件始终保持成正方形，并且完整显示（不裁切、不拉伸）。"""

    def __init__(self, inner, parent=None):
        super().__init__(parent)
        self.inner = inner
        inner.setParent(self)
        self.setMinimumSize(180, 180)

    def resizeEvent(self, _ev):
        side = max(64, min(self.width(), self.height()))
        self.inner.setGeometry((self.width() - side) // 2,
                               (self.height() - side) // 2, side, side)


def row(*widgets, spacing=8):
    lay = QHBoxLayout()
    lay.setSpacing(spacing)
    for w in widgets:
        if isinstance(w, str):
            lab = QLabel(w)
            lab.setObjectName("muted")
            lay.addWidget(lab)
        else:
            lay.addWidget(w)
    lay.addStretch(1)
    return lay


class GroupCard(QFrame):
    clicked = Signal(str)
    menu_requested = Signal(str, object)

    def __init__(self, group: Group):
        super().__init__()
        self.gid = group.gid
        self.setObjectName("groupCard")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(2)
        self.title = QLabel()
        self.title.setObjectName("groupTitle")
        self.meta = QLabel()
        self.meta.setObjectName("muted")
        lay.addWidget(self.title)
        lay.addWidget(self.meta)
        self._t = ""
        self._m = ""
        self.set(group)

    def set(self, group: Group):
        um = group.umpp()
        self._t = group.title
        self._m = "%s µm/px · %d 张" % (("%g" % round(um, 4)) if um else "未标定", group.count)
        self._elide()

    def _elide(self):
        w = max(40, self.width() - 24)
        self.title.setText(self.title.fontMetrics().elidedText(self._t, Qt.ElideRight, w))
        self.meta.setText(self.meta.fontMetrics().elidedText(self._m, Qt.ElideRight, w))

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._elide()
        self.title.setToolTip(self._t)
        self.meta.setToolTip(self._m)

    def set_active(self, on):
        self.setProperty("active", "true" if on else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, _ev):
        self.clicked.emit(self.gid)

    def contextMenuEvent(self, ev):
        self.menu_requested.emit(self.gid, ev.globalPos())


class ThumbButton(QFrame):
    clicked = Signal(str)
    menu_requested = Signal(str, object)

    def __init__(self, item: ImageItem):
        super().__init__()
        self.path = item.path
        self.setObjectName("thumb")
        self.setFixedWidth(92)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(5, 5, 5, 5)
        lay.setSpacing(3)
        self.pic = QLabel()
        self.pic.setFixedSize(80, 80)
        self.pic.setAlignment(Qt.AlignCenter)
        self.pic.setObjectName("thumbPic")
        # 多候选待确认的小橙点（规格书 5.4.5）：贴在缩略图右上角
        self.dot = QLabel(self.pic)
        self.dot.setFixedSize(11, 11)
        self.dot.setStyleSheet("background:#FF9500;border-radius:5px;"
                               "border:1px solid #ffffff;")
        self.dot.move(80 - 13, 2)
        self.dot.setVisible(False)
        self.dot.setToolTip("识别到多条候选标尺线，点开挑一条")
        self.name = QLabel(item.name)
        self.name.setObjectName("thumbName")
        self.name.setWordWrap(False)
        self.meta = QLabel()
        self.meta.setObjectName("muted")
        lay.addWidget(self.pic, 0, Qt.AlignHCenter)
        lay.addWidget(self.name)
        lay.addWidget(self.meta)
        self.name.setToolTip(item.name)
        self.set_meta(item)

    def set_meta(self, item: ImageItem):
        if getattr(item, "missing", False):
            self.meta.setText("原文件不存在")
            self.meta.setStyleSheet("color:#C0392B;")
        elif item.frames > 1:
            self.meta.setText("%d 帧" % item.frames)
            self.meta.setStyleSheet("")
        elif item.umpp > 0:
            self.meta.setText("%g µm/px" % round(item.umpp, 4))
            self.meta.setStyleSheet("")
        else:
            self.meta.setText("未标定")
            self.meta.setStyleSheet("")
        self.pic.setStyleSheet("opacity:0.45;" if getattr(item, "missing", False) else "")
        self.warn(bar_mod.ambiguous(getattr(item, "detect", None)))
        fm = self.name.fontMetrics()
        self.name.setText(fm.elidedText(item.name, Qt.ElideMiddle, 78))
        self.setToolTip("%s\n%s\n%s" % (item.name, item.calib, item.note))

    def warn(self, on):
        self.dot.setVisible(bool(on))

    def set_thumb(self, path):
        pm = QPixmap(path)
        if not pm.isNull():
            self.pic.setPixmap(pm.scaled(80, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def set_active(self, on):
        self.setProperty("active", "true" if on else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, _ev):
        self.clicked.emit(self.path)

    def contextMenuEvent(self, ev):
        self.menu_requested.emit(self.path, ev.globalPos())


# ------------------------------------------------------------------ 主窗口

class MainWindow(QMainWindow):

    # 启动时默认展开的右栏卡片（用户要求：只留通道与裁剪，其余折叠）。
    # 卡片标题见 ui/cards/*.py 里 card("…") 的第一个参数。
    CARDS_OPEN_BY_DEFAULT = ("裁剪视野", "通道与颜色")

    def __init__(self):
        super().__init__()
        paths.ensure_dirs()
        self.settings = Settings.load()
        self.items = []
        self.groups = []
        self.cur_group = None
        self.cur_item = None
        self.frame = 0
        self.view_mode = "full"                 # full / crop
        self._workers = []
        self._planes_key = None
        self._planes = None
        self._base_key = None
        self._base_planes = None
        self._base_rgb = None
        self._base_stale = False
        self._used_rect = None
        self._last_bar_anchor = None
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(110)
        self._preview_timer.timeout.connect(self.refresh_preview)
        self._thumb_timer = QTimer(self)
        self._thumb_timer.setSingleShot(True)
        self._thumb_timer.setInterval(1200)
        self._thumb_timer.timeout.connect(self._refresh_current_thumb)
        self._base_timer = QTimer(self)
        self._base_timer.setSingleShot(True)
        self._base_timer.setInterval(400)
        self._base_timer.timeout.connect(self._refresh_base_layer)
        self._thumb_worker = None
        self._thumbs = {}
        # —— 工程文件 / 撤销（P0-1）——
        self._proj_path = ""             # 当前工程文件；空 = 未命名
        self._dirty = False              # 有未保存改动
        self._restoring = False          # 正在套快照：别把恢复动作又记一次撤销
        self._undo = proj_mod.UndoStack()
        self._recent = []
        self._autosave_at = time.monotonic()
        self._shortcuts = []
        self._clip_channel = None        # 通道"复制/粘贴"用的应用内剪贴板
        self._frame_range_worker = None
        self.cur_t = 0                   # 当前时间点 / Z 层（P0-3）
        self.cur_z = 0
        self.setWindowTitle("Image capture %s · 显微图像统一视野裁剪" % APP_VERSION)
        self.setMinimumSize(720, 520)
        self.resize(1320, 880)
        self._build()
        # 恢复上次的左右栏展开状态
        for btn, on in ((self.btn_left, self.settings.ui_left),
                        (self.btn_right, self.settings.ui_right)):
            btn.blockSignals(True)
            btn.setChecked(on)
            btn.blockSignals(False)
        self.left_holder.setVisible(self.settings.ui_left)
        self.right_holder.setVisible(self.settings.ui_right)
        # 上次是不是"只看图"（不画裁剪框）
        self.btn_hide_box.blockSignals(True)
        self.btn_hide_box.setChecked(not bool(getattr(self.settings, "show_box", True)))
        self.btn_hide_box.blockSignals(False)
        self.canvas.set_show_box(bool(getattr(self.settings, "show_box", True)))
        self._style()
        self.refresh_groups()
        self.refresh_strip()
        self.refresh_manifest()
        # —— 工程文件：自动保存心跳 + 崩溃恢复检测 ——
        self._recent = self._load_recent()
        self._proj_timer = QTimer(self)
        self._proj_timer.setInterval(15000)          # 每 15 s 看一眼够不够 120 s 了
        self._proj_timer.timeout.connect(self._autosave_tick)
        if not self._no_save():
            self._proj_timer.start()
            QTimer.singleShot(400, self._check_autosave)
        self._bind_shortcuts()
        self._update_title()
        self._update_undo_buttons()

    # ------------------------------------------------------------ 界面搭建
    def _build(self):
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(11, 10, 11, 10)
        outer.setSpacing(9)

        # 顶栏
        top = QHBoxLayout()
        title = QLabel("Image capture")
        title.setObjectName("appTitle")
        sub = QLabel("v%s · 原生读 OIB / CZI / LIF · 也支持 TIFF / PNG / JPG / BMP" % APP_VERSION)
        sub.setObjectName("muted")
        top.addWidget(title)
        top.addWidget(sub)
        top.addStretch(1)
        # 工程 / 撤销：文件操作在前，视图开关在后（用户熟悉的工具栏顺序）
        self.btn_proj = BrutalButton("工程")
        self.btn_proj.setToolTip("新建 / 打开 / 保存工程（.icproj）· 最近打开 · 重新探测元数据")
        self.btn_proj.clicked.connect(self.project_menu)
        self.btn_undo = BrutalButton("撤销")
        self.btn_redo = BrutalButton("重做")
        self.btn_undo.clicked.connect(self.do_undo)
        self.btn_redo.clicked.connect(self.do_redo)
        for b in (self.btn_proj, self.btn_undo, self.btn_redo):
            top.addWidget(b)
        self.btn_left = BrutalButton("左栏")
        self.btn_right = BrutalButton("右栏")
        for btn, side in ((self.btn_left, "left"), (self.btn_right, "right")):
            btn.setCheckable(True)
            btn.setChecked(True)
            btn.setToolTip("点一下收起 / 展开这一栏，收起后中间显示区会变大")
            btn.toggled.connect(lambda on, s=side: self.toggle_side(s, on))
        top.addWidget(self.btn_left)
        top.addWidget(self.btn_right)
        self.btn_import = ImportButton("Get started")
        self.btn_import.setToolTip("导入文件夹（可含子目录）或单个/多个文件")
        self.btn_import.clicked.connect(self.import_menu)
        top.addWidget(self.btn_import)
        outer.addLayout(top)

        # 三栏：左 1 : 中 3 : 右 2
        mid = QHBoxLayout()
        mid.setSpacing(9)
        # 左右固定宽度，中间吃掉全部剩余空间（图片区最大）
        self.left_holder = self._side_scroll(self._build_left(), 232)
        self.right_holder = self._side_scroll(self._build_right(), 348)
        mid.addWidget(self.left_holder, 0)
        mid.addWidget(self._build_center(), 1)
        mid.addWidget(self.right_holder, 0)
        outer.addLayout(mid, 1)

        # 底栏（通栏白条）
        foot = QFrame()
        foot.setObjectName("card")
        bottom = QHBoxLayout(foot)
        bottom.setContentsMargins(14, 9, 14, 9)
        bottom.setSpacing(10)
        self.manifest = QLabel("还没有导入图片")
        self.manifest.setObjectName("muted")
        self.manifest.setWordWrap(False)
        self.progress = LoaderBar()          # 导出进度：蓝色斜条纹
        self.lbl_status = QLabel("就绪 · v%s" % APP_VERSION)
        self.lbl_status.setObjectName("muted")
        self.btn_export = IconSlideButton("Download")
        self.btn_export.setToolTip("先勾要导出的图片，再勾导出内容，然后开始导出")
        self.btn_export.clicked.connect(self.export_menu)
        bottom.addWidget(self.manifest, 1)
        bottom.addWidget(self.progress, 1)
        bottom.addWidget(self.lbl_status)
        bottom.addWidget(self.btn_export)
        outer.addWidget(foot)
        self._sync_pills()          # 右栏胶囊的文字跟真实参数对齐
        self._wheel_guard = WheelScrollGuard(self)
        QApplication.instance().installEventFilter(self._wheel_guard)

    def _build_left(self):
        rail = QFrame()
        rail.setObjectName("rail")
        lay = QVBoxLayout(rail)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(9)

        brand = QHBoxLayout()
        brand.setSpacing(9)
        mark = QLabel()
        mark.setFixedSize(28, 28)
        mark.setStyleSheet(
            "border-radius:9px;background:qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            "stop:0 %s,stop:0.6 #8E7BFF,stop:1 %s);" % (theme.PRIMARY, theme.MINT))
        bt = QVBoxLayout()
        bt.setSpacing(1)
        b1 = QLabel("Image capture")
        b1.setStyleSheet("font-weight:700;font-size:12.5px;color:#fff;")
        b2 = QLabel("统一视野裁剪")
        b2.setObjectName("railSub")
        bt.addWidget(b1)
        bt.addWidget(b2)
        brand.addWidget(mark)
        brand.addLayout(bt)
        brand.addStretch(1)
        lay.addLayout(brand)

        cap = QLabel("分组")
        cap.setObjectName("railCap")
        lay.addWidget(cap)

        self.group_host = QWidget()
        self.group_host.setObjectName("groupHost")
        self.group_host.setAutoFillBackground(False)
        self.group_layout = QVBoxLayout(self.group_host)
        self.group_layout.setContentsMargins(0, 0, 0, 0)
        self.group_layout.setSpacing(6)
        self.group_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.group_host)
        scroll.setFrameShape(QFrame.NoFrame)
        gvp = scroll.viewport()
        gvp.setObjectName("groupVp")
        gvp.setAutoFillBackground(False)
        scroll.setStyleSheet("#groupVp, #groupHost { background: transparent; }")
        scroll.setMinimumHeight(120)
        lay.addWidget(scroll, 1)

        rowb = QHBoxLayout()
        rowb.setSpacing(6)
        b_new = SweepButton("新建组")
        b_new.clicked.connect(self.new_group)
        b_clear = SweepButton("清空")
        b_clear.setToolTip("把列表里的图片全部移出（不动原文件）")
        b_clear.clicked.connect(self.clear_all)
        rowb.addWidget(b_new)
        rowb.addWidget(b_clear)
        lay.addLayout(rowb)

        rc = QFrame()
        rc.setObjectName("railCard")
        rl = QVBoxLayout(rc)
        rl.setContentsMargins(11, 10, 11, 10)
        rl.setSpacing(7)
        t = QLabel("标定")
        t.setStyleSheet("font-weight:700;font-size:12px;color:#fff;")
        rl.addWidget(t)
        self.lbl_src = QLabel("文件自带 0 · 标尺识别 0 · 手动 0")
        self.lbl_src.setObjectName("railSub")
        self.lbl_src.setWordWrap(True)
        rl.addWidget(self.lbl_src)
        self.btn_calib = SweepButton("自动识别标尺")
        self.btn_calib.setToolTip("对所有还没有标定的图做一次标尺识别 + 认字")
        self.btn_calib.clicked.connect(self.auto_calibrate)
        rl.addWidget(self.btn_calib)
        drop = QLabel("把文件夹、OIB / CZI / LIF\n拖到这里导入")
        drop.setObjectName("railSub")
        drop.setWordWrap(True)
        drop.setAlignment(Qt.AlignCenter)
        drop.setMinimumHeight(46)
        drop.setStyleSheet("border:1px dashed rgba(255,255,255,0.25);border-radius:12px;"
                           "color:rgba(255,255,255,0.6);padding:8px;")
        rl.addWidget(drop)
        lay.addWidget(rc, 0)
        self.setAcceptDrops(True)
        return rail

    def _build_center(self):
        col = QWidget()
        lay = QVBoxLayout(col)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(9)

        # 头部：组信息 + 视图切换
        head = QHBoxLayout()
        head.setSpacing(8)
        self.lbl_group_head = QLabel("还没有导入图片")
        self.lbl_group_head.setStyleSheet("font-weight:700;font-size:13.5px;")
        self.lbl_group_info = QLabel("")
        self.lbl_group_info.setObjectName("muted")
        head.addWidget(self.lbl_group_head)
        head.addWidget(self.lbl_group_info)
        head.addStretch(1)
        self.btn_view_full = BrutalButton("原图显示")
        self.btn_view_full.setToolTip("显示整张原图；滚轮缩放、拖动平移、双击回到整图")
        self.btn_view_crop = BrutalButton("裁剪结果")
        for b, mode in ((self.btn_view_full, "full"), (self.btn_view_crop, "crop")):
            b.setCheckable(True)
            b.clicked.connect(lambda _c=False, m=mode: self.set_view_mode(m))
            head.addWidget(b)
        self.btn_view_full.setChecked(True)
        # 只看图（2026-09-26 用户要求）：不画裁剪框、也不压暗四周，
        # 方便整体观察和往图上加 ROI。勾上 = 隐藏框。
        self.btn_hide_box = BrutalButton("隐藏裁剪框")
        self.btn_hide_box.setCheckable(True)
        self.btn_hide_box.setToolTip(
            "只看图：不画裁剪框、四周也不压暗，方便观察图像和加 ROI\n"
            "（再点一下恢复裁剪框；裁剪结果视图里这个按钮不生效）")
        self.btn_hide_box.toggled.connect(self.on_hide_box)
        head.addWidget(self.btn_hide_box)
        lay.addLayout(head)

        # 画布
        self.canvas = CropCanvas()
        self.canvas.box_changed.connect(self.on_box_changed)
        self.canvas.box_committed.connect(self.on_box_committed)
        self.canvas.box_drag_started.connect(self.on_box_drag_started)
        self.canvas.roi_done.connect(self.on_roi_done)
        self.canvas.roi_selected.connect(self.on_roi_selected)
        self.canvas.roi_edited.connect(self.on_roi_edited)
        self.canvas.roi_drag_started.connect(self.on_roi_drag_started)
        self.canvas.roi_delete.connect(self.roi_delete_by_rid)
        self.canvas.roi_menu.connect(self.roi_menu)
        self.canvas.roi_mode_changed.connect(self.on_roi_mode_changed)
        self.canvas.bar_dragged.connect(self.on_bar_dragged)
        self.canvas.bar_drag_done.connect(self.on_bar_drag_done)
        self.canvas.line_done.connect(self.on_line_measured)
        self.canvas.view_changed.connect(self._schedule_preview)
        self.canvas_square = SquareBox(self.canvas)
        box = QFrame()
        box.setObjectName("stage")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(9, 9, 9, 9)
        bl.addWidget(self.canvas_square, 1)
        lay.addWidget(box, 1)

        # 信息胶囊行（自动换行，不会顶出边框）
        chip_card = QFrame()
        chip_card.setObjectName("card")
        cl = QVBoxLayout(chip_card)
        cl.setContentsMargins(11, 9, 11, 9)
        cl.setSpacing(6)
        chips = QWidget()
        chips.setLayout(FlowLayout(chips, spacing=6))
        self.chip_layout = chips.layout()
        self.lbl_px = QLabel("")
        self.lbl_px.setObjectName("chip")
        self.lbl_size = QLabel("—")
        self.lbl_size.setObjectName("chip")
        self.chk_sync = ToggleSwitch()
        self.chk_sync.setToolTip("组内裁剪框位置一致")
        self.chk_sync.setChecked(self.settings.__dict__.get("group_sync", True))
        self.chk_sync.toggled.connect(self.on_sync_toggled)
        hint = QLabel("滚轮缩放 · 拖动平移 · 双击复位")
        hint.setObjectName("chip")
        self.chip_layout.addWidget(self.lbl_px)
        self.chip_layout.addWidget(self.lbl_size)
        self.chip_layout.addWidget(hint)
        cl.addWidget(chips)
        opts = QHBoxLayout()
        opts.setSpacing(8)
        opts.addWidget(self.chk_sync)
        lab_sync = ClickLabel("组内裁剪框位置一致")
        lab_sync.setCursor(Qt.PointingHandCursor)
        lab_sync.setToolTip("点这里也能开关")
        lab_sync.clicked.connect(self.chk_sync.toggle)
        opts.addWidget(lab_sync)
        opts.addStretch(1)
        cl.addLayout(opts)

        # Z 层 / 时间点：两行各自一条滑条（P0-3，只有多帧文件才显示）
        self.frames_row = QWidget()
        fv = QVBoxLayout(self.frames_row)
        fv.setContentsMargins(0, 0, 0, 0)
        fv.setSpacing(4)
        # Z 行
        zr = QHBoxLayout()
        zr.setSpacing(8)
        self.cap_z = QLabel("Z 层")
        self.cap_z.setObjectName("muted")
        self.z_slider = QSlider(Qt.Horizontal)
        self.z_slider.setRange(1, 1)
        self.z_slider.valueChanged.connect(self.on_z_changed)
        self.lbl_z = QLabel("")
        self.lbl_z.setObjectName("chip")
        self.z_row = QWidget()
        zr.addWidget(self.cap_z)
        zr.addWidget(self.z_slider, 1)
        zr.addWidget(self.lbl_z)
        self.z_row.setLayout(zr)
        fv.addWidget(self.z_row)
        # T 行
        fr = QHBoxLayout()
        fr.setSpacing(8)
        self.cap_t = QLabel("时间")
        self.cap_t.setObjectName("muted")
        self.frame_slider = QSlider(Qt.Horizontal)      # 保留老名字：外部还有引用
        self.frame_slider.setRange(1, 1)
        self.frame_slider.valueChanged.connect(self.on_frame_changed)
        self.lbl_frame = QLabel("第 1 点 / 共 1 点")
        self.lbl_frame.setObjectName("chip")
        self.t_row = QWidget()
        fr.addWidget(self.cap_t)
        fr.addWidget(self.frame_slider, 1)
        fr.addWidget(self.lbl_frame)
        self.t_row.setLayout(fr)
        fv.addWidget(self.t_row)
        # 元数据说不清"多帧到底是 Z 还是时间"时，让用户自己声明（3.18.3）
        self.btn_declare = BrutalButton("多帧 = 时间序列", compact=True)
        self.btn_declare.setToolTip("相机拍的 Z 序列 TIFF 没有维度信息：点一下换成「Z 栈」")
        self.btn_declare.clicked.connect(self.toggle_declare)
        self.btn_declare.setVisible(False)
        fv.addWidget(self.btn_declare)
        cl.addWidget(self.frames_row)
        self.frames_card = self.frames_row
        lay.addWidget(chip_card)

        # 组内图片
        c = card("组内图片", "点选 · 右键菜单", module=True)
        c.on_settled = self.after_slide        # 滑完再补预览刷新，别卡在收尾
        self.strip_host = QWidget()
        self.strip_host.setObjectName("stripHost")
        self.strip_host.setAutoFillBackground(False)
        self.strip_layout = QHBoxLayout(self.strip_host)
        self.strip_layout.setContentsMargins(0, 0, 0, 0)
        self.strip_layout.setSpacing(8)
        self.strip_layout.addStretch(1)
        s = QScrollArea()
        s.setWidgetResizable(True)
        s.setWidget(self.strip_host)
        s.setFrameShape(QFrame.NoFrame)
        s.setFixedHeight(118)
        s.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        svp = s.viewport()
        svp.setObjectName("stripVp")
        svp.setAutoFillBackground(False)
        s.setStyleSheet("#stripVp, #stripHost { background: transparent; }")
        c.body.addWidget(s)
        lay.addWidget(c)
        self.frames_card.hide()
        return col

    @staticmethod
    def _switch_row(widget, text):
        """一行：flipswitch + 文字说明。"""
        h = QHBoxLayout()
        h.setSpacing(10)
        h.addWidget(widget)
        lab = QLabel(text)
        h.addWidget(lab, 1)
        return h
    def _build_right(self):
        """右栏五张卡片：实现在 ui/cards/ 里，这里只负责按顺序摆好。"""
        from ui.cards import calib as calib_card
        from ui.cards import channel as channel_card
        from ui.cards import crop as crop_card
        from ui.cards import process as process_card
        from ui.cards import roi as roi_card
        from ui.cards import ruler as ruler_card
        from ui.cards import zproj as zproj_card

        col = QWidget()
        lay = QVBoxLayout(col)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        cards = []
        for mod in (crop_card, ruler_card, zproj_card, process_card, roi_card,
                    channel_card, calib_card):
            c = mod.build(self)
            cards.append(c)
            lay.addWidget(c)
        lay.addStretch(1)
        # 默认排布（用户要求）：只展开「裁剪视野」与「通道与颜色」，其余折叠 ——
        # 右栏一屏放得下，不用一直滚；点标题行随时展开，展开状态不会被改写。
        for c in cards:
            c.set_open(getattr(c, "title", "") in self.CARDS_OPEN_BY_DEFAULT)
        # 「导出内容」卡片已按用户要求整块移除（2026-09-23），那批控件搬进
        # ui/export_dialog.py 的导出弹窗里；**属性名不变**（win.chk_merge 等），
        # 所以 _sync_settings() / _sync_pills() / pick_outdir() 一个字都不用改。
        # 这里必须在 _build() 结束前建好，否则后面 _sync_pills() 会读不到那些控件。
        self.exp_dialog = export_dialog.ExportDialog(self)
        return col

    def _side_scroll(self, widget, width):
        """把左右两栏各自放进可滚动的容器：屏幕小的时候栏内滚动，不会把窗口撑大。"""
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # 竖直滚动条常驻：否则收起卡片时滚动条消失→视口变宽→卡片重新换行→高度又变，
        # 会来回抖（这就是"收尾抖动"的来源）
        area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        area.setFixedWidth(width)            # 左右两栏固定宽度，中间吃掉剩余空间
        vp = area.viewport()
        vp.setObjectName("scrollVp")
        vp.setAutoFillBackground(False)
        area.setStyleSheet("#scrollVp { background: transparent; }")
        area.setWidget(widget)
        return area

    def toggle_side(self, side, on):
        holder = self.left_holder if side == "left" else self.right_holder
        holder.setVisible(on)
        self.canvas.update()
        if side == "left":
            self.settings.ui_left = on
        else:
            self.settings.ui_right = on
        self._sync_settings()
        self.refresh_manifest()

    def showEvent(self, ev):
        super().showEvent(ev)
        if getattr(self, "_sized", False):
            return
        self._sized = True
        scr = self.screen() or QApplication.primaryScreen()
        if scr is None:
            return
        g = scr.availableGeometry()
        w = min(1460, max(880, g.width() - 90))
        h = min(960, max(600, g.height() - 90))
        self.resize(w, h)
        self.move(g.x() + max(0, (g.width() - w) // 2),
                  g.y() + max(0, (g.height() - h) // 2))
        QTimer.singleShot(60, self._settle_cards)      # 首帧过完让卡片重新量一次高度

    def _settle_cards(self):
        """卡片里的内容首帧还没量准高度，重新报一次，
        不然模块会被压掉几个像素（展开后比初始高一点，看着像跳）。"""
        for holder in self.findChildren(SlideHolder):
            holder.updateGeometry()

    def _style(self):
        self.setStyleSheet(theme.qss())

    # ------------------------------------------------------------ 参数
    def _sync_settings(self):
        st = self.settings
        st.crop_w = self.f_w.value()
        st.crop_h = self.f_h.value()
        st.lock_1to1 = self.chk_lock.isChecked()
        st.too_small = ["pad", "skip", "shrink"][self.cb_tosmall.currentIndex()]
        st.bar_enabled = True                            # 标尺常开
        st.bar_length = self.field_len.value()          # 留空 = 0 = 自动
        st.bar_position = ["br", "bl", "tr", "tl", "custom"][self.cb_pos.currentIndex()]
        idx = self.cb_color.currentIndex()
        st.bar_color = ["auto", "white", "black", self._custom_color][idx]
        st.bar_thickness = int(self.field_thick.value())     # 留空 = 0 = 自动
        st.bar_ticks = ["ends6", "ends", "none"][self.cb_ticks.currentIndex()]
        st.bar_text = self.chk_text.isChecked()
        st.bar_show_unit = self.chk_unit.isChecked()
        st.bar_font = self.cb_font.currentText()
        st.bar_font_size = int(self.field_size.value())     # 留空 = 0 = 自动
        st.bar_margin = int(self.field_margin.value())       # 留空 = 0 = 自动
        st.export_zoom = [1, 2, 4][self.cb_zoom.currentIndex()]
        st.bar_extra_png = self.chk_bar_png.isChecked()
        st.exp_merge = self.chk_merge.isChecked()
        st.exp_ch = [c.isChecked() for c in self.chk_ch]
        st.merge_mode = "max" if self.cb_merge_mode.currentIndex() == 1 else "add"
        st.out_format = ["follow", "png", "tiff", "jpg"][self.cb_format.currentIndex()]
        st.out_suffix = self.ed_suffix.text() or "_crop"
        st.exp_raw_single = self.chk_raw.isChecked()
        st.exp_raw_stack = self.chk_raw_stack.isChecked()
        st.exp_raw_ome = self.chk_raw_ome.isChecked()
        st.exp_raw_embed = self.chk_raw_embed.isChecked()
        st.exp_proj = self.chk_proj.isChecked()
        st.frames_mode = ["current", "all", "pick"][self.cb_frames.currentIndex()]
        st.frame_pick = self.ed_pick.text()
        st.z_mode = ["current", "all", "pick"][self.cb_zmode.currentIndex()]
        st.z_pick = self.ed_zpick.text()
        st.out_dir = self.ed_outdir.text()
        st.group_sync = self.chk_sync.isChecked()
        st.ui_left = self.btn_left.isChecked()
        st.ui_right = self.btn_right.isChecked()
        st.show_box = not self.btn_hide_box.isChecked()
        return st

    def on_any_setting(self, *_args):
        self._sync_settings()
        self._mark_dirty()               # 参数变了也要自动保存（不进撤销栈）
        self.refresh_manifest()
        self._sync_pills()
        if self.view_mode == "crop":
            self.refresh_preview()

    def on_crop_changed(self, *_args):
        self._commit("改裁剪视野尺寸", coalesce=1.2)   # 连点/连续改只记一次
        if self.chk_lock.isChecked():
            sender = self.sender()
            target = self.f_h if sender is self.f_w else self.f_w
            source = self.f_w if sender is self.f_w else self.f_h
            if abs(target.value() - source.value()) > 1e-6:
                target.blockSignals(True)
                target.setValue(source.value())
                target.blockSignals(False)
        self._sync_settings()
        if self.cur_group:
            box = self.cur_group.box
            box["w"] = self.settings.crop_w
            box["h"] = self.settings.crop_h
            self.canvas.set_lock(self.chk_lock.isChecked())
            self.canvas.set_box(box)
        self.refresh_manifest()
        if self.view_mode == "crop":
            self.refresh_preview()

    def on_lock_toggled(self, on):
        self.canvas.set_lock(on)
        self._sync_settings()

    # ------------------------------------------------------------ 胶囊控件
    def _sync_pills(self):
        """把胶囊上的文字/选中态跟真实控件对齐。"""
        try:
            lock = self.chk_lock.isChecked()
            for pill, on in ((self.pill_lock, lock), (self.pill_free, not lock)):
                pill.blockSignals(True)
                pill.setChecked(on)
                pill.blockSignals(False)
            self.pill_tosmall.setText("视野不足：" + self.cb_tosmall.currentText())
            self.pill_color.setText("颜色：" + self.cb_color.currentText())
            self.pill_ticks.setText("刻度：" + self.cb_ticks.currentText())
            for pill, chk in ((self.pill_unit, self.chk_unit), (self.pill_text, self.chk_text),
                              (self.pill_png, self.chk_bar_png)):
                pill.blockSignals(True)
                pill.setChecked(chk.isChecked())
                pill.blockSignals(False)
            self.pill_zoom.setText("导出放大 " + ["1×", "2×", "4×"][self.cb_zoom.currentIndex()])
            # 勾了原始位深导出 → 放大置灰：放大是插值，插值后的像素值没有定量意义
            raw_on = self.chk_raw.isChecked() or self.chk_raw_stack.isChecked()
            self.cb_zoom.setEnabled(not raw_on)
            self.cb_zoom.setToolTip("原始位深导出不使用放大（放大是插值，插值后的像素值没有定量意义）"
                                    if raw_on else
                                    "图片放大导出，标尺按放大后的分辨率重新高清绘制")
            # 处理链非空时才谈"内嵌要多大"（规格书 3.11.8：勾选后立刻给体积预估）
            it = self.cur_item
            if it is not None and getattr(it, "process", None):
                rect = render.crop_rect(it, self.cur_group.box_for(it), self._sync_settings()) \
                    if self.cur_group else None
                est = render.embed_estimate(it, rect, max(1, len(it.channels)))
                self.chk_raw_embed.setToolTip(
                    "做过处理时把处理前的原始像素一起写进同一个 TIFF，以后能一键还原；"
                    "这一张约 +%.0f MB（压缩前）" % (est / (1 << 20)))
        except AttributeError:
            pass

    def _refresh_pills(self):
        self._sync_settings()
        self._sync_pills()

    def on_pill_color(self):
        menu = QMenu(self)
        names = ["自动", "白色", "黑色", "自定义"]
        acts = [menu.addAction(x) for x in names]
        chosen = menu.exec(self.pill_color.mapToGlobal(self.pill_color.rect().bottomLeft()))
        if chosen in acts:
            if acts.index(chosen) == 3:
                self.pick_bar_color()
                return
            self.cb_color.setCurrentIndex(acts.index(chosen))
        self._refresh_pills()

    def on_pill_lock(self, on):
        self.chk_lock.setChecked(on)
        self.on_any_setting()

    def on_pill_tosmall(self):
        menu = QMenu(self)
        acts = [menu.addAction(x) for x in ("补边", "跳过", "收缩")]
        chosen = menu.exec(self.pill_tosmall.mapToGlobal(self.pill_tosmall.rect().bottomLeft()))
        if chosen in acts:
            self.cb_tosmall.setCurrentIndex(acts.index(chosen))

    def on_pill_ticks(self):
        menu = QMenu(self)
        names = ["两端+6 等分", "只画两端", "不画刻度"]
        acts = [menu.addAction(x) for x in names]
        chosen = menu.exec(self.pill_ticks.mapToGlobal(self.pill_ticks.rect().bottomLeft()))
        if chosen in acts:
            self.cb_ticks.setCurrentIndex(acts.index(chosen))

    def on_pill_zoom(self):
        menu = QMenu(self)
        names = ["1×（原像素）", "2×", "4×"]
        acts = [menu.addAction(x) for x in names]
        chosen = menu.exec(self.pill_zoom.mapToGlobal(self.pill_zoom.rect().bottomLeft()))
        if chosen in acts:
            self.cb_zoom.setCurrentIndex(acts.index(chosen))

    def on_pill_unit(self, on):
        self.chk_unit.setChecked(on)

    def on_pill_text(self, on):
        self.chk_text.setChecked(on)

    def on_pill_png(self, on):
        self.chk_bar_png.setChecked(on)

    def on_bar_position_changed(self, index):
        if index == 4 and self.cur_group is not None:
            if getattr(self.cur_group, "bar_anchor", None) is None:
                self.cur_group.bar_anchor = self._last_bar_anchor or (0.78, 0.9)
        self.on_any_setting()

    def reset_bar_position(self):
        if self.cur_group is not None:
            self.cur_group.bar_anchor = None
            self.cur_group.bar_text_anchor = None
        self.cb_pos.blockSignals(True)
        self.cb_pos.setCurrentIndex(0)
        self.cb_pos.blockSignals(False)
        self.on_any_setting()

    def on_bar_dragged(self, kind, nx, ny):
        """在图上拖动标尺（或文字）。"""
        if self.cur_group is None:
            return
        if not getattr(self, "_bar_drag_seen", False):
            # 只在一次拖动的第一次移动时记快照：拖到哪儿都不算新动作
            self._bar_drag_seen = True
            self._commit("移动标尺")
        if getattr(self.cur_group, "bar_anchor", None) is None:
            self.cur_group.bar_anchor = self._last_bar_anchor or (0.78, 0.9)
        if kind == "text":
            self.cur_group.bar_text_anchor = (nx, ny)
        else:
            self.cur_group.bar_anchor = (nx, ny)
            if self.cur_group.bar_text_anchor is not None:
                dx = nx - (self._last_bar_anchor or (nx, ny))[0]
                dy = ny - (self._last_bar_anchor or (nx, ny))[1]
                tx, ty = self.cur_group.bar_text_anchor
                self.cur_group.bar_text_anchor = (tx + dx, ty + dy)
        if self.cb_pos.currentIndex() != 4:
            self.cb_pos.blockSignals(True)
            self.cb_pos.setCurrentIndex(4)
            self.cb_pos.blockSignals(False)
        self._sync_settings()
        self.refresh_preview()

    def on_bar_drag_done(self):
        """标尺拖完了：下一次拖动重新记一份快照。"""
        self._bar_drag_seen = False

    def _st_for_group(self):
        """把当前组的自定义标尺位置并进参数里。"""
        import dataclasses
        st = self._sync_settings()
        group = self.cur_group
        if group is not None and getattr(group, "bar_anchor", None):
            st = dataclasses.replace(
                st, bar_position="custom", bar_anchor=tuple(group.bar_anchor),
                bar_text_anchor=(tuple(group.bar_text_anchor)
                                 if group.bar_text_anchor else None))
        return st

    def apply_preset(self, w, h):
        self.chk_lock.blockSignals(True)
        self.chk_lock.setChecked(abs(w - h) < 1e-6)
        self.chk_lock.blockSignals(False)
        for spin, val in ((self.f_w, w), (self.f_h, h)):
            spin.blockSignals(True)
            spin.setValue(val)
            spin.blockSignals(False)
        if self.cur_group and self.cur_item:
            field = self.cur_item.field_um() or 100.0
            self.cur_group.box = dict(x=max(0.0, (field - w) / 2), y=max(0.0, (field - h) / 2),
                                      w=float(w), h=float(h))
        self.on_crop_changed()
        self.refresh_preview()

    def pick_bar_color(self):
        from PySide6.QtWidgets import QColorDialog
        col = QColorDialog.getColor(QColor(self._custom_color), self, "标尺颜色")
        if col.isValid():
            self._custom_color = col.name()
            self.cb_color.setCurrentIndex(3)
            self._refresh_pills()

    def pick_outdir(self):
        d = QFileDialog.getExistingDirectory(self, "选择输出目录", self.ed_outdir.text()
                                             or paths.OUTPUT_DIR)
        if d:
            self.ed_outdir.setText(d)
            self.on_any_setting()

    # ------------------------------------------------------------ 导入
    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        self.import_paths([u.toLocalFile() for u in ev.mimeData().urls()])

    def import_folder(self):
        start = paths.ROOT
        d = QFileDialog.getExistingDirectory(self, "选择采集目录（可含子目录）", start)
        if d:
            self.import_paths([d])

    def import_menu(self):
        """导入按钮：文件夹 / 文件 两个入口合在一起。"""
        menu = QMenu(self)
        act_dir = menu.addAction("导入文件夹（含子目录）")
        act_file = menu.addAction("导入单个 / 多个文件…")
        pos = self.btn_import.mapToGlobal(self.btn_import.rect().bottomLeft())
        chosen = menu.exec(pos)
        if chosen is act_dir:
            self.import_folder()
        elif chosen is act_file:
            self.import_files()

    def import_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择图像", paths.ROOT,
            "科研图像 (*.oib *.oif *.czi *.lif *.lof *.xlif *.xlef *.xlcf "
            "*.tif *.tiff *.png *.jpg *.jpeg *.bmp);;所有文件 (*.*)")
        if files:
            self.import_paths(files)

    def import_paths(self, paths_in):
        files = loader.scan_paths(paths_in)
        if not files:
            QMessageBox.information(self, "没找到图像", "这个位置没有可读的图像文件。")
            return
        self._maybe_offer_stitch(files)
        self.lbl_status.setText("正在读取 %d 个文件的元数据…" % len(files))
        self._run(FnWorker(job_probe, files), self.on_probe_done)

    def _maybe_offer_stitch(self, files):
        """导入的是图块阵列时问一句要不要拼起来（P1-9 4.22.1 的"多文件阵列"）。"""
        if self._no_save():
            return
        try:
            grid = stitch_mod.parse_grid(list(files))
        except Exception:                            # noqa: BLE001
            grid = None
        if not grid or len(grid) < 4:
            return
        rows, cols = stitch_mod.grid_shape(grid)
        ans = QMessageBox.question(
            self, "检测到图块阵列",
            "这批文件看起来是 %d×%d 的拼图图块（共 %d 块）。\n要拼成一张图吗？"
            % (rows, cols, len(grid)))
        if ans != QMessageBox.Yes:
            return
        out_dir = self.settings.out_dir or paths.OUTPUT_DIR
        os.makedirs(out_dir, exist_ok=True)
        try:
            item = stitch_mod.stitch_paths(sorted(grid.values()), out_dir)
        except Exception as exc:                     # noqa: BLE001
            QMessageBox.warning(self, "拼接失败", str(exc))
            return
        self.items.append(item)
        self._regroup()
        self.refresh_groups()
        self.refresh_strip()
        self.refresh_manifest()
        self._mark_dirty()
        self.lbl_status.setText("已拼好：%s" % item.name)

    def _run(self, worker, on_done):
        self._workers.append(worker)
        worker.progress.connect(self._on_progress)
        worker.done.connect(on_done)
        worker.failed.connect(self.on_worker_failed)
        worker.finished.connect(lambda: self._drop_worker(worker))
        worker.start()

    def _drop_worker(self, worker):
        if worker in self._workers:
            self._workers.remove(worker)

    def _on_progress(self, i, total, msg):
        total = max(1, total)
        self.progress.setRange(0, 100)
        self.progress.setValue(int(i * 100 / total))
        if msg:
            self.lbl_status.setText("%s（%d/%d）" % (msg, i + 1, total))

    def on_worker_failed(self, msg):
        self.progress.setValue(0)
        self.lbl_status.setText("出错：" + msg)
        QMessageBox.warning(self, "出错了", msg)

    def on_probe_done(self, items):
        good = [it for it in items if it.calib != "失败"]
        known = {it.path for it in self.items}
        added = [it for it in good if it.path not in known]
        self.items.extend(added)
        self._regroup()
        self.refresh_groups()
        self.refresh_strip()
        self.refresh_manifest()
        self.progress.setValue(0)
        self.lbl_status.setText("已导入 %d 张（共 %d 张，%d 组）"
                                % (len(added), len(self.items), len(self.groups)))
        self._mark_dirty()
        self.start_thumbnails()

    def _regroup(self):
        """重新分组。

        · 自动分桶按「图片属性」走（尺寸 + µm/px），组对象按图片重叠复用，
          这样裁剪框 / 标尺位置 / 改过的名字都保得住；
        · 手工归过组的图（右键"移动到其他组"）按组 key 放回去，不会被分桶打散；
        · 空掉的组直接消失，不会留下点不动的空壳。
        """
        buckets = {}
        for it in self.items:
            if getattr(it, "group_manual", False):
                continue                          # 手工归组的图不参加自动分桶
            key = (it.width, it.height, round(it.umpp, 4))
            buckets.setdefault(key, []).append(it)

        old_groups = list(self.groups)
        used = set()
        groups = []

        # ① 自动桶 → 组
        ordered = sorted(buckets.items(), key=lambda kv: (-kv[0][2], -kv[0][0]))
        for _key, its in ordered:
            paths = {it.path for it in its}
            best = None
            for og in old_groups:
                if id(og) in used:
                    continue
                ov = len(paths & {i.path for i in og.images})
                if ov and (best is None or ov > best[0]):
                    best = (ov, og)
            if best is not None:
                g = best[1]
                used.add(id(g))
            else:
                g = Group(gid="", title="")
            g.images = list(its)
            groups.append(g)

        # ② 手工归组的图：放回用户指定的那一组
        for it in self.items:
            if not getattr(it, "group_manual", False):
                continue
            tgt = next((g for g in groups if g.key == it.group_key), None)
            if tgt is None:
                og = next((g for g in old_groups if g.key == it.group_key), None)
                if og is None:
                    it.group_manual = False       # 目标组没了 → 退回自动分桶
                    tgt = next((g for g in groups
                                if g.images and g.images[0].width == it.width
                                and g.images[0].height == it.height
                                and round(g.images[0].umpp, 4) == round(it.umpp, 4)), None)
                    if tgt is None:
                        tgt = Group(gid="", title="")
                        tgt.images = []
                        groups.append(tgt)
                else:
                    og.images = []
                    tgt = og
                    groups.append(tgt)
            for g in groups:
                if g is not tgt:
                    g.images = [x for x in g.images if x.path != it.path]
            if not any(x.path == it.path for x in tgt.images):
                tgt.images.append(it)

        # ③ 统一编号、补标题、初始化裁剪框
        for og in old_groups:                     # 手工建的空组：留着，好往里放图
            if getattr(og, "keep_empty", False) and not any(g.key == og.key for g in groups):
                og.images = []
                groups.append(og)
        self.groups = []
        for n, g in enumerate(groups, 1):
            g.gid = "g%d" % n
            ims = g.images
            if not getattr(g, "title_manual", False):
                if ims:
                    um = ims[0].umpp
                    g.title = "组 %d · %s µm/px · %d×%d" % (
                        n, ("%g" % um) if um else "未标定", ims[0].width, ims[0].height)
                else:
                    g.title = "组 %d（空）" % n
            if ims and not g.box:
                field = ims[0].field_um() or 100.0
                w = min(self.settings.crop_w, field)
                h = min(self.settings.crop_h, field)
                g.box = dict(x=max(0.0, (field - w) / 2), y=max(0.0, (field - h) / 2),
                             w=float(w), h=float(h))
            g.sync = self.chk_sync.isChecked()
            for it in ims:
                it.group = g.gid
            self.groups.append(g)
        gids = [g.gid for g in self.groups]
        if self.groups and (self.cur_group is None or self.cur_group.gid not in gids):
            live = next((g for g in self.groups if g.images), self.groups[0])
            self.cur_group = live
            self.select_group(live.gid)

    def refresh_groups(self):
        while self.group_layout.count() > 1:
            item = self.group_layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        self._group_cards = {}
        for g in self.groups:
            gc = GroupCard(g)
            gc.clicked.connect(self.select_group)
            gc.menu_requested.connect(self.group_menu)
            gc.set_active(bool(self.cur_group and g.gid == self.cur_group.gid))
            self.group_layout.insertWidget(self.group_layout.count() - 1, gc)
            self._group_cards[g.gid] = gc
        n_oib = sum(1 for it in self.items if "内嵌" in it.calib)
        n_bar = sum(1 for it in self.items if "标尺" in it.calib)
        n_man = sum(1 for it in self.items if "手动" in it.calib)
        self.lbl_src.setText("文件自带标定 %d · 标尺识别 %d · 手动 %d" % (n_oib, n_bar, n_man))

    def select_group(self, gid):
        for g in self.groups:
            if g.gid == gid:
                self.cur_group = g
                break
        if not self.cur_group:
            return
        self.chk_sync.blockSignals(True)
        self.chk_sync.setChecked(self.cur_group.sync)
        self.chk_sync.blockSignals(False)
        for gid2, gc in getattr(self, "_group_cards", {}).items():
            gc.set_active(gid2 == self.cur_group.gid)
        self.refresh_strip()
        if self.cur_group.images:
            self.select_item(self.cur_group.images[0].path)
            box = self.cur_group.box_for(self.cur_group.images[0])
            for f, val in ((self.f_w, box["w"]), (self.f_h, box["h"])):
                f.blockSignals(True)
                f.setValue(val)
                f.blockSignals(False)
            self.settings.crop_w = box["w"]
            self.settings.crop_h = box["h"]
            self.canvas.set_lock(abs(box["w"] - box["h"]) < 1e-6)
        else:
            self.cur_item = None
            self.lbl_group_head.setText(self.cur_group.title)
            self.lbl_group_info.setText("这一组还没有图片")
            self.lbl_px.setText("")
            self.lbl_size.setText("—")
            self.lbl_status.setText("「%s」还没有图片：在别的组里右键缩略图 → 移动到这一组"
                                    % self.cur_group.title)
            self.refresh_preview()
            self.refresh_channels()
            self.refresh_manifest()

    def on_sync_toggled(self, on):
        if not self.cur_group:
            return
        self.cur_group.sync = on
        if on:
            self.cur_group.box = self.canvas.box()
            for it in self.cur_group.images:
                self.cur_group.boxes[it.path] = dict(self.cur_group.box)
        elif self.cur_item:
            self.cur_group.boxes[self.cur_item.path] = self.canvas.box()
        self._sync_settings()
        self.lbl_status.setText("组内裁剪框位置：%s" % ("一致" if on else "每张各自设置"))

    # ------------------------------------------------------------ 中栏
    def refresh_strip(self):
        while self.strip_layout.count() > 1:
            item = self.strip_layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        self._thumb_buttons = {}
        if not self.cur_group:
            return
        for it in self.cur_group.images:
            tb = ThumbButton(it)
            tb.clicked.connect(self.select_item)
            tb.menu_requested.connect(self.thumb_menu)
            tb.set_active(bool(self.cur_item and it.path == self.cur_item.path))
            # 缩略图按"通道名/配色/显示区间"算缓存 key。改了通道（比如重新探测元数据后
            # 从"绿+红"变回"只有绿"）缓存 key 就变了 —— 这里按**当前**通道重算一次路径，
            # 别再拿 `_thumbs` 里那个旧文件（否则条带里一直显示旧样子，实测反馈过）。
            want = loader.thumb_path(it, 256)
            if os.path.exists(want):
                self._thumbs[it.path] = want
                tb.set_thumb(want)
            else:
                self._thumbs.pop(it.path, None)     # 旧 key 的缩略图作废，等重出
            self.strip_layout.insertWidget(self.strip_layout.count() - 1, tb)
            self._thumb_buttons[it.path] = tb

    def select_item(self, path):
        it = next((x for x in self.items if x.path == path), None)
        if not it:
            return
        self.cur_item = it
        self.cur_t, self.cur_z = 0, 0
        self.frame = it.flat_index(0, 0)
        if self.cur_group and self.cur_group.sync is False:
            self.cur_group.boxes.setdefault(path, dict(self.cur_group.box))
        for p, tb in getattr(self, "_thumb_buttons", {}).items():
            tb.set_active(p == path)
        self._sync_frame_ui()
        self.refresh_channels()
        self._sync_proj_tool()
        self._sync_process_tool()
        self.refresh_rois()
        self.refresh_calib()
        self.refresh_preview()
        self._settle_channels(it)      # 解码后 loader 可能刚合并/隐藏了通道，补刷通道卡
        self.refresh_manifest()

    def _sync_frame_ui(self):
        """把 Z / T 两条滑条和标签对齐到当前图（P0-3 3.18.4）。"""
        it = self.cur_item
        if it is None:
            return
        if getattr(self, "zp_tool", None) is None:
            return
        zc = max(1, int(it.z_count or 1))
        tc = max(1, int(it.t_count or 1))
        self.frames_card.setVisible(it.frames > 1)
        for w, n, val in ((self.z_slider, zc, self.cur_z), (self.frame_slider, tc, self.cur_t)):
            w.blockSignals(True)
            w.setRange(1, n)
            w.setValue(min(max(1, int(val) + 1), n))
            w.blockSignals(False)
        self.z_row.setVisible(zc > 1)              # 没有 Z 就不显示这一行
        if zc > 1:
            step = ("步进 %.3g µm" % it.z_step_um) if it.z_step_um > 0 else "步进未知"
            depth = (" · 深度 %.3g µm" % it.z_range_um) if it.z_range_um > 0 else ""
            self.lbl_z.setText("第 %d/%d 层 · %s%s"
                               % (self.cur_z + 1, zc, step, depth))
        self.t_row.setVisible(tc > 1)
        if tc > 1:
            iv = ("间隔 %.3g s" % it.t_interval_s) if it.t_interval_s > 0 else "间隔未知"
            tot = (" · 共 %.3g s" % ((tc - 1) * it.t_interval_s)) if it.t_interval_s > 0 else ""
            self.lbl_frame.setText("第 %d/%d 点 · %s%s"
                                   % (self.cur_t + 1, tc, iv, tot))
        # 元数据说不清多帧到底是什么 → 让用户自己声明（判据见规格书 3.18.3）
        show = bool(it.frames > 1 and not it.z_meta_declared and not it.t_meta_declared)
        self.btn_declare.setVisible(show)
        if show:
            self.btn_declare.setText("多帧 = Z 栈" if zc <= 1 else "多帧 = 时间序列")
        self._sync_proj_tool()          # Z 滑条动了，「当前层 ± n」的提示要跟着变

    def on_z_changed(self, value):
        it = self.cur_item
        if it is None:
            return
        self.cur_z = max(0, int(value) - 1)
        it.proj_center = self.cur_z                 # 「当前层 ± n」跟着 Z 滑条走
        self.frame = it.flat_index(self.cur_t, self.cur_z)
        self._sync_frame_ui()
        self.refresh_preview()
        self.refresh_manifest()

    def on_frame_changed(self, value):
        it = self.cur_item
        self.cur_t = max(0, int(value) - 1)
        if it is not None:
            self.frame = it.flat_index(self.cur_t, self.cur_z)
        self._sync_frame_ui()
        self.refresh_preview()
        self.refresh_manifest()

    def toggle_declare(self):
        """多帧 = Z 栈 ↔ 时间序列（规格书 3.18.3）。"""
        it = self.cur_item
        if it is None:
            return
        kind = "t" if (it.z_count or 1) > 1 else "z"
        self._commit("改多帧的含义")
        it.declare_frames(kind)
        self.cur_t, self.cur_z = 0, 0
        self.frame = it.flat_index(0, 0)
        self._sync_frame_ui()
        self.refresh_strip()
        self.refresh_calib()
        self.refresh_preview()
        self.refresh_manifest()
        self.lbl_status.setText("这张图的多帧已按「%s」处理（%d 层/点）"
                                % ("Z 栈" if kind == "z" else "时间序列", it.frames))

    # ------------------------------------------------------------ Z 投影（P1-5）
    def _sync_proj_tool(self):
        """投影卡片对齐到当前图（只有多层 Z 才显示）。"""
        it = self.cur_item
        if getattr(self, "zp_tool", None) is None:
            return
        if it is None:
            self.zp_tool.setVisible(False)
            return
        zc = max(1, int(it.z_count or 1))
        self.zp_tool.setVisible(zc > 1)
        if zc <= 1:
            return
        mode = (getattr(it, "proj_mode", "none") or "none").lower()
        rmode = (getattr(it, "proj_range_mode", "all") or "all").lower()
        for w, val in ((self.cb_proj, {"none": 0, "max": 1, "sum": 2, "mean": 3,
                                       "sd": 4}.get(mode, 0)),
                       (self.cb_proj_range, {"all": 0, "around": 1,
                                             "manual": 2}.get(rmode, 0))):
            w.blockSignals(True)
            w.setCurrentIndex(int(val))
            w.blockSignals(False)
        lo, hi = zproj.proj_range(it)
        for w, val, top in ((self.sp_proj_n, int(getattr(it, "proj_n", 3) or 3), 999),
                            (self.sp_proj_from, lo + 1, zc),
                            (self.sp_proj_to, hi + 1, zc)):
            w.blockSignals(True)
            w.setRange(1, max(1, top))
            w.setValue(max(1, min(val, max(1, top))))
            w.blockSignals(False)
        # 只有选中的那个范围参数才可编辑
        for w, on in ((self.sp_proj_n, rmode == "around"),
                      (self.sp_proj_from, rmode == "manual"),
                      (self.sp_proj_to, rmode == "manual")):
            w.setEnabled(on)
        if mode != "none":
            self.lbl_proj_hint.setText("当前：%s，第 %d~%d 层（共 %d 层）"
                                       % (zproj.proj_label(mode), lo + 1, hi + 1, zc))
        else:
            self.lbl_proj_hint.setText("没投影：显示当前那一层")

    def on_proj_changed(self, *_a):
        it = self.cur_item
        if it is None or getattr(self, "cb_proj", None) is None:
            return
        self._commit("改 Z 投影")
        it.proj_mode = ["none", "max", "sum", "mean", "sd"][self.cb_proj.currentIndex()]
        it.proj_range_mode = ["all", "around", "manual"][
            self.cb_proj_range.currentIndex()]
        it.proj_n = int(self.sp_proj_n.value())
        it.proj_from = int(self.sp_proj_from.value()) - 1
        it.proj_to = int(self.sp_proj_to.value()) - 1
        if it.proj_to < it.proj_from:
            it.proj_to = it.proj_from
        it.proj_center = self.cur_z
        self._sync_proj_tool()
        self._sync_frame_ui()
        if self.view_mode == "crop":
            self.refresh_preview()
        else:
            self._planes_key = None        # 投影结果不是同一份像素 → 强制重算
            self._base_key = None
            self.refresh_preview()
        self._refresh_thumb_later()
        self.refresh_manifest()
        tag = zproj.proj_label(it.proj_mode)
        self.lbl_status.setText("Z 投影：%s（第 %d~%d 层）"
                                % (tag, zproj.proj_range(it)[0] + 1,
                                   zproj.proj_range(it)[1] + 1)
                                if it.proj_mode != "none" else "已关掉 Z 投影")

    def on_proj_range_changed(self, *_a):
        self.on_proj_changed()

    # ------------------------------------------------------------ ROI 与测量（P1-6）
    def _roi_shapes(self):
        it = self.cur_item
        if not it:
            return []
        return [(r.kind, r.points, r.label, bool(r.is_bg), r.rid)
                for r in roi_mod.rois_of(it)]

    def _roi_row_text(self, r):
        """列表那一行：名字 · 尺寸。看不出来哪个是哪个的时候最有用。"""
        it = self.cur_item
        if it is None:
            return r.label
        box = roi_mod.roi_px(r, it.width, it.height)
        if box is None:
            return r.label
        x0, y0, x1, y1 = box
        w, h = (x1 - x0), (y1 - y0)
        umpp = float(getattr(it, "umpp", 0.0) or 0.0)
        if r.kind == "line":
            return ("%s · 长 %.2f µm" % (r.label, np.hypot(w, h) * umpp)) if umpp > 0 \
                else ("%s · 长 %d px" % (r.label, int(round(np.hypot(w, h)))))
        if umpp > 0:
            return "%s · %d×%d px · %.1f×%.1f µm" % (r.label, w, h, w * umpp, h * umpp)
        return "%s · %d×%d px" % (r.label, w, h)

    def on_roi_selected(self, rid):
        """画布上点了某个 ROI：记下选中项（右栏不再列 ROI，只留计数与提示）。"""
        self._roi_sel = str(rid or "")
        r = self._roi_by_rid(self._roi_sel)
        if r is not None and self.lbl_status is not None:
            self.lbl_status.setText("已选中「%s」：可以拖动/缩放，右键改名·设背景·删除，Delete 删除"
                                    % r.label)

    def _roi_by_rid(self, rid):
        it = self.cur_item
        if it is None or not rid:
            return None
        return next((x for x in roi_mod.rois_of(it) if x.rid == rid), None)

    def roi_menu(self, rid, global_pos):
        """在图上右键某个 ROI：改名 / 设背景 / 点大小 / 复制到本组 / 删除。"""
        r = self._roi_by_rid(rid)
        if r is None:
            return
        self._roi_sel = rid
        self.canvas.set_roi_sel(rid)
        menu = QMenu(self)
        head = menu.addAction("%s · %s" % (roi_mod.kind_name(r.kind),
                                           self._roi_row_text(r).split(" · ", 1)[-1]))
        head.setEnabled(False)
        menu.addSeparator()
        a_ren = menu.addAction("改名…")
        a_bg = menu.addAction("取消背景" if r.is_bg else "设为背景（其它 ROI 自动扣它）")
        a_r = menu.addAction("点的大小…") if r.kind == "point" else None
        a_grp = menu.addAction("复制到本组其它图")
        menu.addSeparator()
        a_del = menu.addAction("删除这个 ROI")
        chosen = menu.exec(global_pos)
        if chosen is None:
            return
        if chosen is a_ren:
            self.rename_roi(r)
        elif chosen is a_bg:
            self.roi_toggle_bg(r)
        elif a_r is not None and chosen is a_r:
            self.set_point_radius(r)
        elif chosen is a_grp:
            self.copy_roi_to_group(r)
        elif chosen is a_del:
            self.roi_delete(r)

    def set_point_radius(self, r):
        """点 ROI 的取样半径（像素）：默认 3，太小容易被噪声带偏。"""
        from PySide6.QtWidgets import QInputDialog
        cur = int(round(float(r.radius or 0.0) or roi_mod.POINT_R))
        val, ok = QInputDialog.getInt(self, "点的大小", "取样半径（像素）：",
                                      cur, 1, 64, 1)
        if not ok or val == cur:
            return
        self._commit("改点的大小")
        r.radius = float(val)
        self.refresh_rois()
        self.refresh_preview()
        self.lbl_status.setText("「%s」取样半径改成 %d 像素" % (r.label, val))

    def copy_roi_to_group(self, r):
        """把某一个 ROI 复制到本组其它图（同一个视野的重复拍摄用）。"""
        it = self.cur_item
        if it is None or self.cur_group is None:
            return
        others = [x for x in self.cur_group.images if x.path != it.path]
        if not others:
            QMessageBox.information(self, "本组只有这一张", "这一组没有别的图。")
            return
        self._commit("ROI 复制到本组")
        n = 0
        for x in others:
            have = {q.label for q in roi_mod.rois_of(x)}
            if r.label in have:
                continue
            x.rois = roi_mod.rois_of(x) + [roi_mod.Roi(
                kind=r.kind, points=[[float(p[0]), float(p[1])] for p in r.points],
                z=r.z, t=r.t, ch=r.ch, label=r.label, is_bg=bool(r.is_bg),
                radius=float(r.radius or 0.0))]
            n += 1
        self.refresh_rois()
        self.refresh_manifest()
        self.lbl_status.setText("「%s」已复制到本组 %d 张图（同名的不重复加）" % (r.label, n))

    def on_roi_drag_started(self):
        """按下的瞬间记快照 —— 等松手再记就成"改之后"了。"""
        self._commit("移动/缩放 ROI")

    def on_roi_edited(self, rid, points):
        it = self.cur_item
        if it is None or not points:
            return
        for r in roi_mod.rois_of(it):
            if r.rid == rid:
                r.points = [[float(p[0]), float(p[1])] for p in points]
                break
        self.refresh_rois()
        self.refresh_manifest()
        self.lbl_status.setText("ROI 已更新（%s）" % rid)

    def roi_delete_by_rid(self, rid):
        it = self.cur_item
        r = next((x for x in roi_mod.rois_of(it) if x.rid == rid), None) if it else None
        if r is not None:
            self.roi_delete(r)

    def refresh_rois(self):
        """刷新画布上的 ROI 叠加 + 底下一行计数。

        2026-09-28 用户要求：右栏不再一个个列 ROI（太长太占地方），
        改成**在图上右键那个 ROI** 来编辑/删除，这里只留一行汇总。
        """
        it = self.cur_item
        rois = roi_mod.rois_of(it) if it else []
        if getattr(self, "_roi_sel", "") and \
                not any(x.rid == self._roi_sel for x in rois):
            self._roi_sel = ""            # 选中的那个不在这张图上了
        if self.view_mode == "full":
            self.canvas.set_rois(self._roi_shapes())
        else:
            self.canvas.set_rois([])          # 裁剪结果视图不画 ROI（那是成品预览）
        self.canvas.set_roi_sel(getattr(self, "_roi_sel", ""))
        self.on_roi_selected(getattr(self, "_roi_sel", ""))
        n_bg = sum(1 for r in rois if r.is_bg)
        kinds = {}
        for r in rois:
            kinds[roi_mod.kind_name(r.kind)] = kinds.get(roi_mod.kind_name(r.kind), 0) + 1
        detail = "、".join("%s %d" % (k, v) for k, v in kinds.items())
        self.lbl_roi.setText("共 %d 个 ROI%s%s\n图上右键 ROI 可改名/设背景/删除；按 Esc 退出画图"
                             % (len(rois), ("（%s）" % detail) if detail else "",
                                "· 含 1 个背景" if n_bg else ""))

    def select_roi_row(self, r):
        """右栏列表里点了一行 → 图上高亮它；不在视野里就把视图挪过去。"""
        self._roi_sel = r.rid
        self.canvas.set_roi_sel(r.rid)
        self.on_roi_selected(r.rid)
        if self.view_mode == "full" and r.points:
            xs = [p[0] for p in r.points]
            ys = [p[1] for p in r.points]
            self.canvas.center_on_frac((min(xs) + max(xs)) / 2.0,
                                       (min(ys) + max(ys)) / 2.0)
        self.lbl_status.setText("已选中「%s」：图上可以拖动/缩放，按 Delete 删除"
                                % r.label)

    def apply_rois_to_group(self):
        """把当前图的 ROI 套用到本组其它每一张（归一化坐标 → 相对位置一致）。

        同一视野拍的一串图（时间序列、Z 栈、重复孔）用这个是常态，
        以前得每张手画一遍（2026-09-26 用户反馈"太麻烦"）。
        """
        it = self.cur_item
        if it is None or self.cur_group is None:
            return
        src = [r for r in roi_mod.rois_of(it) if not r.is_bg]
        if not src:
            QMessageBox.information(self, "还没有 ROI", "先在这张图上画一个 ROI。")
            return
        others = [x for x in self.cur_group.images if x.path != it.path]
        if not others:
            QMessageBox.information(self, "本组只有这一张", "这一组没有别的图。")
            return
        self._commit("ROI 套用到本组")
        n_img = n_roi = 0
        for x in others:
            have = {r.label for r in roi_mod.rois_of(x)}
            add = []
            for r in src:
                if r.label in have:
                    continue                      # 同名的不重复加
                add.append(roi_mod.Roi(kind=r.kind,
                                       points=[[float(p[0]), float(p[1])] for p in r.points],
                                       z=r.z, t=r.t, ch=r.ch, label=r.label,
                                       is_bg=bool(r.is_bg)))
            if add:
                x.rois = roi_mod.rois_of(x) + add
                n_img += 1
                n_roi += len(add)
        self.refresh_rois()
        self.refresh_manifest()
        self.lbl_status.setText("已把 %d 个 ROI 套用到本组另外 %d 张图（共 %d 个，同名的不重复加）"
                                % (len(src), n_img, n_roi))

    def rename_roi(self, r):
        from PySide6.QtWidgets import QInputDialog
        txt, ok = QInputDialog.getText(self, "给 ROI 改名", "名字：", text=r.label)
        txt = (txt or "").strip()
        if not ok or not txt or txt == r.label:
            return
        self._commit("改 ROI 名字")
        r.label = txt
        self.refresh_rois()
        self.refresh_manifest()

    def on_roi_tool(self, kind):
        """点一次工具就一直能画（2026-09-28 用户要求）；再点同一个 = 退出。

        工具按钮是可勾选的，勾中状态由画布发来的 roi_mode_changed 同步。
        """
        if self.cur_item is None:
            return
        self.canvas.set_roi_mode(kind)
        mode = self.canvas.roi_mode()
        if not mode:
            self.lbl_status.setText("已退出画 ROI")
            return
        self.lbl_status.setText(
            "「%s」工具已打开：可以一直画，画完继续画；再点一次工具或按 Esc 退出"
            % roi_mod.kind_name(mode))

    def on_roi_mode_changed(self, mode):
        """画布 armed 的工具变了 → 同步那三个按钮的勾选状态。"""
        for k, b in getattr(self, "_roi_tool_buttons", {}).items():
            b.blockSignals(True)
            b.setChecked(bool(mode) and k == mode)
            b.blockSignals(False)

    def on_roi_done(self, kind, x0, y0, x1, y1):
        """画完 → 归一化到**原图整帧**存进 item.rois（规格书 4.8.2）。"""
        it = self.cur_item
        if it is None:
            return
        used = getattr(self, "_used_rect", (0.0, 0.0, 1.0, 1.0))
        fx0 = used[0] + x0 * (used[2] - used[0])
        fy0 = used[1] + y0 * (used[3] - used[1])
        fx1 = used[0] + x1 * (used[2] - used[0])
        fy1 = used[1] + y1 * (used[3] - used[1])
        self._commit("新建 ROI")
        if kind == "line":
            # 直线**必须保序**：以前无条件 min/max 打包，负斜率的线会被翻成另一条对角线
            points = [[fx0, fy0], [fx1, fy1]]
        elif kind == "point":
            points = [[fx0, fy0]]             # 点只存一个坐标
        else:
            points = [[min(fx0, fx1), min(fy0, fy1)],
                      [max(fx0, fx1), max(fy0, fy1)]]
        rois = roi_mod.rois_of(it)
        r = roi_mod.Roi(kind=kind, points=points,
                        label=roi_mod.next_label(rois, kind))
        it.rois = rois + [r]
        self._roi_sel = r.rid
        self.refresh_rois()
        self.refresh_manifest()
        self.lbl_status.setText("已新建「%s」：图上可以直接拖动/缩放，按 Delete 删除"
                                % r.label)
        if kind == "point":
            self.lbl_status.setText("已新建「%s」：右键可以改取样半径；工具还开着，继续点下一个"
                                    % r.label)

    def roi_toggle_bg(self, r):
        it = self.cur_item
        if it is None:
            return
        self._commit("改背景 ROI")
        for x in roi_mod.rois_of(it):           # 背景 ROI 只留一个
            x.is_bg = bool(x is r and not r.is_bg)
        self.refresh_rois()

    def roi_delete(self, r):
        it = self.cur_item
        if it is None:
            return
        self._commit("删 ROI")
        it.rois = [x for x in roi_mod.rois_of(it) if x.rid != r.rid]
        if getattr(self, "_roi_sel", "") == r.rid:
            self._roi_sel = ""
        self.canvas.set_roi_sel("")
        self.refresh_rois()
        self.refresh_manifest()
        self.lbl_status.setText("已删除「%s」" % r.label)

    def roi_rows_data(self, rois=None, chans=None, frames=None):
        """测量行（长表：每个 ROI × 通道 × 帧一行）。

        不传参数就是老行为：所有非背景 ROI × 所有可见通道 × 当前帧（自检直接调这个）。
        测量面板会传具体的 rois / chans / frames（frames 是展平帧号）。
        """
        it = self.cur_item
        if it is None:
            return [], []
        stack = loader.load_stack(it)
        use = ([r for r in roi_mod.rois_of(it) if not r.is_bg] if rois is None
               else [r for r in rois if not r.is_bg])
        frm = [self.frame] if frames is None else list(frames)
        rows = []
        for fr in frm:
            bg = analysis.bg_means(stack, it, frame=fr)
            for r in use:
                part = analysis.roi_stats(stack, it, r, frame=fr, bg=bg, chans=chans)
                if len(frm) > 1:                       # 多帧才写"帧"列，免得单帧时多一列噪音
                    for x in part:
                        x["frame"] = int(fr) + 1
                rows.extend(part)
        return rows, analysis.csv_header(it)

    # ---- 测量面板用的取数接口（P1-6 2026-09-26） ----------------------------
    def measure_frames(self, mode="current"):
        """测量用哪几帧：当前帧 / 全部帧。"""
        it = self.cur_item
        if it is None:
            return [0]
        if mode == "all" and int(getattr(it, "frames", 1) or 1) > 1:
            return list(range(int(it.frames)))
        return [int(self.frame)]

    def measure_profile(self, line, frame=None, width=None):
        """线剖面：指定某条直线 ROI + 帧 + 剖面宽度。"""
        it = self.cur_item
        if it is None or line is None:
            return {}, []
        w = int(self.sp_prof_w.value()) if width is None else int(width)
        prof = analysis.line_profile(loader.load_stack(it), it, line,
                                     frame=self.frame if frame is None else frame,
                                     width=w)
        head = analysis.csv_header(it, extra=["线剖面：%s" % line.label,
                                              "剖面宽度：±%d px" % w])
        return prof, head

    def measure_coloc(self, roi, ch_a, ch_b, frame=None):
        it = self.cur_item
        if it is None:
            return {}, []
        chans = analysis.visible_channels(it)
        a = chans[min(max(0, int(ch_a)), len(chans) - 1)] if chans else None
        b = chans[min(max(0, int(ch_b)), len(chans) - 1)] if chans else None
        if a is None or b is None or a.index == b.index:
            return {}, []
        res = analysis.colocalization(loader.load_stack(it), it, a.index, b.index,
                                      roi=roi,
                                      frame=self.frame if frame is None else frame)
        head = analysis.csv_header(it, extra=[
            "共定位：%s vs %s" % (a.name, b.name),
            "范围：%s" % (("ROI " + roi.label) if roi is not None else "整帧")])
        return res, head

    def measure_particles(self, roi, ch_i, frame=None, min_area=None):
        it = self.cur_item
        if it is None:
            return {}, []
        chans = analysis.visible_channels(it)
        if not chans:
            return {}, []
        ch = chans[min(max(0, int(ch_i)), len(chans) - 1)]
        stack = loader.load_stack(it)
        fr = int(self.frame if frame is None else frame)
        plane = np.asarray(stack[fr, ch.index], np.float32)
        thr = None
        if roi is not None:
            m = roi_mod.roi_mask(roi, it.width, it.height)
            if m is not None:
                thr = analysis.otsu_threshold(plane[m])   # 阈值只按 ROI 内算
                plane = np.where(m, plane, 0.0)
        area = int(self.sp_particle_min.value()) if min_area is None else int(min_area)
        res = analysis.count_particles(plane, thr=thr, min_area_px=area)
        head = analysis.csv_header(it, extra=[
            "粒子计数：%s，阈值 %.1f，面积下限 %d px" % (ch.name, res.get("thr", 0), area),
            "范围：%s" % (("ROI " + roi.label) if roi is not None else "整帧")])
        return res, head

    def roi_measure(self):
        """打开测量面板（2026-09-26：强度/剖面/共定位/粒子合成一个面板）。"""
        if self.cur_item is None:
            return
        if not roi_mod.rois_of(self.cur_item):
            ans = QMessageBox.question(
                self, "还没有 ROI",
                "还没有画 ROI。要按整帧测量吗？\n（强度表为空，但共定位/粒子可以整帧算）")
            if ans != QMessageBox.Yes:
                return
        MeasureDialog(self).exec()

    def roi_profile_data(self):
        it = self.cur_item
        if it is None:
            return {}, []
        line = next((r for r in roi_mod.rois_of(it) if r.kind == "line"), None)
        if line is None:
            return {}, []
        prof = analysis.line_profile(loader.load_stack(it), it, line, frame=self.frame,
                                     width=int(self.sp_prof_w.value()))
        return prof, analysis.csv_header(it, extra=["线剖面：%s" % line.label])

    def roi_coloc_data(self):
        it = self.cur_item
        if it is None:
            return {}, []
        chans = analysis.visible_channels(it)
        if len(chans) < 2:
            return {}, []
        roi = next((r for r in roi_mod.rois_of(it) if not r.is_bg), None)
        res = analysis.colocalization(loader.load_stack(it), it,
                                      chans[0].index, chans[1].index,
                                      roi=roi, frame=self.frame)
        head = analysis.csv_header(it, extra=[
            "共定位：%s vs %s" % (chans[0].name, chans[1].name),
            "范围：%s" % (("ROI " + roi.label) if roi else "整帧"),
            "已配准：%s" % ("是" if res.get("registered") else "否（结果可能不可靠）")])
        return res, head

    def roi_particles_data(self):
        it = self.cur_item
        if it is None:
            return {}, []
        chans = analysis.visible_channels(it)
        if not chans:
            return {}, []
        stack = loader.load_stack(it)
        roi = next((r for r in roi_mod.rois_of(it)
                    if r.kind in ("rect", "ellipse") and not r.is_bg), None)
        plane = np.asarray(stack[self.frame, chans[0].index], np.float32)
        thr = None
        if roi is not None:
            m = roi_mod.roi_mask(roi, it.width, it.height)
            if m is not None:
                # 阈值只在 ROI 内部算：否则 ROI 外的 0 会把 Otsu 拉偏（实测踩过）
                thr = analysis.otsu_threshold(plane[m])
                plane = np.where(m, plane, 0.0)
        res = analysis.count_particles(plane, thr=thr,
                                       min_area_px=int(self.sp_particle_min.value()))
        head = analysis.csv_header(it, extra=[
            "粒子计数：%s，阈值 %.1f，面积下限 %d px"
            % (chans[0].name, res.get("thr", 0), int(self.sp_particle_min.value())),
            "范围：%s" % (("ROI " + roi.label) if roi else "整帧")])
        return res, head

    def roi_export_csv(self):
        """导出测量结果。

        2026-09-26：以前把"ROI 表 + 线剖面"塞进同一个 CSV（空行隔开），
        Excel 打开是一张表两套列头，很难用 —— 现在分开成两个文件：
          roi_measure.csv（每个 ROI 一行，通道展开成列）
          roi_profile.csv（线剖面，仅当画了直线 ROI）
        """
        from ui.roi_dialog import to_wide
        rows, head = self.roi_rows_data()
        prof, phead = self.roi_profile_data()
        if not rows and not prof:
            QMessageBox.information(self, "没有可导出的数据", "先画一个 ROI。")
            return
        out_dir = self.settings.out_dir or paths.OUTPUT_DIR
        p, _f = QFileDialog.getSaveFileName(
            self, "导出 ROI 结果", os.path.join(out_dir, "roi_measure.csv"),
            "CSV (*.csv)")
        if not p:
            return
        wide = to_wide(rows) if rows else []
        with open(p, "w", encoding="utf-8-sig", newline="") as fh:
            fh.write(analysis.rows_to_csv(wide, head))
        extra_files = [p]
        if prof:
            p2 = os.path.splitext(p)[0] + "_profile.csv"
            block = [dict(位置_µm=u, **{k: v[i] for k, v in prof["series"].items()})
                     for i, u in enumerate(prof["um"])]
            with open(p2, "w", encoding="utf-8-sig", newline="") as fh:
                fh.write(analysis.rows_to_csv(block, phead))
            extra_files.append(p2)
        self.lbl_status.setText("已导出 %d 个 CSV：%s（utf-8-sig，Excel 直接打开）"
                                % (len(extra_files),
                                   "、".join(os.path.basename(x) for x in extra_files)))

    # ------------------------------------------------------------ 处理链（P1-7）
    def _proc_step(self, it, kind):
        for s in (getattr(it, "process", None) or []):
            if (s.kind or "").lower() == kind:
                return s
        return None

    def _sync_process_tool(self):
        """处理卡片对齐到当前图（单通道就把配准置灰）。"""
        it = self.cur_item
        if getattr(self, "proc_tool", None) is None:
            return
        if it is None:
            self.proc_tool.setVisible(False)
            return
        self.proc_tool.setVisible(True)
        chans = list(getattr(it, "channels", []) or [])
        reg = self._proc_step(it, "register")
        bg = self._proc_step(it, "bg")
        drift = self._proc_step(it, "drift")
        for w, on in ((self.sw_reg, bool(reg)), (self.sw_bg, bool(bg)),
                      (self.sw_drift, bool(drift))):
            w.blockSignals(True)
            w.setChecked(on)
            w.blockSignals(False)
        self.cb_reg_ref.blockSignals(True)
        self.cb_reg_ref.clear()
        for c in chans:
            self.cb_reg_ref.addItem(c.name or ("CH%d" % (c.index + 1)))
        if chans:
            cur = int((reg.params or {}).get("ref_ch", 0) if reg else 0)
            self.cb_reg_ref.setCurrentIndex(min(max(0, cur), len(chans) - 1))
        self.cb_reg_ref.blockSignals(False)
        single = len(chans) < 2
        for w in (self.sw_reg, self.cb_reg_ref, self.btn_reg_calc):
            w.setEnabled(not single)
        self.sw_reg.setToolTip("只有一路通道，不需要配准" if single else
                               "把各个荧光通道按平移对齐（只做平移）")
        self._rebuild_reg_rows(it, reg)
        p = dict((bg.params if bg else {}) or {})
        self.cb_bg_mode.blockSignals(True)
        self.cb_bg_mode.setCurrentIndex(1 if p.get("mode") == "const" else 0)
        self.cb_bg_mode.blockSignals(False)
        for w, val in ((self.sp_bg_p, float(p.get("p", 5.0) or 5.0)),
                       (self.sp_bg_c, float(p.get("c", 0.0) or 0.0))):
            w.blockSignals(True)
            w.setValue(val)
            w.blockSignals(False)
        self.sp_bg_p.setEnabled(self.cb_bg_mode.currentIndex() == 0)
        self.sp_bg_c.setEnabled(self.cb_bg_mode.currentIndex() == 1)
        self.sp_drift_ref.blockSignals(True)
        self.sp_drift_ref.setRange(1, max(1, int(it.frames or 1)))
        self.sp_drift_ref.setValue(int((drift.params or {}).get("ref_frame", 0)
                                       if drift else 0) + 1)
        self.sp_drift_ref.blockSignals(False)
        self.sp_drift_ref.setEnabled(int(it.frames or 1) > 1)
        self.btn_drift_calc.setEnabled(int(it.frames or 1) > 1)
        on = [n for n, ok in (("配准", reg), ("扣背景", bg), ("漂移", drift)) if ok]
        self.lbl_proc.setText("已启用：" + ("、".join(on) if on else "无（看的是原始像素）"))

    def _rebuild_reg_rows(self, it, reg):
        """每个通道一行：位移读数 + 手动微调（±0.5 px 步进）。"""
        while self.reg_rows.count():
            item = self.reg_rows.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        params = dict((reg.params if reg else {}) or {})
        shifts = dict(params.get("shifts") or {})
        manual = dict(params.get("manual") or {})
        ref_ch = int(params.get("ref_ch", 0) or 0)
        for i, c in enumerate(list(getattr(it, "channels", []) or [])):
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(5)
            name = c.name or ("CH%d" % (i + 1))
            s = shifts.get(str(i))
            if i == ref_ch:
                txt = "%s（参考）" % name
            elif s:
                txt = "%s：Δx %.2f / Δy %.2f px" % (name, s[0], s[1])
            else:
                txt = "%s：未算" % name
            lab = QLabel(txt)
            lab.setObjectName("muted")
            lab.setWordWrap(True)
            h.addWidget(lab, 1)
            if i != ref_ch:
                m = manual.get(str(i)) or (0.0, 0.0)
                for _k, val in (("dx", float(m[0])), ("dy", float(m[1]))):
                    sp = QDoubleSpinBox()
                    sp.setObjectName("field")
                    sp.setRange(-50.0, 50.0)
                    sp.setSingleStep(0.5)
                    sp.setDecimals(2)
                    sp.setFixedWidth(72)
                    sp.setValue(val)
                    sp.setToolTip("手动微调（px）：配准不理想时在这里补")
                    sp.valueChanged.connect(lambda _v, idx=i: self.on_reg_manual(idx))
                    h.addWidget(sp)
            self.reg_rows.addWidget(row)

    def _proc_rebuild(self, it, keep_params=True):
        """按界面开关重建 `item.process`（顺序固定：配准 → 扣背景 → 漂移）。"""
        old = {s.kind: dict(s.params or {}) for s in (getattr(it, "process", None) or [])}
        steps = []
        if self.sw_reg.isChecked() and len(getattr(it, "channels", []) or []) > 1:
            p = old.get("register", {}) if keep_params else {}
            p["ref_ch"] = int(self.cb_reg_ref.currentIndex())
            steps.append(ProcessStep("register", p))
        if self.sw_bg.isChecked():
            p = old.get("bg", {}) if keep_params else {}
            p["mode"] = "const" if self.cb_bg_mode.currentIndex() == 1 else "percentile"
            p["p"] = float(self.sp_bg_p.value())
            p["c"] = float(self.sp_bg_c.value())
            steps.append(ProcessStep("bg", p))
        if self.sw_drift.isChecked() and int(it.frames or 1) > 1:
            p = old.get("drift", {}) if keep_params else {}
            p["ref_frame"] = int(self.sp_drift_ref.value()) - 1
            steps.append(ProcessStep("drift", p))
        # 去卷积已按用户要求移除（2026-09-22）：老工程里的 deconvolve 步骤到这里被丢掉
        it.process = steps
        # 换链必须把**处理结果**丢掉：只清 key 的话，链被清空时会落到
        # load_stack 的"手工缓存"分支上，界面继续显示处理过的像素（实测踩过）。
        # 链前数据 `_raw_cache` 留着，重算不用再解码原文件。
        it._cache = None
        it._cache_key = None
        return steps

    def on_proc_changed(self, *_a):
        it = self.cur_item
        if it is None or getattr(self, "proc_tool", None) is None:
            return
        self._commit("改处理链")
        self._proc_rebuild(it)
        self._sync_process_tool()
        self._planes_key = None
        self._base_key = None
        self.refresh_preview()
        self._refresh_thumb_later()
        self.refresh_manifest()
        self.lbl_status.setText(self.lbl_proc.text())

    def on_reg_manual(self, ch_index):
        """手动微调：直接读界面上那两个框的值写进处理链。"""
        it = self.cur_item
        reg = self._proc_step(it, "register") if it else None
        if reg is None:
            return
        row = self.reg_rows.itemAt(ch_index)
        if row is None or row.widget() is None:
            return
        spins = row.widget().findChildren(QDoubleSpinBox)
        if len(spins) < 2:
            return
        m = dict(reg.params.get("manual") or {})
        m[str(ch_index)] = [float(spins[0].value()), float(spins[1].value())]
        reg.params["manual"] = m
        it._cache_key = None
        self._planes_key = None
        self.refresh_preview()
        self._refresh_thumb_later()

    def recalc_register(self):
        """重新算通道位移（后台线程；算完写进处理链）。"""
        it = self.cur_item
        if it is None:
            return
        self._proc_rebuild(it)
        reg = self._proc_step(it, "register")
        if reg is None:
            QMessageBox.information(self, "先打开配准", "先把「通道配准」开关打开。")
            return
        reg.params.pop("shifts", None)
        reg.params.pop("manual", None)
        it._cache_key = None
        self.lbl_status.setText("正在算通道位移（相位相关）…")
        self._run(FnWorker(self._job_register, it), self._on_register_done)

    @staticmethod
    def _job_register(item, report=None):
        """后台：算位移 + 预热整条链（结果进缓存）。"""
        from core import register as reg
        stack = loader.raw_stack(item)
        step = next((s for s in (item.process or []) if s.kind == "register"), None)
        if step is None:
            return {}
        params = step.params
        shifts = reg.channel_shifts(stack, ref_ch=int(params.get("ref_ch", 0) or 0),
                                    frame=int(params.get("frame", 0) or 0))
        params["shifts"] = {str(c): [round(v[0], 4), round(v[1], 4), round(v[2], 4)]
                            for c, v in shifts.items()}
        loader.load_stack(item)
        return params["shifts"]

    def _on_register_done(self, shifts):
        self.progress.setValue(0)
        self._sync_process_tool()
        self._planes_key = None
        self.refresh_preview()
        self._refresh_thumb_later()
        self.lbl_status.setText("通道位移已算好（%d 路）" % len(shifts or {}))

    def recalc_drift(self):
        it = self.cur_item
        if it is None:
            return
        self._proc_rebuild(it)
        if self._proc_step(it, "drift") is None:
            QMessageBox.information(self, "先打开漂移校正",
                                    "先把「时间序列漂移校正」开关打开。")
            return
        it._cache_key = None
        self.lbl_status.setText("正在算逐帧漂移…")
        self._run(FnWorker(self._job_drift, it), self._on_drift_done)

    @staticmethod
    def _job_drift(item, report=None):
        from core import register as reg
        stack = loader.raw_stack(item)
        step = next((s for s in (item.process or []) if s.kind == "drift"), None)
        if step is None:
            return {}
        params = step.params
        shifts = reg.drift_shifts(stack, ref_frame=int(params.get("ref_frame", 0) or 0),
                                  ch=int(params.get("ch", 0) or 0), report=report)
        params["shifts"] = {str(f): [round(v[0], 4), round(v[1], 4), round(v[2], 4)]
                            for f, v in shifts.items()}
        loader.load_stack(item)
        return params["shifts"]

    def _on_drift_done(self, shifts):
        self.progress.setValue(0)
        self._sync_process_tool()
        self._planes_key = None
        self.refresh_preview()
        self._refresh_thumb_later()
        self.lbl_status.setText("逐帧漂移已算好（%d 帧）" % len(shifts or {}))

    def save_overlay_check(self):
        """参考通道绿 + 目标通道品红叠一张：有彩边就是没对齐（规格书 4.13.1）。"""
        it = self.cur_item
        chans = list(getattr(it, "channels", []) or []) if it else []
        if len(chans) < 2:
            QMessageBox.information(self, "需要两个通道", "叠加检查图至少要两个通道。")
            return
        try:
            stack = loader.load_stack(it)
            f = max(0, min(self.frame, stack.shape[0] - 1))
            reg = self._proc_step(it, "register")
            ref_ch = int((reg.params or {}).get("ref_ch", 0) if reg else 0)
            other = 1 if ref_ch == 0 else 0

            def norm(a):
                top = max(1e-6, float(np.percentile(a, 99.5)))
                return (np.clip(a / top, 0, 1) * 255).astype(np.uint8)

            g = norm(np.asarray(stack[f, ref_ch], np.float32))
            m = norm(np.asarray(stack[f, other], np.float32))
            rgb = np.zeros(g.shape + (3,), np.uint8)
            rgb[..., 1] = g
            rgb[..., 0] = m
            rgb[..., 2] = m
            out_dir = self.settings.out_dir or paths.OUTPUT_DIR
            os.makedirs(out_dir, exist_ok=True)
            out = os.path.join(out_dir, "%s_叠加检查.png" % os.path.splitext(it.name)[0])
            from PIL import Image as PILImage
            PILImage.fromarray(rgb).save(out)
            self.lbl_status.setText("叠加检查图：%s（有彩边 = 没对齐）" % out)
        except Exception as exc:                     # noqa: BLE001
            QMessageBox.warning(self, "生成失败", str(exc))

    def set_view_mode(self, mode):
        self.view_mode = mode
        self.btn_view_full.setChecked(mode == "full")
        self.btn_view_crop.setChecked(mode == "crop")
        self.btn_hide_box.setEnabled(mode == "full")     # 裁剪结果视图里没有框可隐藏
        self.canvas.set_show_box(mode == "full" and not self.btn_hide_box.isChecked())
        if mode == "crop":
            self.canvas.set_zoom(1.0)          # 成品图永远整张显示
        self.refresh_preview()

    def on_hide_box(self, on):
        """只看图：不画裁剪框（也不压暗四周），方便观察和加 ROI。"""
        self.settings.show_box = not bool(on)
        if self.view_mode == "full":
            self.canvas.set_show_box(not bool(on))
        self.lbl_status.setText(
            "已隐藏裁剪框：整图观察，图上可以直接画 ROI（再点一下恢复）" if on
            else "裁剪框已恢复")
    def on_box_changed(self):
        if not self.cur_group or not self.cur_item:
            return
        box = self.canvas.box()
        if self.cur_group.sync:
            self.cur_group.box = box
        else:
            self.cur_group.boxes[self.cur_item.path] = box
        self._update_px_label()

    def on_box_committed(self):
        self._mark_dirty()                 # 快照在 on_box_drag_started 里取过了
        self.on_box_changed()
        if self.view_mode == "crop":
            self.refresh_preview()

    def on_box_drag_started(self):
        """按下的瞬间记一份裁剪框快照 —— 等松手再记就成"改之后"了。"""
        self._commit("移动/缩放裁剪框")

    def apply_box_to_all(self):
        """一键把当前视野框的大小套到所有组（位置各组自己保留）。"""
        """把当前组的裁剪框大小套到所有组；位置各组自己调整（放不下就靠边）。"""
        if not self.cur_group or not self.cur_item:
            return
        self._commit("一键套裁剪框到所有组")
        w = float(self.settings.crop_w)
        h = float(self.settings.crop_h)
        for g in self.groups:
            f = g.images[0].field_um() if g.images else 0.0
            ox = float(g.box.get("x", 0.0))
            oy = float(g.box.get("y", 0.0))
            if f > 0:
                ox = min(max(0.0, ox), max(0.0, f - w))
                oy = min(max(0.0, oy), max(0.0, f - h))
            else:
                ox = oy = 0.0
            g.box = dict(x=ox, y=oy, w=w, h=h)
            for it in g.images:                 # 关掉同步的图也一起换尺寸，位置保留
                b = g.boxes.get(it.path)
                if b:
                    g.boxes[it.path] = dict(x=float(b.get("x", 0.0)),
                                            y=float(b.get("y", 0.0)), w=w, h=h)
        self.canvas.set_box(self.cur_group.box_for(self.cur_item))
        self.refresh_preview()
        self.refresh_manifest()
        self.lbl_status.setText("已把 %.10g × %.10g µm 套到 %d 个组"
                                % (w, h, len(self.groups)))

    def on_line_mode(self, on):
        self.canvas.set_line_mode(on)
        if on:
            self.canvas.clear_line()
            self.lbl_line.setText("在图上对着标尺点两个点")
        else:
            self.lbl_line.setText("还没画线")

    # ------------------------------------------------------------ 识别结果可视化
    def _detect_info(self, it):
        """把 bar.detect_umpp 的结果翻成画布能画的点（规格书 5.4.6）。

        返回 {p0, p1, label, conf, value_um, length_px} 或 None。
        p0/p1 是**原图**归一化坐标；竖标尺的 bar 在 _untranspose 里已经换回原图坐标系，
        但 x0==x1、长度记在 length 上，所以这里按 orientation 拼两个端点。
        """
        det = getattr(it, "detect", None) if it else None
        if not det:
            return None
        bar = det.get("bar")
        if not bar or it.width <= 0 or it.height <= 0:
            return None
        length = float(bar.get("length") or 0.0)
        if length <= 0:
            return None
        p0, p1 = self._bar_points(it, bar, det.get("orientation"))
        text = det.get("text") or ""
        if det.get("ok"):
            label = "%s → %.4g µm/px" % (text or ("%.4g µm" % det.get("value_um", 0)),
                                         det.get("umpp", 0.0))
            conf = {"high": "高", "mid": "中"}.get(det.get("confidence"), "低")
        else:                                    # 找到了线但没读到数字：也得让用户看见线
            label = text or "找到标尺线"
            conf = "低"
        alts = []
        if bar_mod.ambiguous(det):               # 候选差太多：其它几条也画出来（5.4.5）
            for c in det.get("candidates") or []:
                if c.get("bar") is None or abs(c.get("umpp", 0) - det.get("umpp", 0)) < 1e-9:
                    continue
                a0, a1 = self._bar_points(it, c["bar"], det.get("orientation"))
                alts.append(dict(p0=a0, p1=a1))
        return dict(p0=p0, p1=p1, label=label, conf=conf, value_um=det.get("value_um", 0.0),
                    length_px=length, alts=alts)

    @staticmethod
    def _bar_points(it, bar, orientation):
        """标尺条 → 原图归一化端点（竖标尺的 x0==x1、长度记在 length 上）。"""
        length = float(bar.get("length") or 0.0)
        if orientation == "v":
            x = (float(bar["x0"]) + 0.5) / it.width
            return ((x, float(bar["y"]) / it.height),
                    (x, (float(bar["y"]) + length) / it.height))
        y = (float(bar["y"]) + 0.5) / it.height
        return ((float(bar["x0"]) / it.width, y), (float(bar["x1"]) / it.width, y))

    def on_detect_fix(self):
        """「不对，手动框」：进画线模式，并把识别到的端点预填进去，用户微调即可。"""
        it = self.cur_item
        info = self._detect_info(it)
        if not info:
            QMessageBox.information(self, "没有可预填的线", "这张图还没有识别结果。")
            return
        self.canvas.set_zoom(1.0)                # 先复位：保证端点不会跑到窗口外
        self.refresh_preview()                   # 立刻重算，_pix_um 才是最新的
        if not self.btn_line.isChecked():
            self.btn_line.setChecked(True)       # 触发 on_line_mode(True)
        else:
            self.on_line_mode(True)
        a = self.canvas.norm_to_view(*info["p0"])
        b = self.canvas.norm_to_view(*info["p1"])
        it.line_px = info["length_px"]
        self.canvas.set_line(a, b, info["length_px"])
        if info["value_um"] > 0:
            self.field_line_um.setValue(info["value_um"])
        self.lbl_line.setText("识别线长 %.1f 像素 —— 拖两端微调，或直接点两个点重画"
                              % info["length_px"])

    def on_line_measured(self, x0, y0, x1, y1):
        """画完线：换算成原图像素长度显示出来。"""
        it = self.cur_item
        if not it:
            return
        used = getattr(self, "_used_rect", (0.0, 0.0, 1.0, 1.0))
        ax = (used[0] + x0 * (used[2] - used[0])) * it.width
        ay = (used[1] + y0 * (used[3] - used[1])) * it.height
        bx = (used[0] + x1 * (used[2] - used[0])) * it.width
        by = (used[1] + y1 * (used[3] - used[1])) * it.height
        if getattr(self, "_ortho_win", None) is not None:
            # 这条线是给正交视图当取样线用的（P1-5），不是标定
            self._ortho_win.set_line_px(ax, ay, bx, by)
            self.canvas.set_line_mode(False)
            self._ortho_win = None
            self.lbl_status.setText("取样线已更新，正交视图跟着变")
            return
        d = math.hypot(bx - ax, by - ay)
        it.line_px = d
        self.canvas._line_px = d
        self.canvas.update()
        self.lbl_line.setText("线长 %.1f 像素" % d)

    def start_ortho_pick(self, ortho_win):
        """让主图进入"画取样线"状态（线画完就交给正交窗口）。"""
        if self.cur_item is None:
            return
        if int(getattr(self.cur_item, "z_count", 1) or 1) <= 1:
            QMessageBox.information(self, "只有一层 Z",
                                    "这张图没有多层 Z，出不了 XZ / YZ 剖面。")
            return
        self._ortho_win = ortho_win
        self.canvas.set_zoom(1.0)
        self.refresh_preview()
        self.canvas.set_line_mode(True)
        self.lbl_status.setText("在主图上拉一条直线当取样线（横线 = XZ，竖线 = YZ）")

    def open_ortho(self):
        """打开（或激活）正交视图窗口。"""
        if self.cur_item is None:
            return
        from ui.ortho import OrthoWindow
        w = getattr(self, "_ortho_window", None)
        if w is None:
            w = OrthoWindow(self)
            self._ortho_window = w
        w.sync_channels()
        w.show()
        w.raise_()
        w.activateWindow()
        w.refresh()

    def apply_line_calib(self, all_groups=False):
        """按"线长 px ↔ 输入的 µm"算出 µm/px 并应用（只作用于图片格式）。"""
        it = self.cur_item
        if not it:
            return
        d = float(getattr(it, "line_px", 0.0) or 0.0)
        um = float(self.field_line_um.value())
        if d <= 0 or um <= 0:
            QMessageBox.information(self, "还差一点",
                                    "先在图上对着标尺画一条线，\n再填这条线代表多少微米。")
            return
        umpp = um / d
        if all_groups:
            targets = [x for g in self.groups for x in g.images if is_image_file(x.path)]
        else:
            targets = ([x for x in self.cur_group.images if is_image_file(x.path)]
                       if self.cur_group else [])
        if not targets:
            QMessageBox.information(
                self, "没有可应用的图",
                "这个画线标定只对图片格式生效（PNG / TIFF / JPG / BMP）；\n"
                "OIB / CZI / LIF 这些下机文件本身自带标定。")
            return
        self._commit("手动画线标定")           # 快照要取"改之前"的状态
        for x in targets:
            x.umpp = umpp
            x.calib = "手动画线标定"
            x.detect = None            # 人工线是最终口径，别再把识别线留在图上
        self.settings.line_um = um
        self._regroup()
        self.refresh_groups()
        self.refresh_strip()
        self.refresh_preview()
        self.refresh_calib()
        self.refresh_manifest()
        self.lbl_status.setText("标定 %.5f µm/px，已应用到 %d 张图" % (umpp, len(targets)))

    def _update_px_label(self):
        it = self.cur_item
        if not it or it.umpp <= 0:
            self.lbl_px.setText("")
            self.lbl_size.setText("—")
            return
        box = self.cur_group.box_for(it)
        self.lbl_px.setText("裁剪 ≈ %d × %d px"
                            % (round(box["w"] / it.umpp), round(box["h"] / it.umpp)))
        self.lbl_size.setText("%.1f × %.1f µm" % (box["w"], box["h"]))

    def _schedule_preview(self):
        """缩放/平移时不要每帧都重算，等手停下来再算一次。"""
        if self.view_mode != "full":
            return
        if SlideAnim.busy():
            # 模块正在滑：这会儿重算会重画一次画布，正好压到动画收尾上
            self._preview_pending = True
            return
        self._preview_timer.start()

    def after_slide(self):
        """模块滑完了：把滑动期间挂起的预览刷新补上。"""
        if getattr(self, "_preview_pending", False):
            self._preview_pending = False
            self._preview_timer.start()

    def refresh_preview(self):
        it = self.cur_item
        if it is None:
            self.canvas.set_image(np.zeros((8, 8, 3), np.uint8))
            self.lbl_px.setText("")
            return
        if getattr(it, "missing", False):
            # 工程里记着、但磁盘上找不到：显示占位，别让预览线程去撞坏路径
            self.canvas.set_show_box(False)
            self.canvas.set_detect(None)
            self.canvas.clear_bar_zones()
            self.canvas.set_overlay(None)
            self.canvas.set_image(np.full((8, 8, 3), 40, np.uint8))
            self.lbl_px.setText("")
            self.lbl_status.setText("原文件不存在：%s —— 右键这张缩略图可重新指定位置"
                                    % (it.file_path or it.path))
            return
        try:
            if self.view_mode == "full":
                self._preview_full(it)
            else:
                self._preview_crop(it)
        except Exception as exc:                 # noqa: BLE001
            traceback.print_exc()
            self.lbl_status.setText("预览出错：%s" % exc)
        self._update_px_label()

    def _preview_full(self, it):
        """原图显示：按可见范围一次性重采样，保证清晰。"""
        # 开着 Z 投影时换"替身 item"：它的第 0 帧就是投影结果，
        # 下面的重采样/合成/锐化一行都不用改（清晰度是冻结的，见规格书 §2.7）
        it = render.view_item(it, self.frame)
        frame = 0 if it is not self.cur_item else self.frame
        dpr = float(self.canvas.devicePixelRatioF() or 1.0)
        tw = max(64, int(round(self.canvas.width() * dpr)))
        th = max(64, int(round(self.canvas.height() * dpr)))
        field_w = it.field_um() or float(it.width)
        field_h = (it.height * it.umpp) if it.umpp > 0 else field_w
        self.canvas.set_field(field_w, field_h)
        # 整图小图（既做放大时的底图，也给缩略图复用），按图片缓存一次
        base_key = (it.path, frame)
        if base_key != getattr(self, "_base_key", None) or self._base_planes is None:
            side = 900.0
            if it.width >= it.height:
                bw, bh = int(side), max(48, int(round(side * it.height / max(1, it.width))))
            else:
                bh, bw = int(side), max(48, int(round(side * it.width / max(1, it.height))))
            self._base_planes, _u = render.preview_for_view(
                it, frame, (0.0, 0.0, 1.0, 1.0), (bw, bh))
            self._base_key = base_key
            self._base_rgb = None
            self._base_stale = True
        # ① 上层：当前可见区域的高清预览（缩放 1x 时它本来就铺满，不必做底图）
        rect = self.canvas.visible_rect_norm()
        key = (it.path, frame, tuple(round(v, 4) for v in rect), tw, th)
        if key != getattr(self, "_planes_key", None):
            self._planes, used = render.preview_for_view(it, frame, rect, (tw, th))
            self._used_rect = used
            self._planes_key = key
        else:
            # 缓存命中时也要把 _used_rect 复位成"这一屏覆盖的范围"。
            # 裁剪结果视图会把 _used_rect 改成裁剪框的范围（那一屏画 ROI 要用），
            # 切回原图时如果这里不重置，画布就以为图只覆盖中间那一小块 ——
            # 结果是裁剪框四周留黑，滚一下滚轮才对（2026-09-26 用户实测反馈）。
            self._used_rect = rect
        rgb = render.compose(self._planes, it.channels,
                             render.ranges_for(it, frame),
                             mode=self.settings.merge_mode)
        # 整图挤进屏幕时补一点锐度（只影响屏幕观感；导出数据不动）
        used0 = getattr(self, "_used_rect", rect)
        shrink = (used0[2] - used0[0]) * it.width / float(max(1, tw))
        if shrink >= 1.6:
            rgb = render.sharpen_display(rgb)
        self.canvas.set_show_box(bool(getattr(self.settings, "show_box", True)))
        self.canvas.set_lock(self.chk_lock.isChecked())
        used = getattr(self, "_used_rect", rect)
        # 用"实际取到的像素范围"来定位，避免细节层和底图错开一个像素（看着像抖一下）
        self.canvas.set_pix_um(used[0] * field_w, used[1] * field_h,
                               (used[2] - used[0]) * field_w,
                               (used[3] - used[1]) * field_h)
        self.canvas.set_overlay(None)
        self.canvas.clear_bar_zones()
        self.canvas.set_image(rgb, dpr)
        # ② 底层：整图预览，只在放大时才需要（铺满用，防黑屏/跳动）
        if self.canvas.zoom() > 1.0001:
            if self._base_stale or getattr(self, "_base_rgb", None) is None:
                self._base_rgb = render.compose(self._base_planes, it.channels,
                                                render.ranges_for(it, frame),
                                                mode=self.settings.merge_mode)
                self._base_stale = False
            self.canvas.set_base_image(self._base_rgb, dpr, (0.0, 0.0, field_w, field_h))
        else:
            self.canvas.set_base_image(None)
        self.canvas.set_detect(self._detect_info(it))   # 画"识别到哪根线"（5.4.6）
        self.canvas.set_box(self.cur_group.box_for(it))
        # ROI 叠加只画在"原图显示"里（裁剪结果视图是成品预览，坐标基准不一样）
        self.canvas.set_rois(self._roi_shapes())
        self.canvas.set_roi_sel(getattr(self, "_roi_sel", ""))

    def _preview_crop(self, it):
        """裁剪结果：成品图 + 标尺叠加层（标尺可拖动）。"""
        it = render.view_item(it, self.frame)     # 投影模式下换成替身（帧归 0）
        self.canvas.set_zoom(1.0)
        st = self._st_for_group()
        stack = loader.load_stack(it)
        fr = 0 if it is not self.cur_item else max(0, min(self.frame, stack.shape[0] - 1))
        rect = render.crop_rect(it, self.cur_group.box_for(it), st)
        if rect is None:
            self.canvas.set_image(np.zeros((8, 8, 3), np.uint8))
            self.canvas.set_overlay(None)
            self.canvas.clear_bar_zones()
            self.lbl_px.setText("视野不足，已按设置跳过这张")
            return
        data = render.crop_planes(stack[fr], rect)
        # 成品图永远整张显示，所以先缩到显示尺寸再合成：大裁剪框能省几十倍时间
        dpr = float(self.canvas.devicePixelRatioF() or 1.0)
        side = max(64, int(round(max(self.canvas.width(), self.canvas.height()) * dpr)))
        ph, pw = data.shape[-2], data.shape[-1]
        if max(ph, pw) > side * 1.2:
            k = max(2, int(np.ceil(max(ph, pw) / float(side))))
            from PIL import Image as PILImage
            tw2 = max(1, int(round(pw / float(k))))
            th2 = max(1, int(round(ph / float(k))))
            data = np.stack([np.asarray(PILImage.fromarray(data[c]).resize(
                (tw2, th2), PILImage.LANCZOS)) for c in range(data.shape[0])])
        rgb = render.compose(data, it.channels, render.ranges_for(it, fr),
                             mode=self.settings.merge_mode)
        h, w = rgb.shape[:2]
        if max(h, w) < 480:                      # 小图放大看，放大后再画标尺
            k = max(1, int(np.ceil(480.0 / max(h, w))))
            from PIL import Image as PILImage
            rgb = np.asarray(PILImage.fromarray(rgb).resize((w * k, h * k), PILImage.LANCZOS))
        disp_h, disp_w = rgb.shape[:2]
        crop_um = (rect[2] * it.umpp, rect[3] * it.umpp)
        # 显示分辨率 = 裁剪框的物理宽度 / 实际显示的像素宽度。
        # 老写法 `it.umpp / (disp_w / w)` 只算了"小图放大"那一步，漏掉了
        # 前面"大裁剪先缩到画布尺寸"的缩小 —— 只要裁剪像素被缩过，标尺就会
        # 按缩小倍数画长（实测 100 µm 的画面里 10 µm 标尺画成了 50%）。
        umpp_disp = (crop_um[0] / disp_w) if (it.umpp > 0 and disp_w > 0) else 0.0
        self.canvas.set_show_box(False)
        self.canvas.set_base_image(None)
        self.canvas.set_field(crop_um[0], crop_um[1])
        self.canvas.set_pix_um(0.0, 0.0, crop_um[0], crop_um[1])
        # 裁剪结果视图里画布坐标是"裁剪框局部"，而 ROI 存的是整帧归一化 ——
        # 两个基准不一样，所以这里不画 ROI（画了就会跑到别处去）；
        # 但要把 _used_rect 更新成"裁剪框在整帧里的范围"，这样在这一屏里
        # 新画的 ROI 换算回整帧坐标才是对的（历史 bug：这里没更新，坐标会错位）。
        it_w = max(1, int(it.width))
        it_h = max(1, int(it.height))
        self._used_rect = (rect[0] / float(it_w), rect[1] / float(it_h),
                           (rect[0] + rect[2]) / float(it_w),
                           (rect[1] + rect[3]) / float(it_h))
        self.canvas.set_rois([])
        self.canvas.set_roi_sel("")
        self.canvas.set_image(rgb)
        self.canvas.set_overlay(None)
        self.canvas.clear_bar_zones()
        self.canvas.set_detect(None)             # 裁剪结果视图里不画识别线
        self._last_bar_anchor = None
        if st.bar_enabled and umpp_disp > 0:
            bar_um = bar_mod.bar_length_for(disp_w, umpp_disp, st)
            layer, _len, lay = bar_mod.bar_layer_only(disp_w, disp_h, umpp_disp, st,
                                                      bar_um, color=None, probe=rgb)
            self.canvas.set_overlay(np.asarray(layer))
            k = self.canvas.disp_scale(disp_w)    # 预览图像素 → 控件像素
            self._last_bar_anchor = ((lay["x0"] + lay["x1"]) / 2.0 / disp_w,
                                     lay["y"] / disp_h)
            # 线的命中区收紧：只包住横条本身，别把上方紧贴的文字也圈进来
            line_h = max(20.0, lay["thick"] * k * 2.0 + 8.0)
            bar_rect = QRect(int(lay["x0"] * k) - 6, int(lay["y"] * k - line_h / 2.0),
                             int((lay["x1"] - lay["x0"]) * k) + 12, int(line_h))
            if lay["label"]:
                gap = int(st.bar_text_offset or max(2, round(lay["font_size"] * 0.25)))
                ty = lay["y"] - gap - lay["th"] - 1
                if ty < 1:
                    ty = lay["y"] + lay["tick"] + gap
                tx = lay["x0"] + (lay["x1"] - lay["x0"]) / 2.0 - lay["tw"] / 2.0
                text_rect = QRect(int(tx * k) - 6, int(ty * k) - 6, int(lay["tw"] * k) + 12,
                                  int(lay["th"] * k) + 12)
                text_center = ((tx + lay["tw"] / 2.0) / disp_w, (ty + lay["th"] / 2.0) / disp_h)
            else:
                text_rect, text_center = None, None
            self.canvas.set_bar_zones(bar_rect, text_rect, tuple(self._last_bar_anchor),
                                      text_center, (disp_w * k, disp_h * k))
        self.lbl_px.setText("成品 %d × %d px%s" % (rect[2], rect[3],
                                                  "（显示已放大）" if disp_w != w else ""))

    def refresh_channels(self):
        while self.chan_layout.count():
            item = self.chan_layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        if getattr(self, "range_tool", None) is None:
            return
        if not self.cur_item:
            self.range_tool.setVisible(False)
            self._chan_drawn = None
            return
        self._chan_rows = []
        self._chan_ui = {}
        chans = self.cur_item.channels
        if chans and all(c.role == "rgb" for c in chans):
            lab = QLabel("整图（已经是彩色图，直接裁剪输出）")
            lab.setObjectName("muted")
            lab.setWordWrap(True)
            self.chan_layout.addWidget(lab)
            self.range_tool.setVisible(False)
            self._chan_drawn = self._chan_sig(self.cur_item)
            QTimer.singleShot(0, self._settle_cards)
            return
        self._sync_range_tool()
        for ch in chans:
            self.chan_layout.addWidget(self._chan_row(ch))
        QTimer.singleShot(0, self._settle_cards)       # 通道数变了，卡片高度要重新量
        self._chan_drawn = self._chan_sig(self.cur_item)

    @staticmethod
    def _chan_sig(it):
        """通道表的"体格签名"：只用来判断解码后 loader 有没有把通道表改掉。"""
        if it is None:
            return None
        return tuple((int(getattr(c, "index", i)), c.name or "", c.role,
                      bool(getattr(c, "visible", True)))
                     for i, c in enumerate(getattr(it, "channels", None) or []))

    def _settle_channels(self, it):
        """解码之后再补刷一次通道卡。

        历史 bug（用户实测反馈）：蔡司 Airyscan 的"原始版 + 处理版"两层、
        以及只录了一路的空 Bright 通道，都要**看了数据**才知道该合并/隐藏 ——
        这些修正只发生在 `loader.load_stack()` 第一次解码时（core/loader.py）。
        可界面上的通道卡是在解码前画的（`select_item` 里 refresh_channels 排在
        refresh_preview 前面），于是导入 Snap-14700 这类文件后右栏一直挂着两路，
        缩略图与主图却已经是合并后的一路。这里比对签名补刷一次。
        """
        if it is None or it is not self.cur_item:
            return False
        if self._chan_sig(it) == getattr(self, "_chan_drawn", None):
            return False
        self.refresh_channels()
        self.refresh_strip()                 # 缩略图也按新通道重出
        # 通道表是所有"按通道算"的面板的数据源，一起补刷：否则顶部那行还写着
        # "2 通道"、处理卡的参考通道还挂着已经不存在的 FITC-T1、导出清单的
        # 原始位深文件数也还是按旧通道数算的（都是用户能一眼看见的地方）。
        self._sync_process_tool()
        self.refresh_rois()
        self.refresh_calib()
        self.refresh_manifest()
        return True

    # ------------------------------------------------------------ 逐帧归一化（P0-4）
    def _sync_range_tool(self):
        """把逐帧归一化控件对齐到当前图的状态（单帧图不显示）。"""
        it = self.cur_item
        if getattr(self, "range_tool", None) is None:
            return
        if it is None:
            self.range_tool.setVisible(False)
            return
        show = int(getattr(it, "frames", 1) or 1) > 1
        self.range_tool.setVisible(show)
        if not show:
            return
        mode = getattr(it, "range_mode", "global") or "global"
        for w, val in ((self.cb_range_mode, {"global": 0, "per_frame": 1, "ref": 2}.get(mode, 0)),
                       (self.ed_p_lo, float(getattr(it, "range_p_lo", 55.0) or 55.0)),
                       (self.ed_p_hi, float(getattr(it, "range_p_hi", 99.8) or 99.8))):
            w.blockSignals(True)
            if isinstance(w, QComboBox):
                w.setCurrentIndex(int(val))
            else:
                w.setValue(val)
            w.blockSignals(False)
        self.sp_ref.blockSignals(True)
        self.sp_ref.setRange(1, max(1, int(it.frames)))
        self.sp_ref.setValue(min(max(1, int(getattr(it, "ref_frame", 0) or 0) + 1), it.frames))
        self.sp_ref.blockSignals(False)
        self.sp_ref.setEnabled(mode == "ref")
        if mode == "per_frame":
            self.lbl_range_warn.setText("逐帧归一化会消除强度随时间变化的真实信号，"
                                        "定量分析时请勿启用。")
        elif mode == "ref":
            self.lbl_range_warn.setText("以参考帧的窗口宽度为准逐帧平移：保留相对强弱，"
                                        "只修正整体变暗。")
        else:
            self.lbl_range_warn.setText("全部帧共用同一套黑/白点（现状）。")

    def on_range_mode(self, idx):
        it = self.cur_item
        if it is None:
            return
        self._commit("改区间模式")
        it.range_mode = ["global", "per_frame", "ref"][int(idx)]
        it._frame_ranges = None                 # 换模式 → 缓存失效
        self._sync_range_tool()
        self._ensure_frame_ranges()

    def on_range_pct(self, *_a):
        it = self.cur_item
        if it is None:
            return
        self._commit("改归一化分位", coalesce=1.0)
        it.range_p_lo = float(self.ed_p_lo.value() or 55.0)
        it.range_p_hi = float(self.ed_p_hi.value() or 99.8)
        it._frame_ranges = None
        self._ensure_frame_ranges()

    def on_range_ref(self, value):
        it = self.cur_item
        if it is None:
            return
        self._commit("改参考帧")
        it.ref_frame = max(0, int(value) - 1)
        it._frame_ranges = None
        self._ensure_frame_ranges()

    def _ensure_frame_ranges(self):
        """按需在后台算逐帧区间；算之前先用统一区间显示（不会闪）。"""
        it = self.cur_item
        if it is None:
            return
        if (getattr(it, "range_mode", "global") or "global") == "global":
            it._frame_ranges = None
            self.refresh_preview()
            return
        if loader.has_frame_ranges(it):
            self.refresh_preview()
            self._refresh_thumb_later()
            return
        # 当前这一帧先同步算出来（一帧的分位数很快）——用户立刻看到变化，
        # 剩下的帧交给后台线程补全。
        try:
            loader.compute_frame_ranges(it, only_frame=self.frame)
            self.refresh_preview()
        except Exception:                        # noqa: BLE001
            pass
        self.lbl_status.setText("正在算逐帧显示区间…")
        self._run(FnWorker(loader.compute_frame_ranges, it), self._on_frame_ranges)

    def _on_frame_ranges(self, result):
        self.progress.setValue(0)
        it = self.cur_item
        self.refresh_preview()
        self._refresh_thumb_later()
        n = len(result or {})
        self.lbl_status.setText("逐帧显示区间已算好（%d 帧×通道）" % n)
        if it is not None and n:
            self._mark_dirty()

    def _chan_row(self, ch):
        f = QFrame()
        f.setObjectName("chan")
        lay = QVBoxLayout(f)
        lay.setContentsMargins(11, 9, 11, 7)
        lay.setSpacing(3)
        # 第一行：色点 + 通道名 + 开关
        top = QHBoxLayout()
        top.setSpacing(8)
        dot = ClickLabel()
        dot.setObjectName("dot")
        dot.setFixedSize(12, 12)
        dot.setStyleSheet("background:rgb(%d,%d,%d); border-radius:6px;"
                          % tuple(int(v) for v in ch.color))
        dot.setCursor(Qt.PointingHandCursor)
        dot.setToolTip("点一下改这个通道的颜色（选「灰底」= 当明场底图）")
        dot.clicked.connect(lambda c=ch: self.pick_channel_color(c))
        wave = "%d→%d" % (ch.ex, ch.em) if (ch.ex and ch.em) else ""
        title = " ".join(x for x in (ch.name or ("CH%d" % (ch.index + 1)), wave,
                                     color_name(ch.color)) if x)
        name = QLabel()
        name.setToolTip(title + "　（点左边的色点改颜色）")
        name.setMinimumWidth(30)
        name.setText(name.fontMetrics().elidedText(title, Qt.ElideRight, 200))
        sw = FlipSwitch()
        sw.setChecked(ch.visible)
        sw.setToolTip("这个通道参不参与合成")
        sw.toggled.connect(lambda v, c=ch: self.set_channel_visible(c, v))
        more = BrutalButton("⋯", compact=True)
        more.setFixedWidth(30)
        more.setToolTip("把这一路的区间 / 配色批量套到别的图；复制、粘贴、重置")
        more.clicked.connect(lambda _ck=False, c=ch: self.channel_menu(c))
        top.addWidget(dot)
        top.addWidget(name)
        top.addStretch(1)
        top.addWidget(more)
        top.addWidget(sw)
        lay.addLayout(top)
        # 第二行：双端滑条（左黑右白）
        slider = RangeSlider()
        vmax = int(ch.vmax or max(ch.white, 255) or 255)
        slider.setRange(0, max(16, int(vmax * 1.05)))
        slider.setValues(ch.black, ch.white)
        slider.valuesChanged.connect(lambda lo, hi, c=ch: self.on_channel_slider(c, lo, hi))
        lay.addWidget(slider)
        # 第三行：黑 …… 白
        bl = QHBoxLayout()
        bl.setSpacing(4)
        spins = {}
        for text, attr, align in (("黑", "black", Qt.AlignLeft), ("白", "white", Qt.AlignRight)):
            sp = QSpinBox()
            sp.setObjectName("val")
            sp.setRange(0, 65535)
            sp.setPrefix(text + " ")
            sp.setAlignment(align)
            sp.setFixedWidth(74)
            sp.setToolTip("也可以直接敲数值")
            sp.setValue(int(getattr(ch, attr)))
            sp.valueChanged.connect(lambda v, c=ch, a=attr: self.on_channel_spin(c, a, v))
            spins[attr] = sp
        bl.addWidget(spins["black"])
        bl.addStretch(1)
        bl.addWidget(spins["white"])
        lay.addLayout(bl)
        self._chan_ui[ch.index] = dict(slider=slider, black=spins["black"],
                                       white=spins["white"], dot=dot)
        return f

    def on_channel_color(self, ch, index):
        """按颜色表第 index 项改通道颜色（保留给老调用）。"""
        if 0 <= index < len(CHANNEL_COLORS):
            self.apply_channel_color(ch, *CHANNEL_COLORS[index])

    # ------------------------------------------------------------ 通道：批量应用
    def channel_menu(self, ch):
        """通道行右侧 ⋯：批量应用 / 复制粘贴 / 重置（规格书 3.25.2）。"""
        menu = QMenu(self)
        a_grp = menu.addAction("应用到本组所有图")
        a_umpp = menu.addAction("应用到同 µm/px 的所有图")
        a_all = menu.addAction("应用到所有组")
        menu.addSeparator()
        a_cp = menu.addAction("复制本通道设置")
        a_paste = menu.addAction("粘贴到这一张的同通道")
        a_paste.setEnabled(bool(getattr(self, "_clip_channel", None)))
        menu.addSeparator()
        a_reset = menu.addAction("重置为自动区间")
        a_stretch = menu.addAction("拉伸到 1%~99.9% 分位")
        chosen = menu.exec(QCursor.pos())
        if chosen is None:
            return
        if chosen is a_grp:
            self.apply_channel_to(ch, "group")
        elif chosen is a_umpp:
            self.apply_channel_to(ch, "umpp")
        elif chosen is a_all:
            self.apply_channel_to(ch, "all")
        elif chosen is a_cp:
            self._clip_channel = dict(
                index=ch.index, color=tuple(ch.color), role=ch.role,
                black=float(ch.black), white=float(ch.white),
                vmax=float(getattr(ch, "vmax", ch.white) or ch.white))
            self.lbl_status.setText("已复制 %s 的设置（配色 + 区间）" % self._chan_label(ch))
        elif chosen is a_paste:
            self.paste_channel(ch)
        elif chosen is a_reset:
            self.reset_channel_auto(ch)
        elif chosen is a_stretch:
            self.stretch_channel(ch)

    @staticmethod
    def _chan_label(ch) -> str:
        return ch.name or ("CH%d" % (ch.index + 1))

    def _chan_targets(self, ch, scope):
        """按范围挑目标图；返回 (targets, 说明文字)。"""
        if scope == "group":
            return (list(self.cur_group.images) if self.cur_group else []), "本组"
        if scope == "umpp":
            want = round(float(self.cur_item.umpp), 4) if self.cur_item else 0.0
            return ([it for it in self.items if round(float(it.umpp), 4) == want],
                    "同 µm/px 的图")
        return list(self.items), "全部组"

    def apply_channel_to(self, ch, scope):
        """把当前图这一路的配色 + 区间套到别的图（规格书 3.25.2 的匹配规则）。"""
        if self.cur_item is None:
            return
        targets, what = self._chan_targets(ch, scope)
        targets = [it for it in targets if it is not self.cur_item]
        if not targets:
            self.lbl_status.setText("这个范围里没有别的图")
            return
        if scope != "group" and not self._no_save():
            ans = QMessageBox.question(
                self, "跨组应用显示区间",
                "不同图像的信号强度可能不一样，跨组套用显示区间会让部分图过曝或过暗。\n"
                "建议先用「应用到本组所有图」。\n\n还是继续套到%s吗？" % what,
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ans != QMessageBox.Yes:
                return
        self._commit("批量应用通道设置")
        done = skip_role = skip_none = skip_rgb = 0
        for it in targets:
            if getattr(it, "missing", False):
                skip_none += 1
                continue
            if it.channels and all(c.role == "rgb" for c in it.channels):
                skip_rgb += 1                     # 合成彩图的 R/G/B 语义不同，不参与
                continue
            tgt = next((c for c in (it.channels or []) if c.index == ch.index), None)
            if tgt is None:
                skip_none += 1                    # 目标图通道数不够
                continue
            if tgt.role != ch.role:
                skip_role += 1                    # 类型不一致（灰底 vs 荧光）不动
                continue
            tgt.color = tuple(ch.color)
            tgt.black, tgt.white = float(ch.black), float(ch.white)
            tgt.vmax = max(float(getattr(tgt, "vmax", 0.0) or 0.0), float(ch.white))
            done += 1
        self._regroup()
        self.refresh_channels()
        self.refresh_preview()
        self._refresh_thumb_later()
        tail = []
        if skip_role:
            tail.append("%d 张通道类型不一致" % skip_role)
        if skip_rgb:
            tail.append("%d 张是合成彩图" % skip_rgb)
        if skip_none:
            tail.append("%d 张没有这个通道" % skip_none)
        self.lbl_status.setText(
            "已把 %s 的配色 + 区间应用到 %d 张图的 %s%s"
            % (self._chan_label(ch), done, what,
               ("，跳过：" + "、".join(tail)) if tail else ""))

    def paste_channel(self, ch):
        """把复制的通道设置贴到当前图同序号的通道。"""
        src = getattr(self, "_clip_channel", None)
        if not src or self.cur_item is None:
            return
        tgt = next((c for c in (self.cur_item.channels or []) if c.index == ch.index), None)
        if tgt is None:
            self.lbl_status.setText("这张图没有这个通道")
            return
        self._commit("粘贴通道设置")
        tgt.color = tuple(src["color"])
        tgt.role = src["role"]
        tgt.black, tgt.white = float(src["black"]), float(src["white"])
        tgt.vmax = max(float(getattr(tgt, "vmax", 0.0) or 0.0), float(src["white"]))
        self.refresh_channels()
        self.refresh_preview()
        self._refresh_thumb_later()
        self.lbl_status.setText("已粘贴通道设置到 %s" % self._chan_label(tgt))

    def reset_channel_auto(self, ch):
        """把这一路重置回**默认区间 = 该通道数据的实际最小/最大**（2026-09-26 用户口径）。

        想要老那种"拉伸到 1%~99.9 分位"的观感，用 ⋯ 菜单里的另一项（见 channel_menu）。
        """
        it = self.cur_item
        if it is None:
            return
        try:
            stack = loader.load_stack(it)
            rng = loader.estimate_ranges(stack)
            if ch.index >= len(rng):
                return
            lo, hi, top = rng[ch.index]
        except Exception as exc:                 # noqa: BLE001
            self.lbl_status.setText("重置失败：%s" % exc)
            return
        self._commit("重置通道区间")
        if hi > lo:
            ch.black, ch.white = float(lo), float(hi)
        ch.vmax = max(16.0, float(top))
        self.refresh_channels()
        self.refresh_preview()
        self._refresh_thumb_later()
        self.lbl_status.setText("已重置 %s 的显示区间为自动值（%.0f ~ %.0f）"
                                % (self._chan_label(ch), ch.black, ch.white))

    def stretch_channel(self, ch):
        """把这一路拉伸到 1%~99.9 分位（老观感；只在想要更亮更"跳"时用）。"""
        it = self.cur_item
        if it is None:
            return
        try:
            stack = loader.load_stack(it)
            plane = np.asarray(stack[0, ch.index], np.float32)
            lo, hi = float(np.percentile(plane, 1)), float(np.percentile(plane, 99.9))
            top = max(float(np.percentile(plane, 99.99)), float(plane.max()))
        except Exception as exc:                 # noqa: BLE001
            self.lbl_status.setText("拉伸失败：%s" % exc)
            return
        self._commit("拉伸通道区间")
        if hi > lo:
            ch.black, ch.white = lo, hi
        ch.vmax = max(16.0, top)
        self.refresh_channels()
        self.refresh_preview()
        self._refresh_thumb_later()
        self.lbl_status.setText("已把 %s 拉伸到 1%%~99.9%% 分位（%.0f ~ %.0f）"
                                % (self._chan_label(ch), lo, hi))

    def apply_channel_color(self, ch, label, col):
        self._commit("改通道颜色")
        ch.color = tuple(col)
        # 灰底 = 明场底图；红/绿各自成类，导出文件名也跟着对
        ch.role = "gray" if label.startswith("灰底") else ("red" if label.startswith("红") else "green")
        self.refresh_channels()
        self.refresh_preview()
        self._refresh_thumb_later()

    def on_merge_mode(self, *_a):
        """改「叠加方式」：显示要立刻跟上（底图也得重算，不然拖动时露旧画面）。"""
        self._commit("改叠加方式")
        self._sync_settings()
        self.refresh_preview()
        self._refresh_thumb_later()
        self.refresh_manifest()
        self.lbl_status.setText("叠加方式：%s" % self.cb_merge_mode.currentText())

    def on_channel_slider(self, ch, lo, hi):
        self._commit("调通道区间", coalesce=1.5)     # 拖动过程只记一次快照
        ch.black, ch.white = float(lo), float(hi)
        ui = self._chan_ui.get(ch.index)
        if ui:
            for key, val in (("black", lo), ("white", hi)):
                w = ui.get(key)
                if w is not None:
                    w.blockSignals(True)
                    w.setValue(int(val))
                    w.blockSignals(False)
        self.refresh_preview()
        self._refresh_thumb_later()

    def on_channel_spin(self, ch, attr, value):
        self._commit("调通道区间")
        setattr(ch, attr, float(value))
        if ch.white <= ch.black:
            ch.white = ch.black + 1
        ui = self._chan_ui.get(ch.index)
        if ui and ui.get("slider") is not None:
            ui["slider"].setValues(ch.black, ch.white)
            ui["slider"].setRange(0, max(16, int((ch.vmax or ch.white) * 1.05)))
        self.refresh_preview()
        self._refresh_thumb_later()

    @staticmethod
    def _color_icon(rgb, size=14):
        """菜单上的小色点。"""
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(*rgb))
        p.drawEllipse(1, 1, size - 2, size - 2)
        p.end()
        return QIcon(pm)

    def pick_channel_color(self, ch):
        """点色点：弹出颜色菜单（自定义走取色器）。"""
        menu = QMenu(self)
        acts = []
        for label, col in CHANNEL_COLORS:
            act = menu.addAction(label)
            act.setIcon(self._color_icon(col))
            acts.append(act)
        menu.addSeparator()
        act_custom = menu.addAction("自定义…")
        chosen = menu.exec(QCursor.pos())
        if chosen is None:
            return
        if chosen is act_custom:
            from PySide6.QtWidgets import QColorDialog
            col = QColorDialog.getColor(QColor(*ch.color), self, "通道颜色")
            if not col.isValid():
                return
            ch.color = (col.red(), col.green(), col.blue())
            self.refresh_channels()
            self.refresh_preview()
            self._refresh_thumb_later()
            return
        for act, (label, col) in zip(acts, CHANNEL_COLORS):
            if chosen is act:
                self.apply_channel_color(ch, label, col)
                return

    def set_channel_visible(self, ch, on):
        self._commit("通道显示 / 隐藏")
        ch.visible = bool(on)
        self.refresh_preview()
        self._refresh_thumb_later()

    def set_channel_range(self, ch, attr, value):
        setattr(ch, attr, float(value))
        if ch.white <= ch.black:
            ch.white = ch.black + 1.0
        self.refresh_preview()

    def refresh_calib(self):
        it = self.cur_item
        if not it:
            return
        if self.cur_group is not None:
            self.lbl_group_head.setText(self.cur_group.title)
            um = it.umpp if it.umpp > 0 else 0
            # Z / T 分开写（P0-3）：以前混成一句"N 帧"，用户分不清是层还是时间点
            dims = []
            if int(it.z_count or 1) > 1:
                dims.append("Z %d 层%s" % (it.z_count,
                                          (" · %.3g µm 步进" % it.z_step_um)
                                          if it.z_step_um > 0 else ""))
            if int(it.t_count or 1) > 1:
                dims.append("时间 %d 点%s" % (it.t_count,
                                            (" · 间隔 %.3g s" % it.t_interval_s)
                                            if it.t_interval_s > 0 else ""))
            if not dims and it.frames > 1:
                dims.append("%d 帧" % it.frames)
            self.lbl_group_info.setText(
                "%s µm/px · %d×%d · %d 通道%s"
                % (("%g" % round(um, 4)) if um else "未标定", it.width, it.height,
                   len(it.channels), (" · " + " · ".join(dims)) if dims else ""))
        if it.umpp > 0:
            self.lbl_calib.setText("%s\n%g µm/px · %s\n视野 %.1f µm · %d×%d px"
                                   % (it.name, round(it.umpp, 5), it.calib, it.field_um(),
                                      it.width, it.height))
        else:
            self.lbl_calib.setText("%s\n未标定（%s）" % (it.name, it.calib))
        # 画线标定只给图片格式用；下机文件自带标定就不显示这套工具
        self.cal_tool.setVisible(is_image_file(it.path))
        # 有识别结果才显示「识别不对，手动框」（5.4.6）
        self.btn_detect_fix.setVisible(is_image_file(it.path)
                                       and self._detect_info(it) is not None)
        self._refresh_cands()

    def _refresh_cands(self):
        """多候选待确认时，在标定卡片里列出每条候选线让用户点选（规格书 5.4.5）。"""
        lay = getattr(self, "cand_lay", None)
        if lay is None:
            return
        while lay.count() > 1:                    # 保留第 0 项（说明文字）
            item = lay.takeAt(1)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        it = self.cur_item
        det = getattr(it, "detect", None) if it else None
        show = bool(det) and is_image_file(it.path) and bar_mod.ambiguous(det)
        self.cand_box.setVisible(show)
        if not show:
            return
        cands = det.get("candidates") or []
        self.lbl_cand.setText("识别到 %d 条候选标尺线，点一条采用（图上琥珀色是其它候选）："
                              % len(cands))
        for i, c in enumerate(cands):
            bar = c.get("bar") or {}
            txt = c.get("text") or ("%.4g µm" % c.get("value_um", 0))
            b = BrutalButton("%d) %s · 长 %.0f px · 置信 %.2f · %.4g µm/px"
                             % (i + 1, txt, bar.get("length", 0.0),
                                c.get("score", 0.0), c.get("umpp", 0.0)), compact=True)
            b.clicked.connect(lambda _ck=False, cc=c: self.apply_candidate(cc))
            lay.addWidget(b)

    def apply_candidate(self, c):
        """用户点选某条候选线 → 就按它标定。"""
        it = self.cur_item
        if not it or float(c.get("umpp") or 0.0) <= 0:
            return
        self._commit("选定候选标尺")
        it.umpp = float(c["umpp"])
        it.calib = "标尺识别（多候选，人工选定 %s）" % (c.get("text") or "")
        det = dict(getattr(it, "detect", {}) or {})
        det.update(ok=True, umpp=it.umpp, value_um=c.get("value_um"), text=c.get("text"),
                   bar=c.get("bar"), box=c.get("box"), candidates=[c],
                   why="人工选定候选")
        it.detect = det
        self._regroup()
        self.refresh_groups()
        self.refresh_strip()
        self.refresh_calib()
        self.refresh_preview()
        self.refresh_manifest()
        self.lbl_status.setText("已按选中的候选标定 %g µm/px" % it.umpp)

    def refresh_manifest(self):
        st = self._sync_settings()
        variants = (1 if st.exp_merge else 0) + sum(1 for x in st.exp_ch if x)
        lines, total, skipped = [], 0, 0
        raw_bits = set()
        for g in self.groups:
            shots = 0
            files = 0
            for it in g.images:
                if getattr(it, "missing", False):
                    skipped += 1              # 原文件不在的占位图不参与导出
                    continue
                if it.umpp <= 0:
                    skipped += 1
                    continue
                nf = len(self._frames_for(it))
                shots += nf
                files += nf * variants        # 彩图
                if st.exp_raw_single:         # 原始位深：逐通道，不受 CH1~CH3 勾选限制
                    files += nf * max(1, len(it.channels))
                    raw_bits.add(int(getattr(it, "bits", 8) or 8))
                if st.exp_raw_stack:
                    files += nf
                    raw_bits.add(int(getattr(it, "bits", 8) or 8))
            total += files
            lines.append("%s · %d 张 → %d 个文件" % (g.title, g.count, files))
        tail = "合计 %d 个文件 · 24bit 彩色" % total
        if raw_bits:
            tail += " + 原始位深 %sbit" % "/".join(str(b) for b in sorted(raw_bits))
        if st.out_format in ("png", "jpg") and (st.exp_raw_single or st.exp_raw_stack):
            tail += "（原始导出强制 TIFF）"
        if skipped:
            tail += "（%d 张未标定，先跳过）" % skipped
        # 底栏只放一行摘要，详细清单放进悬停提示
        if lines:
            self.manifest.setText("导出清单：%d 组 · %s" % (len(lines), tail))
            self.manifest.setToolTip("\n".join(lines + [tail]))
        else:
            self.manifest.setText("还没有导入图片")
            self.manifest.setToolTip("")

    # ------------------------------------------------------------ 缩略图 / 标定
    def start_thumbnails(self):
        if self._thumb_worker and self._thumb_worker.isRunning():
            self._thumb_worker.stop()
            self._thumb_worker.wait(500)
        self._thumb_worker = ThumbWorker(self.items, self, mode=self.settings.merge_mode)
        self._thumb_worker.ready.connect(self.on_thumb_ready)
        self._thumb_worker.start()

    def on_thumb_ready(self, path, thumb):
        if not path:
            return
        self._thumbs[path] = thumb
        tb = getattr(self, "_thumb_buttons", {}).get(path)
        if tb:
            tb.set_thumb(thumb)
        # 缩略图是在后台线程解码的，那一步可能刚把通道表修正（合并"原始版+处理版"、
        # 隐藏全黑通道）——当前这张要补刷通道卡，否则右栏一直挂着多余的那几路。
        self._settle_channels(next((x for x in self.items if x.path == path), None))

    def _refresh_thumb_later(self):
        """通道颜色/区间改完，过一会儿重出当前这张的缩略图。"""
        self._thumb_timer.start()
        self._base_stale = True          # 底图也等停下来再重算，拖动才不卡
        self._base_timer.start()

    def _refresh_base_layer(self):
        """把整图底图按最新通道设置重算一次（延迟执行，避免拖动时卡顿）。"""
        if not self._base_stale or self.cur_item is None:
            return
        if self.view_mode != "full" or self.canvas.zoom() <= 1.0001:
            # **这里千万不能把 _base_stale 清掉**：1× 时底图本来就不显示，清掉它就等于
            # 忘了"底图脏了"这件事 —— 之后放大，_preview_full 看到 key 命中 + 不脏，
            # 就不会重算底图，于是拖动/缩放时新露出来的区域还是**改配色之前**的画面
            # （2026-09-27 用户实测反馈）。留着脏标记，等真放大时再算。
            return
        if self._base_planes is not None:
            try:
                self._base_rgb = render.compose(
                    self._base_planes, self.cur_item.channels,
                    render.ranges_for(self.cur_item, self.frame),
                    mode=self.settings.merge_mode)
                self.canvas.set_base_image(self._base_rgb,
                                           float(self.canvas.devicePixelRatioF() or 1.0),
                                           (0.0, 0.0, self.cur_item.field_um() or 1.0,
                                            (self.cur_item.height * self.cur_item.umpp)
                                            if self.cur_item.umpp > 0 else 1.0))
            except Exception:                    # noqa: BLE001
                pass
        self._base_stale = False

    def _refresh_current_thumb(self):
        item = self.cur_item
        if item is None:
            return
        planes = None
        if getattr(self, "_base_key", None) == (item.path, self.frame):
            planes = self._base_planes          # 用小图出缩略图，快很多
        worker = ThumbWorker([item], self, planes=planes, mode=self.settings.merge_mode)
        worker.ready.connect(self.on_thumb_ready)
        worker.start()
        self._workers.append(worker)

    def auto_calibrate(self):
        need = [it for it in self.items if it.umpp <= 0]
        if not need:
            QMessageBox.information(self, "不用识别", "所有图都已经有标定了。")
            return
        self._commit("自动识别标尺")     # 快照必须在后台线程改数据之前取
        self.lbl_status.setText("正在识别 %d 张图的标尺（OCR）…" % len(need))
        self._run(FnWorker(job_calibrate, self.items), self.on_calib_done)

    def on_calib_done(self, _items):
        self.progress.setValue(0)
        self._mark_dirty()
        self._regroup()
        self.refresh_groups()
        self.refresh_strip()
        self.refresh_calib()
        self.refresh_manifest()
        self.refresh_preview()
        self.lbl_status.setText("标尺识别结束")

    def apply_manual_umpp(self, all_group=False):
        if not self.cur_item:
            return
        value = self.sp_umpp.value()
        if all_group and self.cur_group:
            targets = self.cur_group.images
        else:
            targets = [self.cur_item]
        self._commit("手动填写标定")
        for it in targets:
            it.umpp = value
            it.calib = "手动填写"
        self.refresh_calib()
        self.refresh_groups()
        self.refresh_manifest()
        self.refresh_preview()
        self.lbl_status.setText("已把 %g µm/px 应用到 %d 张图" % (value, len(targets)))

    # ------------------------------------------------------------ 导出
    def _frames_for(self, item):
        """按 Z / T 两个维度各自的"全部 / 当前 / 指定"算要导出的展平帧号（3.18.5）。"""
        if item.frames <= 1:
            return [0]
        st = self._sync_settings()
        cur = item is self.cur_item
        zs = self._pick_dim(st.z_mode, st.z_pick, max(1, int(item.z_count or 1)),
                            self.cur_z if cur else 0)
        ts = self._pick_dim(st.frames_mode, st.frame_pick, max(1, int(item.t_count or 1)),
                            self.cur_t if cur else 0)
        return sorted({item.flat_index(t, z) for t in ts for z in zs}) or [0]

    def _pick_dim(self, mode, text, n, cur):
        """一个维度（Z 或 T）选出来的是哪几个序号（0 基）。"""
        n = max(1, int(n))
        if mode == "all":
            return list(range(n))
        if mode == "pick":
            return self._parse_frames(text, n)
        return [min(max(0, int(cur)), n - 1)]

    @staticmethod
    def _parse_frames(text, total):
        out = []
        for part in (text or "").replace("，", ",").replace(" ", "").split(","):
            if not part:
                continue
            if "-" in part:
                try:
                    a, b = part.split("-")[:2]
                    out.extend(range(int(a) - 1, int(b)))
                except ValueError:
                    continue
            else:
                try:
                    out.append(int(part) - 1)
                except ValueError:
                    continue
        return [max(0, min(f, total - 1)) for f in sorted(set(out))] or [0]

    def _build_jobs(self, scope="all", picked=None):
        """scope: "one" 只当前图 / "group" 只当前组 / "all" 全部（兼容旧的 True/False）。

        `picked` 是导出弹窗勾出来的 [(图, 组)]，给了它就只导这些（2026-09-23）。
        """
        if scope is True:
            scope = "one"
        elif scope is False:
            scope = "all"
        if picked is not None:
            pairs = list(picked)
        else:
            groups = self.groups if scope == "all" else [self.cur_group]
            pairs = [(it, g) for g in groups if g
                     for it in ([self.cur_item] if (scope == "one" and g is self.cur_group)
                                else g.images)]
        jobs = []
        for it, g in pairs:
            if it is None or it.umpp <= 0 or getattr(it, "missing", False):
                continue                      # 没标定 / 原文件不在：跟以前一样跳过
            jobs.append((it, g, self._frames_for(it)))
        return jobs

    def _export(self, scope="all", picked=None):
        st = self._sync_settings()
        jobs = self._build_jobs(scope, picked)
        if not jobs:
            QMessageBox.information(self, "没有可导出的图",
                                    "先补齐标定（µm/px），或者等自动识别完成。")
            return
        out_root = st.out_dir or paths.OUTPUT_DIR
        self.lbl_status.setText("正在导出…")
        self._run(FnWorker(job_export, jobs, st, out_root), self.on_export_done)

    def export_menu(self):
        """Download：先选图片、再选导出内容（一窗两栏，见 ui/export_dialog.py）。"""
        if not self.items:
            QMessageBox.information(self, "还没有图片", "先导入图片再导出。")
            return
        picked = self.exp_dialog.pick(self.groups, focus_item=self.cur_item)
        if picked is None:                    # 用户点了取消
            return
        self._export("picked", picked=picked)

    def export_current(self):
        self._export("one")

    def export_all(self):
        self._export("all")

    def on_export_done(self, rows):
        ok = sum(1 for r in rows if r.get("files"))
        files = sum(int(r.get("files") or 0) for r in rows)
        self.progress.setValue(100)
        self.lbl_status.setText("导出完成：%d 张 → %d 个文件" % (ok, files))
        out_root = self.settings.out_dir or paths.OUTPUT_DIR
        QMessageBox.information(self, "导出完成",
                                "共处理 %d 张，写出 %d 个文件。\n输出目录：%s"
                                % (ok, files, out_root))

    # ------------------------------------------------------------ 工程文件 / 撤销
    @staticmethod
    def _no_save():
        """自检脚本会设这个变量：不写盘（不碰用户的 settings / 工程 / autosave）。"""
        return os.environ.get("IMAGECAPTURE_NO_SAVE") == "1"

    def _bind_shortcuts(self):
        pairs = (("Ctrl+S", self.proj_save), ("Ctrl+Shift+S", self.proj_save_as),
                 ("Ctrl+O", self.proj_open), ("Ctrl+N", self.proj_new),
                 ("Ctrl+Z", self.do_undo), ("Ctrl+Y", self.do_redo),
                 ("Ctrl+Shift+Z", self.do_redo),
                 # 熟手快路：不弹选图窗，按上次的导出设置直接导全部（2026-09-23）
                 ("Ctrl+E", self.export_all))
        for keys, slot in pairs:
            sc = QShortcut(QKeySequence(keys), self)
            sc.setContext(Qt.WindowShortcut)
            sc.activated.connect(slot)
            self._shortcuts.append(sc)

    # ---- 快照
    def _view_state(self):
        return dict(group=(self.cur_group.gid if self.cur_group else ""),
                    item=(self.cur_item.path if self.cur_item else ""),
                    frame=int(self.frame or 0), mode=self.view_mode,
                    t=int(self.cur_t or 0), z=int(self.cur_z or 0))

    def _snapshot(self):
        """撤销栈用的纯数据快照（不含像素缓存，几百 KB 级）。"""
        return proj_mod.build_doc(self._sync_settings(), self.groups, self.items,
                                  self._view_state())

    def _project_doc(self):
        """写盘用的工程内容：按工程文件所在目录补一份相对路径（换盘符也打得开）。"""
        doc = self._snapshot()
        base = os.path.dirname(os.path.abspath(self._proj_path)) if self._proj_path else ""
        if base:
            doc["items"] = [proj_mod.item_to_dict(it, base) for it in self.items]
        return doc

    # ---- 脏标记 / 标题 / 撤销按钮
    def _mark_dirty(self, on=True):
        if self._restoring:
            return
        self._dirty = bool(on)
        self._update_title()          # 标题要跟着"未命名/文件名 + *"走

    def _commit(self, name, coalesce=0.0):
        """动作提交：先记一份"动作发生前"的快照，再打脏标记。

        只在提交时调用（裁剪框走 box_committed、拖标尺走 bar_drag_done），
        不在拖动过程中调用 —— 否则撤销栈会被中间态塞满（规格书 3.4.7）。
        """
        if self._restoring:
            return
        self._undo.push(name, self._snapshot(), coalesce)
        self._mark_dirty()
        self._update_undo_buttons()

    def _update_title(self):
        nm = os.path.basename(self._proj_path) if self._proj_path else "未命名"
        self.setWindowTitle("Image capture — %s%s · %s"
                            % (nm, " *" if self._dirty else "", APP_VERSION))

    def _update_undo_buttons(self):
        u, r = self._undo.names()
        self.btn_undo.setEnabled(self._undo.can_undo())
        self.btn_redo.setEnabled(self._undo.can_redo())
        self.btn_undo.setToolTip(("撤销「%s」" % u) if u else "没有可撤销的操作")
        self.btn_redo.setToolTip(("重做「%s」" % r) if r else "没有可重做的操作")

    def do_undo(self):
        got = self._undo.undo(self._snapshot())
        if not got:
            self.lbl_status.setText("没有可撤销的操作")
            return
        name, doc = got
        self._apply_state(doc)
        self._mark_dirty()
        self._update_undo_buttons()
        self.lbl_status.setText("已撤销：%s" % name)

    def do_redo(self):
        got = self._undo.redo(self._snapshot())
        if not got:
            self.lbl_status.setText("没有可重做的操作")
            return
        name, doc = got
        self._apply_state(doc)
        self._mark_dirty()
        self._update_undo_buttons()
        self.lbl_status.setText("已重做：%s" % name)

    def _apply_state(self, doc):
        """把一份快照 / 工程内容套回界面（撤销、重做、打开工程共用这一处）。"""
        self._restoring = True
        try:
            bases = [os.path.dirname(os.path.abspath(self._proj_path))] if self._proj_path else []
            st, groups, items, orphan, view = proj_mod.load_into(doc, bases)
            for old in self.items:           # 换工作区：把上一位的像素缓存放掉
                try:
                    loader.release(old)
                except Exception:            # noqa: BLE001
                    pass
            self.settings = st
            self.items = items
            self.groups = groups
            if orphan:                       # 组对不上（工程被手改过）：先并进第一组，别丢图
                if not self.groups:
                    self.groups.append(Group(gid="g1", title="组 1"))
                self.groups[0].images.extend(orphan)
            for g in self.groups:
                for x in g.images:
                    x.group = g.gid
            # 裁剪宽高 / 1:1 / 组内同步：控件与数据是双向的，恢复时要挡信号
            for w, v in ((self.f_w, st.crop_w), (self.f_h, st.crop_h)):
                w.blockSignals(True)
                w.setValue(float(v))
                w.blockSignals(False)
            for w, v in ((self.chk_lock, st.lock_1to1), (self.chk_sync, st.group_sync),
                         (self.btn_hide_box, not bool(getattr(st, "show_box", True)))):
                w.blockSignals(True)
                w.setChecked(bool(v))
                w.blockSignals(False)
            want_frame = int(view.get("frame") or 0)
            self.cur_group = next((g for g in self.groups if g.gid == view.get("group")), None)
            self.cur_item = next((x for x in self.items if x.path == view.get("item")), None)
            self.view_mode = view.get("mode") or "full"
        finally:
            self._restoring = False
        self._thumbs = {}                    # 缩略图重出（工程文件不存缩略图）
        self.canvas.set_show_box(self.view_mode == "full"
                                 and not self.btn_hide_box.isChecked())
        self.btn_view_full.setChecked(self.view_mode == "full")
        self.btn_view_crop.setChecked(self.view_mode == "crop")
        self.btn_hide_box.setEnabled(self.view_mode == "full")
        self.canvas.set_zoom(1.0)
        self.refresh_groups()
        if self.cur_group is not None:
            self.select_group(self.cur_group.gid)
        else:
            self.refresh_strip()
        if self.cur_item is not None:
            self.select_item(self.cur_item.path)
            if want_frame and self.cur_item.frames > 1:
                # 优先按存下来的 (t, z)；老工程只有 frame，就换算回 t/z
                if view.get("t") is not None or view.get("z") is not None:
                    self.cur_t = int(view.get("t") or 0)
                    self.cur_z = int(view.get("z") or 0)
                else:
                    self.cur_t, self.cur_z = self.cur_item.tz_of(want_frame)
                self.frame = self.cur_item.flat_index(self.cur_t, self.cur_z)
                self._sync_frame_ui()
                self.refresh_preview()
        self.refresh_calib()
        self.refresh_preview()
        self.refresh_manifest()
        if self.items:
            self.start_thumbnails()

    # ---- 工程菜单
    def project_menu(self):
        menu = QMenu(self)
        a_new = menu.addAction("新建工程")
        a_open = menu.addAction("打开工程…")
        a_save = menu.addAction("保存")
        a_saveas = menu.addAction("另存为…")
        a_saveas.setEnabled(bool(self.items))
        menu.addSeparator()
        rec = menu.addMenu("最近打开")
        rec.setEnabled(bool(self._recent))
        for p in self._recent[:10]:
            act = rec.addAction(os.path.basename(p))
            act.setToolTip(p)
            act.setData(p)
        a_clr = rec.addAction("清空最近记录")
        menu.addSeparator()
        a_redetect = menu.addAction("重新探测元数据")
        a_redetect.setToolTip("重读一遍所有下机文件的标定 / 尺寸 / 帧数（大图会慢）")
        a_restore = menu.addAction("恢复上次自动保存")
        a_restore.setEnabled(os.path.exists(paths.AUTOSAVE_FILE))
        chosen = menu.exec(self.btn_proj.mapToGlobal(self.btn_proj.rect().bottomLeft()))
        if chosen is None:
            return
        if chosen is a_new:
            self.proj_new()
        elif chosen is a_open:
            self.proj_open()
        elif chosen is a_save:
            self.proj_save()
        elif chosen is a_saveas:
            self.proj_save_as()
        elif chosen is a_clr:
            self._recent = []
            self._save_recent()
        elif chosen is a_redetect:
            self.redetect_all()
        elif chosen is a_restore:
            self.restore_autosave()
        elif chosen.data():
            self.open_project(chosen.data())

    def _confirm_discard(self):
        """有未保存改动时问一句。返回 True = 可以继续（丢弃/已保存）。"""
        if not self._dirty or self._no_save():
            return True
        ans = QMessageBox.question(self, "还有未保存的改动",
                                   "当前工作区有未保存的改动。要先保存吗？",
                                   QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                                   QMessageBox.Save)
        if ans == QMessageBox.Cancel:
            return False
        if ans == QMessageBox.Save:
            return bool(self.proj_save())
        return True

    def proj_new(self):
        if not self._confirm_discard():
            return
        self._restoring = True
        try:
            for it in self.items:
                loader.release(it)
            self.items = []
            self.groups = []
            self.cur_group = None
            self.cur_item = None
            self._thumbs.clear()
            self._proj_path = ""
            self._undo.clear()
            self._dirty = False
        finally:
            self._restoring = False
        self.refresh_groups()
        self.refresh_strip()
        self.refresh_channels()
        self.refresh_preview()
        self.refresh_manifest()
        self._update_title()
        self._update_undo_buttons()
        self.lbl_status.setText("新建工程：空白工作区")

    def proj_save(self):
        if not self._proj_path:
            return self.proj_save_as()
        try:
            proj_mod.save_project(self._proj_path, self._project_doc(),
                                  os.path.dirname(os.path.abspath(self._proj_path)))
        except Exception as exc:                 # noqa: BLE001
            QMessageBox.warning(self, "保存失败",
                                "工程没能写入：\n%s\n\n可以试试「另存为」。" % exc)
            return False
        self._mark_dirty(False)
        self._push_recent(self._proj_path)
        self.lbl_status.setText("工程已保存：%s" % self._proj_path)
        return True

    def proj_save_as(self):
        default = self._proj_path or os.path.join(paths.OUTPUT_DIR, "未命名.icproj")
        p, _f = QFileDialog.getSaveFileName(self, "另存为工程", default,
                                            "Image capture 工程 (*.icproj)")
        if not p:
            return False
        if not p.lower().endswith(".icproj"):
            p += ".icproj"
        self._proj_path = p
        return self.proj_save()

    def proj_open(self):
        if not self._confirm_discard():
            return
        p, _f = QFileDialog.getOpenFileName(self, "打开工程", paths.OUTPUT_DIR,
                                            "Image capture 工程 (*.icproj)")
        if p:
            self.open_project(p)

    def open_project(self, path):
        try:
            doc = proj_mod.load_project(path)
        except proj_mod.ProjectError as exc:
            QMessageBox.warning(self, "打不开这个工程", str(exc))
            return False
        self._proj_path = path
        self._apply_state(doc)
        self._undo.clear()                       # 打开工程：栈清空（规格书 3.4.7.1）
        self._mark_dirty(False)
        self._push_recent(path)
        self._update_undo_buttons()
        miss = [x for x in self.items if getattr(x, "missing", False)]
        if miss:
            self._ask_missing(miss)
        self.lbl_status.setText("已打开工程：%s（%d 张 · %d 组）"
                                % (os.path.basename(path), len(self.items), len(self.groups)))
        return True

    def _ask_missing(self, miss):
        """工程里有原文件找不到 —— 绝不能让整个工程打不开（规格书 3.4.5）。"""
        names = "\n".join("· %s" % (m.file_path or m.path) for m in miss[:8])
        more = "\n（还有 %d 个）" % (len(miss) - 8) if len(miss) > 8 else ""
        box = QMessageBox(self)
        box.setWindowTitle("有文件找不到")
        box.setText("工程里有 %d 张图的原文件不在原来的位置：\n%s%s\n\n想怎么处理？"
                    % (len(miss), names, more))
        b_keep = box.addButton("全部保留占位", QMessageBox.AcceptRole)
        b_pick = box.addButton("逐个选择新位置", QMessageBox.ActionRole)
        b_drop = box.addButton("移除这些条目", QMessageBox.DestructiveRole)
        box.exec()
        hit = box.clickedButton()
        if hit is b_drop:
            for m in list(miss):
                self.remove_item(m)
        elif hit is b_pick:
            for m in list(miss):
                p, _f = QFileDialog.getOpenFileName(
                    self, "给「%s」选新位置" % m.name,
                    os.path.dirname(m.file_path or m.path) or paths.OUTPUT_DIR)
                if p:
                    self.relocate_item(m, p)
        self._mark_dirty()

    def relocate_item(self, item, newpath):
        """把某个条目指向新文件：分组 / 标定 / 裁剪框都留着。"""
        old = item.path
        item.path = newpath + (("#%d" % (item.series + 1)) if item.series else "")
        item.name = os.path.basename(newpath)
        item.missing = not os.path.exists(item.file_path)
        for g in self.groups:                    # boxes 是按 path 存的，键要跟着换
            if old in g.boxes:
                g.boxes[item.path] = g.boxes.pop(old)
        self.refresh_groups()
        self.refresh_strip()
        self.refresh_manifest()
        self.lbl_status.setText("已重新指向：%s" % item.name)

    def redetect_all(self):
        files, seen = [], set()
        for it in self.items:
            p = it.file_path
            if p and p not in seen and os.path.exists(p):
                seen.add(p)
                files.append(p)
        if not files:
            self.lbl_status.setText("没有可重新探测的文件")
            return
        self.lbl_status.setText("正在重新探测 %d 个文件…" % len(files))
        self._run(FnWorker(job_probe, files), self._on_redetect_done)

    def _on_redetect_done(self, items):
        by_path = {it.path: it for it in items if it.calib != "失败"}
        n = 0
        for it in self.items:
            src = by_path.get(it.path)
            if src is None:
                continue
            for k in ("width", "height", "frames", "bits", "channels", "calib"):
                setattr(it, k, getattr(src, k))
            if it.umpp <= 0 and src.umpp > 0:
                it.umpp = src.umpp
            it.missing = False
            n += 1
        self.progress.setValue(0)
        # 通道表可能整个变了 → 缩略图缓存也要作废重出（不然条带里还是旧配色）
        self._thumbs.clear()
        self._regroup()
        self.refresh_groups()
        self.refresh_strip()
        self.refresh_calib()
        self.refresh_preview()
        self.refresh_manifest()
        self._mark_dirty()
        if self.items:
            self.start_thumbnails()
        self.lbl_status.setText("已重新探测 %d 张的元数据" % n)

    # ---- 自动保存 / 崩溃恢复
    def _autosave_tick(self):
        if self._no_save() or not self._dirty:
            return
        if time.monotonic() - self._autosave_at < 120:
            return
        self.write_autosave()

    def write_autosave(self, silent=True):
        """自动保存只写 config\\autosave.icproj，绝不覆盖用户的正式工程文件。"""
        try:
            proj_mod.save_project(paths.AUTOSAVE_FILE, self._snapshot())
            self._autosave_at = time.monotonic()
            if not silent:
                self.lbl_status.setText("已自动保存到 config\\autosave.icproj")
            return True
        except Exception as exc:                 # noqa: BLE001
            if not silent:
                self.lbl_status.setText("自动保存失败：%s" % exc)
            return False

    def _check_autosave(self):
        if self._no_save() or not os.path.exists(paths.AUTOSAVE_FILE):
            return
        try:
            last = 0.0
            if os.path.exists(paths.LAST_EXIT_FILE):
                with open(paths.LAST_EXIT_FILE, "r", encoding="utf-8") as fh:
                    last = float((fh.read() or "0").strip() or 0)
            if os.path.getmtime(paths.AUTOSAVE_FILE) <= last:
                return                  # 上次是正常退出，不打扰
            when = time.strftime("%m-%d %H:%M",
                                 time.localtime(os.path.getmtime(paths.AUTOSAVE_FILE)))
        except Exception:                       # noqa: BLE001
            return
        ans = QMessageBox.question(self, "上次没正常退出",
                                   "发现一份自动保存的工作（%s）。要载入它吗？" % when)
        if ans == QMessageBox.Yes:
            self.restore_autosave()

    def restore_autosave(self):
        if not os.path.exists(paths.AUTOSAVE_FILE):
            QMessageBox.information(self, "没有自动保存", "还没有自动保存的文件。")
            return
        try:
            doc = proj_mod.load_project(paths.AUTOSAVE_FILE)
        except proj_mod.ProjectError as exc:
            QMessageBox.warning(self, "读不了自动保存", str(exc))
            return
        self._proj_path = ""            # 恢复出来的算"未命名"，让用户另存
        self._apply_state(doc)
        self._undo.clear()
        self._dirty = True
        self._update_title()
        self._update_undo_buttons()
        miss = [x for x in self.items if getattr(x, "missing", False)]
        if miss:
            self._ask_missing(miss)
        self.lbl_status.setText("已恢复上次自动保存的工作（还没保存成正式工程）")

    # ---- 最近打开
    def _load_recent(self):
        try:
            with open(paths.RECENT_FILE, "r", encoding="utf-8") as fh:
                d = json.load(fh)
            return [p for p in (d.get("paths") or []) if isinstance(p, str)]
        except Exception:                       # noqa: BLE001
            return []

    def _save_recent(self):
        if self._no_save():
            return
        try:
            os.makedirs(paths.CONFIG_DIR, exist_ok=True)
            with open(paths.RECENT_FILE, "w", encoding="utf-8") as fh:
                json.dump({"paths": self._recent[:10]}, fh, ensure_ascii=False, indent=1)
        except Exception:                       # noqa: BLE001
            pass

    def _push_recent(self, path):
        path = os.path.abspath(path)
        self._recent = [p for p in self._recent if os.path.abspath(p) != path]
        self._recent.insert(0, path)
        self._recent = self._recent[:10]
        self._save_recent()

    # ------------------------------------------------------------ 收尾
    def save_settings(self):
        st = self._sync_settings()
        path = st.save()
        self.lbl_status.setText("参数已保存：" + path)

    # ------------------------------------------------------------ 分组管理
    def new_group(self):
        self._commit("新建组")
        n = len(self.groups) + 1
        gid = "g%d" % n
        while any(g.gid == gid for g in self.groups):
            n += 1
            gid = "g%d" % n
        g = Group(gid=gid, title="新组 %d" % n)
        g.title_manual = True               # 名字别被自动标题覆盖
        g.keep_empty = True                 # 空着也要留着，好往里放图
        field = max(self.settings.crop_w * 3, 100.0)
        g.box = dict(x=max(0.0, (field - self.settings.crop_w) / 2),
                     y=max(0.0, (field - self.settings.crop_h) / 2),
                     w=self.settings.crop_w, h=self.settings.crop_h)
        self.groups.append(g)
        self.refresh_groups()
        self.select_group(gid)
        self.lbl_status.setText("已新建一个空组，可以用「移动当前图到…」把图放进去")

    def clear_all(self):
        if not self.items:
            return
        ans = QMessageBox.question(self, "清空列表",
                                   "把列表里的 %d 张图全部移出？\n（只移出列表，不动硬盘上的原文件）"
                                   % len(self.items))
        if ans != QMessageBox.Yes:
            return
        self._commit("清空列表")
        for it in self.items:
            loader.release(it)
        self.items = []
        self.groups = []
        self.cur_group = None
        self.cur_item = None
        self._thumbs.clear()
        self.refresh_groups()
        self.refresh_strip()
        self.refresh_preview()
        self.refresh_manifest()
        self.lbl_status.setText("列表已清空")

    def remove_item(self, item):
        if item is None:
            return
        self._commit("移出图片")
        name = item.name
        for g in self.groups:
            g.images = [x for x in g.images if x.path != item.path]
        self.items = [x for x in self.items if x.path != item.path]
        loader.release(item)
        if self.cur_item is item:
            self.cur_item = None
        if self.cur_group and not self.cur_group.images:
            self.cur_group = None
        self._regroup()                          # 空掉的组直接消失，不留空壳
        self.refresh_groups()
        self.refresh_strip()
        live = next((g for g in self.groups if g.images), None)
        if live is not None:
            self.select_group(live.gid)
        else:
            self.cur_group = None
            self.cur_item = None
            self.refresh_preview()
            self.refresh_channels()
        self.refresh_manifest()
        self.lbl_status.setText("已移出：%s（原文件没动）" % name)

    def remove_current(self):
        self.remove_item(self.cur_item)

    def move_item_to(self, path, gid):
        item = next((x for x in self.items if x.path == path), None)
        if item is None:
            return
        target = next((g for g in self.groups if g.gid == gid), None)
        if target is None:
            return
        self._commit("把图片移到别的组")
        item.group_manual = True                 # 记住是你手工放的，重组时不再被打回原组
        item.group_key = target.key
        item.group = target.gid
        self._regroup()                          # 源组空了就消失，目标组的图也补上
        target = next((g for g in self.groups if g.key == item.group_key), None)
        if target is not None:
            self.cur_group = target
        self.refresh_groups()
        self.refresh_strip()
        self.select_item(item.path)              # 移过去后直接显示这一张，看得见效果
        self.refresh_manifest()
        self.lbl_status.setText("已把 %s 移到「%s」" % (
            item.name, target.title if target else "别的组"))

    def set_first_in_group(self, path):
        item = next((x for x in self.items if x.path == path), None)
        if item is None:
            return
        self._commit("设为组内第一张")
        for g in self.groups:
            if any(x.path == path for x in g.images):
                g.images = [item] + [x for x in g.images if x.path != path]
                self.cur_group = g
                break
        self.refresh_groups()
        self.refresh_strip()
        self.lbl_status.setText("「%s」组默认显示：%s" % (self.cur_group.title, item.name))

    def open_item_folder(self, path):
        item = next((x for x in self.items if x.path == path), None)
        path = item.file_path if item is not None else path
        try:
            os.startfile(os.path.dirname(path))
        except Exception as exc:                 # noqa: BLE001
            self.lbl_status.setText("打不开文件夹：%s" % exc)

    def copy_item_path(self, path):
        item = next((x for x in self.items if x.path == path), None)
        path = item.file_path if item is not None else path
        QApplication.clipboard().setText(path)
        self.lbl_status.setText("路径已复制")

    def thumb_menu(self, path, pos):
        """右键单张缩略图：移动 / 移出 / 打开位置 / 复制路径。"""
        item = next((x for x in self.items if x.path == path), None)
        if item is None:
            return
        menu = QMenu(self)
        sub = menu.addMenu("移动到其他组")
        for g in self.groups:
            act = sub.addAction("%s（%d 张）" % (g.title, g.count))
            act.setData(g.gid)
            act.setEnabled(item.group != g.gid)
        act_first = menu.addAction("设为这一组的第一张")
        act_find = None
        if getattr(item, "missing", False):
            act_find = menu.addAction("重新指定文件位置…")
        act_back = None
        if getattr(item, "has_proc", False):
            act_back = menu.addAction("还原到未处理状态")
            act_back.setEnabled(bool(getattr(item, "embed_ok", False)))
            act_back.setToolTip("把这条 TIFF 里内嵌的链前像素换回来（逐像素相同）"
                                if getattr(item, "embed_ok", False) else
                                "这个文件只记录了处理步骤，没有内嵌原始数据，还原不了")
        menu.addSeparator()
        act_del = menu.addAction("从列表移出（不动原文件）")
        act_open = menu.addAction("打开所在文件夹")
        act_copy = menu.addAction("复制文件路径")
        chosen = menu.exec(pos)
        if chosen is None:
            return
        if chosen.data():
            self.move_item_to(path, chosen.data())
        elif act_find is not None and chosen is act_find:
            p, _f = QFileDialog.getOpenFileName(
                self, "给「%s」选新位置" % item.name,
                os.path.dirname(item.file_path or item.path) or paths.OUTPUT_DIR)
            if p:
                self._commit("重新指定文件位置")
                self.relocate_item(item, p)
        elif act_back is not None and chosen is act_back:
            self.restore_item(item)
        elif chosen is act_first:
            self.set_first_in_group(path)
        elif chosen is act_del:
            self.remove_item(item)
        elif chosen is act_open:
            self.open_item_folder(path)
        elif chosen is act_copy:
            self.copy_item_path(path)

    def group_menu(self, gid, pos):
        """右键左边的组方框：重命名 / 归组 / 按组识别标尺 / 新建 / 删除。"""
        group = next((g for g in self.groups if g.gid == gid), None)
        if group is None:
            return
        menu = QMenu(self)
        act_ren = menu.addAction("重命名组…")
        act_in = menu.addAction("把当前图移入这一组")
        act_cal = menu.addAction("对本组未标定的图自动识别")
        menu.addSeparator()
        act_new = menu.addAction("新建组")
        act_del = menu.addAction("删除这个组（图片并到其他组）")
        act_del.setEnabled(len(self.groups) > 1)
        chosen = menu.exec(pos)
        if chosen is None:
            return
        if chosen is act_ren:
            self.rename_group(gid)
        elif chosen is act_in:
            if self.cur_item is None:
                QMessageBox.information(self, "还没有选中图片", "先在下面点一张图片，再回来归组。")
            else:
                self.move_item_to(self.cur_item.path, gid)
        elif chosen is act_cal:
            self.calibrate_group(gid)
        elif chosen is act_new:
            self.new_group()
        elif chosen is act_del:
            self.delete_group(gid)

    def rename_group(self, gid):
        group = next((g for g in self.groups if g.gid == gid), None)
        if group is None:
            return
        text, ok = QInputDialog.getText(self, "重命名组", "组名：", text=group.title)
        if ok and text.strip():
            self._commit("重命名组")
            group.title = text.strip()
            group.title_manual = True        # 手工改过的名字，重组时不许被自动标题覆盖
            self.refresh_groups()
            self.refresh_manifest()
            self.lbl_status.setText("组名已改为：%s" % group.title)

    def delete_group(self, gid):
        group = next((g for g in self.groups if g.gid == gid), None)
        if group is None or len(self.groups) < 2:
            return
        self._commit("删除组")
        target = next(g for g in self.groups if g.gid != gid)
        for it in list(group.images):
            target.images.append(it)
            it.group = target.gid
        self.groups = [g for g in self.groups if g.gid != gid]
        self.cur_group = target
        self.refresh_groups()
        self.refresh_strip()
        self.refresh_manifest()
        self.lbl_status.setText("已删除组「%s」，里面的图并到「%s」" % (group.title, target.title))

    def calibrate_group(self, gid):
        group = next((g for g in self.groups if g.gid == gid), None)
        if group is None:
            return
        need = [it for it in group.images if it.umpp <= 0]
        if not need:
            QMessageBox.information(self, "不用识别", "这一组的图都已有标定。")
            return
        self._commit("自动识别标尺")
        self.lbl_status.setText("正在识别「%s」里 %d 张图的标尺…" % (group.title, len(need)))
        self._run(FnWorker(job_calibrate, need), self.on_calib_done)

    def move_current_menu(self):
        """（旧的按钮入口已取消，改成右键菜单 thumb_menu）"""
        if self.cur_item:
            self.thumb_menu(self.cur_item.path, self.cursor().pos())

    def restore_item(self, item):
        """把导出的原始位深 TIFF 里内嵌的**链前像素**换回来（规格书 3.11.7）。

        不做逆运算 —— 亚像素平移、扣背景的 clip、去卷积都不可逆，
        所以"精确还原"只能靠内嵌数据，这条路径是逐像素相同的。
        """
        if item is None:
            return
        arr = raw_mod.restore_planes(item.file_path)
        if arr is None:
            QMessageBox.information(self, "没有内嵌原始数据",
                                    "这个文件只记录了处理步骤，没有内嵌可还原的像素。")
            return
        info = raw_mod.read_private(item.file_path)
        self._commit("还原到未处理状态")
        item._cache = arr
        item.frames = max(1, arr.shape[0])
        item.process = []                    # 已经回到链前，链清空（别再套一遍）
        if arr.shape[1] != len(item.channels or []):
            need = int(arr.shape[1])
            chans = list(item.channels or [])
            while len(chans) < need:         # 通道数对不上就按最后一个的形状补
                base = chans[-1] if chans else None
                from core.model import Channel as _Ch
                chans.append(_Ch(index=len(chans),
                                 name="CH%d" % (len(chans) + 1),
                                 color=getattr(base, "color", (255, 255, 255)),
                                 black=getattr(base, "black", 0.0),
                                 white=getattr(base, "white", 255.0),
                                 role=getattr(base, "role", "green")))
            item.channels = chans[:need]
        rec = (info.get("proc") or {})
        if float(rec.get("umpp") or 0) > 0:
            item.umpp = float(rec["umpp"])
        item.calib = (item.calib or "").replace("（带处理记录）", "")
        item.has_proc = False
        item.embed_ok = False
        item.note = ((item.note or "") + "　已还原到未处理状态").strip()
        self.refresh_groups()
        self.refresh_strip()
        self.refresh_calib()
        self.refresh_preview()
        self.refresh_manifest()
        self.lbl_status.setText("已还原到未处理状态：%s" % item.name)

    def closeEvent(self, ev):
        try:
            if not self._no_save():
                if self._dirty:
                    ans = QMessageBox.question(
                        self, "还有未保存的改动",
                        "工作区有未保存的改动：\n%s\n\n要先保存吗？"
                        % (self._proj_path or "（还没保存过工程）"),
                        QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                        QMessageBox.Save)
                    if ans == QMessageBox.Cancel:
                        ev.ignore()
                        return
                    if ans == QMessageBox.Save and not self.proj_save():
                        ev.ignore()
                        return
                # 先写自动保存再记"正常退出"：下次启动看见 autosave 比它旧就不打扰
                if self._dirty:
                    self.write_autosave()
                self._sync_settings().save()
                try:
                    with open(paths.LAST_EXIT_FILE, "w", encoding="utf-8") as fh:
                        fh.write(str(time.time()))
                except Exception:                # noqa: BLE001
                    pass
            if self._thumb_worker and self._thumb_worker.isRunning():
                self._thumb_worker.stop()
                self._thumb_worker.wait(800)
        except Exception:                        # noqa: BLE001
            pass
        ev.accept()
