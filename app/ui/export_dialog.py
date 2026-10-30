# -*- coding: utf-8 -*-
"""导出对话框（2026-09-23）：点 Download 之后「先选图片、再选导出内容」。

为什么做成弹窗：导出内容原来是右栏一整张卡片，占地方但改动频率很低。收进
弹窗后右栏空出来了，而「导哪些图 / 导什么内容 / 会出多少个文件」在同一屏就能看到，
不用来回翻。

**兼容约定（很重要）**：导出内容那批控件仍然用**原来的属性名挂在 MainWindow 上**
（`win.chk_merge`、`win.chk_ch`、`win.chk_raw*`、`win.chk_proj`、`win.cb_format`、
`win.ed_suffix`、`win.cb_zmode`、`win.ed_zpick`、`win.cb_frames`、`win.ed_pick`、
`win.ed_outdir`）—— `_sync_settings()` / `_sync_pills()` / `pick_outdir()` 以及
`tests\\raw_export_check.py`、`tests\\zt_check.py` 都按这些名字读，控件只是换了个
东家，按名字读的代码一行都没改。
"""
from __future__ import annotations

import paths
from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QComboBox, QDialog, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QScrollArea, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from ui.widgets import BrutalButton, FlipSwitch

GREY = QColor("#9AA0AE")


def _cap(text, kind="cardTitle"):
    lab = QLabel(text)
    lab.setObjectName(kind)
    return lab


def _tip(text):
    lab = QLabel(text)
    lab.setObjectName("cardHint")
    lab.setWordWrap(True)
    return lab


class ExportDialog(QDialog):
    """一窗两栏：左边勾图，右边勾导出内容；底部实时报"几张 → 几个文件"。"""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("导出")
        self.setModal(True)
        self.resize(950, 700)                 # 右栏内容全展开约 700 高，就不用滚了
        self._rows = {}          # item.path → (树节点, item, group)
        self._groups = {}        # group.gid → 组节点
        self._quiet = False
        self._build()

    # ------------------------------------------------------------ 搭界面
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)
        cols = QHBoxLayout()
        cols.setSpacing(14)
        cols.addWidget(self._build_left(), 0)
        cols.addWidget(self._build_right(), 1)
        root.addLayout(cols, 1)

        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.lbl_sum = QLabel("")
        self.lbl_sum.setObjectName("cardTitle")
        bar.addWidget(self.lbl_sum, 1)
        self.btn_cancel = BrutalButton("取消")
        self.btn_cancel.clicked.connect(self.reject)
        bar.addWidget(self.btn_cancel)
        self.btn_go = BrutalButton("开始导出")
        self.btn_go.clicked.connect(self.accept)
        bar.addWidget(self.btn_go)
        root.addLayout(bar)

    def _build_left(self):
        box = QWidget()
        box.setFixedWidth(372)
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        v.addWidget(_cap("① 选图片"))
        v.addWidget(_tip("勾整组 = 组内全部；灰掉的是没标定或原文件找不到的图，先修好才能导"))
        tools = QHBoxLayout()
        tools.setSpacing(6)
        for text, slot in (("全选", self.select_all), ("全不选", self.select_none),
                           ("反选", self.invert)):
            b = BrutalButton(text, compact=True)
            b.clicked.connect(slot)
            tools.addWidget(b)
        tools.addStretch(1)
        v.addLayout(tools)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["图片", "帧"])
        self.tree.setUniformRowHeights(True)
        self.tree.setColumnWidth(0, 250)
        self.tree.setColumnWidth(1, 54)
        self.tree.itemChanged.connect(self._on_item_changed)
        v.addWidget(self.tree, 1)
        self.lbl_empty = QLabel("")
        self.lbl_empty.setObjectName("muted")
        self.lbl_empty.setWordWrap(True)
        v.addWidget(self.lbl_empty)
        return box

    def _build_right(self):
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        v.addWidget(_cap("② 导出内容"))
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        self.right_host = QWidget()
        self._fill_content(self.right_host)     # 建控件（属性名跟原来一样挂在 win 上）
        area.setWidget(self.right_host)
        v.addWidget(area, 1)
        return box

    def _fill_content(self, host):
        """导出内容控件：从右栏「导出内容」卡片原样搬过来，只换了容器。"""
        win = self.win
        lay = QVBoxLayout(host)
        lay.setContentsMargins(2, 0, 10, 0)
        lay.setSpacing(6)

        # ---- 常用：彩色合并 / 逐通道彩图
        lay.addWidget(_cap("常用", "cardHint"))
        win.chk_merge = FlipSwitch()
        win.chk_merge.setChecked(win.settings.exp_merge)
        win.chk_merge.toggled.connect(win.on_any_setting)
        lay.addLayout(win._switch_row(win.chk_merge, "合并彩色图（Merge）"))
        win.chk_ch = []
        for i, text in enumerate(("CH1 单独一张", "CH2 单独一张", "CH3 单独一张")):
            sw = FlipSwitch()
            sw.setChecked(bool(win.settings.exp_ch[i]) if i < len(win.settings.exp_ch) else False)
            sw.toggled.connect(win.on_any_setting)
            win.chk_ch.append(sw)
            lay.addLayout(win._switch_row(sw, text))

        # ---- 原始位深（P0-2）
        lay.addWidget(_cap("原始位深", "cardHint"))
        win.chk_raw = FlipSwitch()
        win.chk_raw.setChecked(bool(win.settings.exp_raw_single))
        win.chk_raw.toggled.connect(win.on_any_setting)
        lay.addLayout(win._switch_row(win.chk_raw, "单通道原始位深（8/16bit，不烘焙）"))
        win.chk_raw_stack = FlipSwitch()
        win.chk_raw_stack.setChecked(bool(win.settings.exp_raw_stack))
        win.chk_raw_stack.toggled.connect(win.on_any_setting)
        lay.addLayout(win._switch_row(win.chk_raw_stack, "多通道栈原始位深（一个文件装全部通道）"))
        win.chk_raw_ome = FlipSwitch()
        win.chk_raw_ome.setChecked(bool(win.settings.exp_raw_ome))
        win.chk_raw_ome.toggled.connect(win.on_any_setting)
        lay.addLayout(win._switch_row(win.chk_raw_ome, "含 OME-XML 元数据"))
        win.chk_raw_embed = FlipSwitch()
        win.chk_raw_embed.setChecked(bool(win.settings.exp_raw_embed))
        win.chk_raw_embed.toggled.connect(win.on_any_setting)
        lay.addLayout(win._switch_row(win.chk_raw_embed, "内嵌可还原的原始数据"))

        # ---- 其他
        lay.addWidget(_cap("其他", "cardHint"))
        win.chk_proj = FlipSwitch()
        win.chk_proj.setChecked(bool(getattr(win.settings, "exp_proj", False)))
        win.chk_proj.toggled.connect(win.on_any_setting)
        lay.addLayout(win._switch_row(win.chk_proj, "Z 投影图（另出 _MIP）"))
        win.chk_proj.setToolTip("开着 Z 投影时，额外出一张投影图（原图的大小与视野不变）")
        for w, tip in ((win.chk_raw, "逐通道导出灰度 TIFF，像素值原样，显示区间不烘焙；导出始终 1×（不用放大）"),
                       (win.chk_raw_stack, "把全部通道（不受上面 CH1~CH3 限制）装进一个 TIFF"),
                       (win.chk_raw_ome, "写物理像素尺寸 / 通道名 / 激发发射波长，Fiji 和 Imaris 认这份元数据"),
                       (win.chk_raw_embed, "做过处理（配准/扣背景/去卷积）时，把处理前的原始像素一起写进同一个 TIFF，"
                                           "以后能一键还原到未处理状态；处理链为空时不写、不占体积"),
                       ):
            w.setToolTip(tip)

        # ---- 范围：格式 / 后缀 / Z 层 / 时间点（Z 与 T 各选各的，P0-3 3.18.5）
        lay.addWidget(_cap("范围", "cardHint"))
        win.cb_format = QComboBox()
        win.cb_format.setObjectName("field")
        win.cb_format.addItems(["跟随原图", "PNG", "TIFF", "JPG"])
        win.cb_format.setCurrentIndex(["follow", "png", "tiff", "jpg"].index(win.settings.out_format))
        win.cb_format.currentIndexChanged.connect(win.on_any_setting)
        win.ed_suffix = QLineEdit(win.settings.out_suffix)
        win.ed_suffix.setObjectName("field")
        win.ed_suffix.editingFinished.connect(win.on_any_setting)
        fs2 = QHBoxLayout()
        fs2.setSpacing(6)
        fs2.addWidget(_cap("格式", "cardHint"))
        fs2.addWidget(win.cb_format, 1)
        fs2.addWidget(_cap("后缀", "cardHint"))
        fs2.addWidget(win.ed_suffix, 1)
        lay.addLayout(fs2)
        win.cb_zmode = QComboBox()
        win.cb_zmode.setObjectName("field")
        win.cb_zmode.addItems(["只出当前 Z 层", "出全部 Z 层", "只出指定 Z 层"])
        win.cb_zmode.setCurrentIndex(["current", "all", "pick"].index(
            getattr(win.settings, "z_mode", "current")))
        win.cb_zmode.currentIndexChanged.connect(win.on_any_setting)
        win.ed_zpick = QLineEdit(getattr(win.settings, "z_pick", ""))
        win.ed_zpick.setObjectName("field")
        win.ed_zpick.setPlaceholderText("指定 Z 层，如 1,5,12 或 1-10")
        win.ed_zpick.editingFinished.connect(win.on_any_setting)
        zr = QHBoxLayout()
        zr.setSpacing(6)
        zr.addWidget(_cap("Z 层", "cardHint"))
        zr.addWidget(win.cb_zmode, 1)
        lay.addLayout(zr)
        lay.addWidget(win.ed_zpick)
        win.cb_frames = QComboBox()
        win.cb_frames.setObjectName("field")
        win.cb_frames.addItems(["只出当前时间点", "出全部时间点", "只出指定时间点"])
        win.cb_frames.setCurrentIndex(["current", "all", "pick"].index(win.settings.frames_mode))
        win.cb_frames.currentIndexChanged.connect(win.on_any_setting)
        win.ed_pick = QLineEdit(win.settings.frame_pick)
        win.ed_pick.setObjectName("field")
        win.ed_pick.setPlaceholderText("指定时间点，如 1,5,12 或 1-10")
        win.ed_pick.editingFinished.connect(win.on_any_setting)
        fr = QHBoxLayout()
        fr.setSpacing(6)
        fr.addWidget(_cap("时间点", "cardHint"))
        fr.addWidget(win.cb_frames, 1)
        lay.addLayout(fr)
        lay.addWidget(win.ed_pick)

        # ---- 输出位置
        lay.addWidget(_cap("输出", "cardHint"))
        win.ed_outdir = QLineEdit(win.settings.__dict__.get("out_dir", paths.OUTPUT_DIR))
        win.ed_outdir.setObjectName("field")
        b_out = BrutalButton("输出目录", compact=True)
        b_out.clicked.connect(win.pick_outdir)
        od = QHBoxLayout()
        od.setSpacing(6)
        od.addWidget(win.ed_outdir, 1)
        od.addWidget(b_out)
        lay.addLayout(od)
        lay.addStretch(1)

    # ------------------------------------------------------------ 填 / 读树
    @staticmethod
    def _blocked_reason(it):
        """这张为什么不能导出（None = 可以导）。跟 _build_jobs 的过滤条件保持一致。"""
        if getattr(it, "missing", False):
            return "原文件找不到"
        if it.umpp <= 0:
            return "未标定"
        return None

    def _frame_text(self, it):
        try:
            n = len(self.win._frames_for(it))
        except Exception:                            # noqa: BLE001
            n = 1
        return "%d 帧" % n if n > 1 else ""

    def _fill_tree(self, groups):
        self.tree.blockSignals(True)
        self.tree.clear()
        self._rows, self._groups = {}, {}
        n_ok = n_bad = 0
        for g in groups:
            head = QTreeWidgetItem([g.title, "%d 张" % len(g.images)])
            head.setFlags(head.flags() | Qt.ItemIsUserCheckable)
            head.setCheckState(0, Qt.Checked)
            self.tree.addTopLevelItem(head)
            self._groups[g.gid] = head
            for it in g.images:
                why = self._blocked_reason(it)
                name = it.name if not why else "%s（%s）" % (it.name, why)
                row = QTreeWidgetItem([name, self._frame_text(it)])
                if why:
                    n_bad += 1
                    # 注意：QTreeWidgetItem 默认就带 ItemIsUserCheckable，
                    # 这里必须**显式去掉**，否则灰行也能被勾上（自检 [1] 抓到过）。
                    row.setFlags(Qt.ItemIsSelectable)
                    row.setForeground(0, QBrush(GREY))
                    row.setForeground(1, QBrush(GREY))
                    row.setToolTip(0, "%s —— 先修好才能导出" % why)
                else:
                    n_ok += 1
                    row.setFlags(row.flags() | Qt.ItemIsUserCheckable)
                    row.setCheckState(0, Qt.Checked)
                    row.setToolTip(0, it.note or it.path)
                head.addChild(row)
                self._rows[it.path] = (row, it, g)
            head.setExpanded(True)
        self.tree.blockSignals(False)
        self.lbl_empty.setText(("可导出 %d 张" % n_ok) if n_ok else
                               "没有可导出的图：先补齐标定（µm/px），或者等自动识别完成")
        if n_bad:
            self.lbl_empty.setText(self.lbl_empty.text() + " · 有 %d 张不能导（见灰色行）" % n_bad)

    def _picked_rows(self):
        out = []
        for path, (row, it, g) in self._rows.items():
            if row.checkState(0) == Qt.Checked:
                out.append((it, g))
        return out

    # ------------------------------------------------------------ 交互
    def _on_item_changed(self, row, _col):
        if self._quiet:
            return
        self._quiet = True
        try:
            if row.parent() is None:                      # 组节点 → 组内全同步
                state = row.checkState(0)
                if state != Qt.PartiallyChecked:
                    for i in range(row.childCount()):
                        ch = row.child(i)
                        if ch.flags() & Qt.ItemIsUserCheckable:
                            ch.setCheckState(0, state)
            else:                                         # 图节点 → 回填组的三态
                head = row.parent()
                picked = [head.child(i).checkState(0) for i in range(head.childCount())
                          if head.child(i).flags() & Qt.ItemIsUserCheckable]
                if not picked:
                    head.setCheckState(0, Qt.Unchecked)
                elif all(s == Qt.Checked for s in picked):
                    head.setCheckState(0, Qt.Checked)
                elif all(s == Qt.Unchecked for s in picked):
                    head.setCheckState(0, Qt.Unchecked)
                else:
                    head.setCheckState(0, Qt.PartiallyChecked)
        finally:
            self._quiet = False
        self._refresh_summary()

    def _set_all(self, mode):
        self._quiet = True
        try:
            for head in self._groups.values():
                for i in range(head.childCount()):
                    ch = head.child(i)
                    if not (ch.flags() & Qt.ItemIsUserCheckable):
                        continue
                    if mode == "all":
                        ch.setCheckState(0, Qt.Checked)
                    elif mode == "none":
                        ch.setCheckState(0, Qt.Unchecked)
                    else:
                        ch.setCheckState(0, Qt.Unchecked if ch.checkState(0) == Qt.Checked
                                         else Qt.Checked)
                picked = [head.child(i).checkState(0) for i in range(head.childCount())
                          if head.child(i).flags() & Qt.ItemIsUserCheckable]
                if not picked:
                    head.setCheckState(0, Qt.Unchecked)
                elif all(s == Qt.Checked for s in picked):
                    head.setCheckState(0, Qt.Checked)
                elif all(s == Qt.Unchecked for s in picked):
                    head.setCheckState(0, Qt.Unchecked)
                else:
                    head.setCheckState(0, Qt.PartiallyChecked)
        finally:
            self._quiet = False
        self._refresh_summary()

    def select_all(self):
        self._set_all("all")

    def select_none(self):
        self._set_all("none")

    def invert(self):
        self._set_all("flip")

    def _refresh_summary(self):
        """底部那行：几张 → 几个文件。算法跟 refresh_manifest 一模一样（不另写一套）。"""
        picked = self._picked_rows()
        st = self.win._sync_settings()
        variants = (1 if st.exp_merge else 0) + sum(1 for x in st.exp_ch if x)
        files = 0
        for it, _g in picked:
            try:
                nf = len(self.win._frames_for(it))
            except Exception:                            # noqa: BLE001
                nf = 1
            files += nf * variants
            if st.exp_raw_single:
                files += nf * max(1, len(it.channels or []))
            if st.exp_raw_stack:
                files += nf
        self.right_host.setEnabled(bool(picked))
        self.btn_go.setEnabled(bool(picked))
        if not picked:
            self.lbl_sum.setText("还没勾图 —— 先把左边要导出的图勾上（导出内容随后可选）")
            return
        self.lbl_sum.setText(
            "已选 %d 组 · %d 张 → 预计 %d 个文件 · 输出 %s"
            % (len({g.gid for _it, g in picked}), len(picked), files,
               st.out_dir or paths.OUTPUT_DIR))

    # ------------------------------------------------------------ 对外
    def pick(self, groups, focus_item=None):
        """打开对话框。返回选中的 [(item, group)]；用户取消返回 None。"""
        self._fill_tree(groups)
        if focus_item is not None and focus_item.path in self._rows:
            self.tree.scrollToItem(self._rows[focus_item.path][0])
        self._refresh_summary()
        if not self._picked_rows():
            # 一张能导的都没有：直接告诉用户，别让他对着空列表点
            self.btn_go.setEnabled(False)
        if self.exec() != QDialog.Accepted:
            return None
        return self._picked_rows()
