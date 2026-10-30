# -*- coding: utf-8 -*-
"""预览画布：合成图 + 可拖动裁剪框 + 可拖动的新标尺。

视图只有一套坐标：self._view_um 表示"当前屏幕上显示图片的哪一块（µm）"。
放大/缩小/平移都直接改它；预览图（pixmap）只覆盖其中一块，按物理范围贴上去。
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

ACCENT = QColor("#5B5BD6")


class CropCanvas(QWidget):
    box_changed = Signal()
    box_committed = Signal()
    box_drag_started = Signal()              # 开始拖裁剪框（撤销栈在这一刻取快照）
    view_changed = Signal()                  # 缩放 / 平移 / 尺寸变了
    bar_dragged = Signal(str, float, float)  # ("bar"/"text", 归一化 x, y)
    bar_drag_done = Signal()                 # 标尺拖动结束（撤销栈在这一次提交）
    roi_done = Signal(str, float, float, float, float)   # 画完 ROI：(kind, x0,y0,x1,y1)
    roi_selected = Signal(str)               # 选中/取消选中 ROI（空串 = 没选中）
    roi_edited = Signal(str, object)         # 拖完 ROI：(rid, [[nx,ny],…] 原图归一化)
    roi_delete = Signal(str)                 # 按 Delete 删掉选中的 ROI
    roi_drag_started = Signal()              # 开始拖 ROI（撤销栈在这一刻取快照）
    roi_menu = Signal(str, object)           # 在 ROI 上点右键：(rid, 全局坐标)
    roi_mode_changed = Signal(str)           # 当前armed的画 ROI 工具（空串 = 没armed）
    line_done = Signal(float, float, float, float)   # 画线标定：两点归一化坐标

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(200, 200)
        self.setMouseTracking(True)
        self._pix = None
        self._base = None
        self._base_um = None
        self._overlay = None
        self._buf = None
        self._field = (100.0, 100.0)               # 整张图的物理宽高（µm）
        self._view_um = (0.0, 0.0, 100.0, 100.0)   # 屏幕正在显示的物理范围
        self._pix_um = None                        # 当前预览图覆盖的物理范围
        self._box = dict(x=35.0, y=35.0, w=30.0, h=30.0)
        self._lock = True
        self._drag = None
        self._pan = None
        self._show_box = True
        self.max_zoom = 20.0
        self._bar_zones = None
        self._bar_anchors = None
        self._bar_drag = None
        self._line_mode = False
        self._line = []                 # 归一化坐标（相对显示图）
        self._line_px = 0.0             # 原图像素长度（主窗口算完回填）
        self._detect = None             # 标尺识别结果标记（规格书 5.4.6）
        self._roi_kind = ""             # 正在画 ROI 的形状（"" = 不在画）
        self._roi_drag = None           # (x0, y0) 归一化起点
        # ROI 叠加：每个是 dict(kind, pts=[(nx,ny)…], label, bg, rid)；
        # 坐标一律是**原图整帧归一化**，绘制时经 norm_to_view() 换算
        # （历史 bug：以前直接拿整帧坐标当"可见区坐标"画，一放大就跑到角落去）
        self._roi_shapes = []
        self._roi_sel = ""              # 当前选中的 ROI rid
        self._roi_op = None             # 正在拖/缩 ROI 的操作
        self.setFocusPolicy(Qt.StrongFocus)      # 点一下图才能按 Delete 删 ROI

    # ---------------------------------------------------------- 外部接口
    def set_image(self, rgb: np.ndarray, dpr=1.0):
        self._buf = np.ascontiguousarray(rgb)
        h, w = self._buf.shape[:2]
        img = QImage(self._buf.data, w, h, 3 * w, QImage.Format_RGB888)
        pm = QPixmap.fromImage(img)
        try:
            pm.setDevicePixelRatio(float(dpr))
        except Exception:                        # noqa: BLE001
            pass
        self._pix = pm
        self.update()

    def set_base_image(self, rgb, dpr=1.0, pix_um=None):
        """整图底图：缩放时先铺满，避免出现黑屏。"""
        if rgb is None:
            self._base = None
            self._base_um = None
        else:
            arr = np.ascontiguousarray(rgb)
            h, w = arr.shape[:2]
            img = QImage(arr.data, w, h, 3 * w, QImage.Format_RGB888)
            pm = QPixmap.fromImage(img)
            try:
                pm.setDevicePixelRatio(float(dpr))
            except Exception:                    # noqa: BLE001
                pass
            self._base = pm
            self._base_um = pix_um
        self.update()

    def set_overlay(self, rgba, dpr=1.0):
        if rgba is None:
            self._overlay = None
        else:
            arr = np.ascontiguousarray(rgba)
            h, w = arr.shape[:2]
            img = QImage(arr.data, w, h, 4 * w, QImage.Format_RGBA8888)
            pm = QPixmap.fromImage(img)
            try:
                pm.setDevicePixelRatio(float(dpr))
            except Exception:                    # noqa: BLE001
                pass
            self._overlay = pm
        self.update()

    def set_field(self, field_w, field_h=None):
        """整图的物理宽高；换图片时自动回到整图视图。"""
        fw = max(1e-6, float(field_w))
        fh = max(1e-6, float(field_h if field_h else field_w))
        if abs(fw - self._field[0]) > 1e-6 or abs(fh - self._field[1]) > 1e-6:
            self._field = (fw, fh)
            self._view_um = (0.0, 0.0, fw, fh)
        self.update()

    def set_pix_um(self, ox, oy, sx, sy):
        """刚渲染好的预览图覆盖的物理范围。"""
        self._pix_um = (float(ox), float(oy), max(1e-6, float(sx)), max(1e-6, float(sy)))

    def set_bar_zones(self, bar_rect, text_rect, bar_anchor, text_anchor, size):
        self._bar_zones = {"bar": bar_rect, "text": text_rect}
        self._bar_anchors = {"bar": bar_anchor, "text": text_anchor, "size": size}

    def clear_bar_zones(self):
        self._bar_zones = None
        self._bar_anchors = None

    def set_box(self, box):
        self._box = dict(box)
        self.update()

    # ---------------------------------------------------------- 画线标定
    def set_line_mode(self, on):
        self._line_mode = bool(on)
        if not self._line_mode:
            self._line = []
        self.setCursor(Qt.CrossCursor if self._line_mode else Qt.ArrowCursor)
        self.update()

    def line_mode(self):
        return self._line_mode

    def clear_line(self):
        self._line = []
        self.update()

    def set_line(self, n0, n1, px=0.0):
        """外部预填一条线（归一化坐标，相对当前显示图）。给「不对，手动框」用。"""
        self._line = [tuple(n0), tuple(n1)]
        if px:
            self._line_px = float(px)
        self.update()

    def set_detect(self, info):
        """标尺识别结果标记：info = {p0, p1, label, conf} 或 None。

        p0/p1 是**原图**归一化坐标；绘制时才换算到当前显示图，所以缩放/平移后
        线会跟着图走（这正是"识别到哪根线"要的观感）。
        """
        self._detect = info
        self.update()

    # ---------------------------------------------------------- ROI（P1-6）
    def set_roi_mode(self, kind):
        """armed 一个画 ROI 的工具。

        2026-09-28 用户要求：**点一次就一直能画**（不用每画一个再点一次工具）。
        所以这里不再"画完自动解除"，要退出就再点一次同一个工具、或按 Esc。
        已经 armed 时再点同一个 → 取消 armed。
        """
        kind = str(kind or "")
        if kind and kind == self._roi_kind:
            kind = ""
        self._roi_kind = kind
        self._roi_drag = None
        self.setCursor(Qt.CrossCursor if self._roi_kind else Qt.ArrowCursor)
        self.roi_mode_changed.emit(self._roi_kind)
        self.update()

    def roi_mode(self):
        return self._roi_kind

    def set_rois(self, shapes):
        """叠加显示 ROI。

        shapes = [(kind, [[nx,ny],…], label[, is_bg[, rid]])]，
        坐标是**原图整帧**归一化（0~1），不是"当前可见区"。
        """
        out = []
        for sh in (shapes or []):
            kind = sh[0]
            pts = [tuple(float(v) for v in p) for p in (sh[1] or [])]
            out.append(dict(kind=kind, pts=pts,
                            label=(sh[2] if len(sh) > 2 else ""),
                            bg=bool(sh[3]) if len(sh) > 3 else False,
                            rid=(str(sh[4]) if len(sh) > 4 else "")))
        self._roi_shapes = out
        if self._roi_sel and not any(s["rid"] == self._roi_sel for s in out):
            self._roi_sel = ""            # 选中的那个被删了
        self.update()

    def set_roi_sel(self, rid):
        rid = str(rid or "")
        if rid != self._roi_sel:
            self._roi_sel = rid
            self.update()

    def center_on_frac(self, fx, fy):
        """把视图中心挪到整图归一化坐标 (fx, fy) —— 列表里点某个 ROI 时用。

        已经在可视范围内的不动视图（不然每点一下都跳一下）。
        """
        fw, fh = self._field
        cx, cy = float(fx) * fw, float(fy) * fh
        vx, vy, vw, vh = self._view_um
        if vx <= cx <= vx + vw and vy <= cy <= vy + vh:
            return False
        self._set_view_center(cx, cy, vw, 0.5, 0.5)
        self.update()
        self.view_changed.emit()
        return True

    def roi_sel(self):
        return self._roi_sel

    def view_to_norm(self, u, v):
        """当前显示图归一化 → 原图整帧归一化（norm_to_view 的逆）。"""
        p = self._pix_um
        if p is None:
            return (float(u), float(v))
        ox, oy, sx, sy = p
        fw, fh = self._field
        return ((ox + float(u) * sx) / max(1e-9, fw),
                (oy + float(v) * sy) / max(1e-9, fh))

    def _frame_pt(self, pos):
        """控件坐标 → 原图整帧归一化坐标。"""
        u, v = self._norm_of(pos)
        return self.view_to_norm(u, v)

    def _roi_screen(self, sh):
        """ROI 在控件上的两个对角点（QPointF）。点 ROI 只有一个点 → 返回同一个点两次。"""
        pts = sh["pts"]
        if not pts:
            return None
        if len(pts) == 1:
            p = self._pt_of(self.norm_to_view(*pts[0]))
            return p, p
        a = self._pt_of(self.norm_to_view(*pts[0]))
        b = self._pt_of(self.norm_to_view(*pts[-1]))
        return a, b

    def _roi_hit(self, pos):
        """点在哪条 ROI 上：返回 (rid, mode)。mode: move / nw / ne / sw / se / p0 / p1。"""
        k = 10
        for sh in reversed(self._roi_shapes):
            if not sh["rid"] or not sh["pts"]:      # 点 ROI 只有一个点，不能当"无效"跳过
                continue
            sc = self._roi_screen(sh)
            if sc is None:
                continue
            a, b = sc
            if sh["kind"] == "point":
                # 点 ROI：靠近那个点就算命中（好点、好拖）
                if abs(pos.x() - a.x()) <= 9 and abs(pos.y() - a.y()) <= 9:
                    return sh["rid"], "move"
                continue
            if sh["kind"] == "line":
                for tag, pt in (("p0", a), ("p1", b)):
                    if (abs(pos.x() - pt.x()) <= k and abs(pos.y() - pt.y()) <= k):
                        return sh["rid"], tag
                if self._near_segment(pos, a, b):
                    return sh["rid"], "move"
                continue
            r = QRect(int(min(a.x(), b.x())), int(min(a.y(), b.y())),
                      max(2, int(abs(b.x() - a.x()))), max(2, int(abs(b.y() - a.y()))))
            near = {"nw": QRect(r.left() - k, r.top() - k, 2 * k, 2 * k),
                    "ne": QRect(r.right() - k, r.top() - k, 2 * k, 2 * k),
                    "sw": QRect(r.left() - k, r.bottom() - k, 2 * k, 2 * k),
                    "se": QRect(r.right() - k, r.bottom() - k, 2 * k, 2 * k)}
            for mode, box in near.items():
                if box.contains(pos):
                    return sh["rid"], mode
            if r.contains(pos):
                return sh["rid"], "move"
        return None

    @staticmethod
    def _near_segment(pos, a, b, tol=9.0):
        """点到线段的距离（像素）。"""
        dx, dy = b.x() - a.x(), b.y() - a.y()
        L2 = dx * dx + dy * dy
        if L2 <= 1e-9:
            return (pos.x() - a.x()) ** 2 + (pos.y() - a.y()) ** 2 <= tol * tol
        t = max(0.0, min(1.0, ((pos.x() - a.x()) * dx + (pos.y() - a.y()) * dy) / L2))
        px, py = a.x() + t * dx, a.y() + t * dy
        return (pos.x() - px) ** 2 + (pos.y() - py) ** 2 <= tol * tol

    def _roi_apply_drag(self, cur):
        """把鼠标当前位置换算成 ROI 的新坐标（原图归一化），边拖边更新本地副本。"""
        op = self._roi_op
        sh = next((s for s in self._roi_shapes if s["rid"] == op["rid"]), None)
        if sh is None or not op["pts"]:
            return
        dx = cur[0] - op["start"][0]
        dy = cur[1] - op["start"][1]
        mode = op["mode"]
        p0, p1 = op["pts"][0], op["pts"][-1]

        def cl(v):
            return min(max(float(v), 0.0), 1.0)

        if sh["kind"] == "point":
            pts = [(cl(p0[0] + dx), cl(p0[1] + dy))]      # 点就只有位置
        elif sh["kind"] == "line":
            if mode == "p0":
                pts = [(cl(p0[0] + dx), cl(p0[1] + dy)), p1]
            elif mode == "p1":
                pts = [p0, (cl(p1[0] + dx), cl(p1[1] + dy))]
            else:
                pts = [(cl(p0[0] + dx), cl(p0[1] + dy)),
                       (cl(p1[0] + dx), cl(p1[1] + dy))]
        else:
            l, t = min(p0[0], p1[0]), min(p0[1], p1[1])
            r, b = max(p0[0], p1[0]), max(p0[1], p1[1])
            if mode == "move":                     # 整体平移，不许出界
                if l + dx < 0.0:
                    dx = -l
                if t + dy < 0.0:
                    dy = -t
                if r + dx > 1.0:
                    dx = 1.0 - r
                if b + dy > 1.0:
                    dy = 1.0 - b
                l, r, t, b = l + dx, r + dx, t + dy, b + dy
            else:                                  # 四角缩放：对角固定
                if "e" in mode:
                    r = min(max(r + dx, l + 0.004), 1.0)
                if "w" in mode:
                    l = max(min(l + dx, r - 0.004), 0.0)
                if "s" in mode:
                    b = min(max(b + dy, t + 0.004), 1.0)
                if "n" in mode:
                    t = max(min(t + dy, b - 0.004), 0.0)
            pts = [(l, t), (r, b)]
        sh["pts"] = pts
        self.update()


    def norm_to_view(self, fx, fy):
        """原图归一化坐标 → 当前显示图的归一化坐标（_pix_um 覆盖的那块）。"""
        p = self._pix_um
        if p is None:
            return (float(fx), float(fy))
        ox, oy, sx, sy = p
        return ((fx * self._field[0] - ox) / max(1e-9, sx),
                (fy * self._field[1] - oy) / max(1e-9, sy))

    def _norm_of(self, pos):
        r = self._view_rect()
        if r.width() <= 0 or r.height() <= 0:
            return (0.0, 0.0)
        return ((pos.x() - r.left()) / float(r.width()),
                (pos.y() - r.top()) / float(r.height()))

    def _pt_of(self, n):
        r = self._view_rect()
        return QPointF(r.left() + n[0] * r.width(), r.top() + n[1] * r.height())

    def box(self):
        return dict(self._box)

    def set_lock(self, lock):
        self._lock = bool(lock)

    def set_show_box(self, show):
        self._show_box = bool(show)
        self.update()

    # ---------------------------------------------------------- 视图控制
    def view_um(self):
        return self._view_um

    def zoom(self):
        return self._field[0] / max(1e-6, self._view_um[2])

    def view_scale(self):
        """图像物理尺寸 → 控件像素（裁剪结果视图里会用到）。"""
        p = self._pix_um
        if p is None:
            return 1.0
        r = self._view_rect()
        return r.width() / max(1e-6, p[2])

    def disp_scale(self, disp_w):
        """预览图自身的像素 → 控件像素（画标尺命中区时用）。"""
        return self._view_rect().width() / max(1.0, float(disp_w))

    def set_zoom(self, zoom, anchor=None):
        """zoom=1 表示整图；anchor 是控件坐标（默认画面中心）。"""
        z = min(max(float(zoom), 1.0), self.max_zoom)
        vx, vy, vw, vh = self._view_um
        size = self._field[0] / z
        if anchor is not None:
            px0, py0, k = self._px_map()
            u = min(max((anchor.x() - px0) / max(1e-9, vw * k), 0.0), 1.0)
            v = min(max((anchor.y() - py0) / max(1e-9, vh * k), 0.0), 1.0)
            self._set_view_center(vx + u * vw, vy + v * vh, size, u, v)
        else:
            self._set_view_center(vx + vw / 2.0, vy + vh / 2.0, size, 0.5, 0.5)
        self.update()
        self.view_changed.emit()

    def _set_view_center(self, cx, cy, size, u=0.5, v=0.5):
        """视图 = 以 (cx,cy) 为锚点、物理边长为 size；u/v 是锚点落在画面里的相对位置。"""
        fw, fh = self._field
        size = min(max(size, fw / self.max_zoom), fw)
        sw = size
        sh = size * fh / fw                    # 保持图片比例
        if u <= 0.0:
            vx = cx - u * sw
        else:
            vx = cx - u * sw
        vy = cy - v * sh
        vx = min(max(vx, 0.0), max(0.0, fw - sw))
        vy = min(max(vy, 0.0), max(0.0, fh - sh))
        self._view_um = (vx, vy, sw, sh)

    def reset_view(self):
        self._view_um = (0.0, 0.0, self._field[0], self._field[1])
        self.update()
        self.view_changed.emit()

    def wheelEvent(self, ev):
        """滚轮缩放（以鼠标位置为锚点；放大上限 self.max_zoom）。"""
        if self._pix is None:
            return
        steps = ev.angleDelta().y() / 120.0
        if not steps:
            return
        factor = 1.15 ** steps
        pos = ev.position()
        vx, vy, vw, vh = self._view_um
        px0, py0, k = self._px_map()
        u = min(max((pos.x() - px0) / max(1e-9, vw * k), 0.0), 1.0)
        v = min(max((pos.y() - py0) / max(1e-9, vh * k), 0.0), 1.0)
        cx = vx + u * vw
        cy = vy + v * vh
        self._set_view_center(cx, cy, vw / factor, u, v)
        self.update()
        self.view_changed.emit()
        ev.accept()

    def visible_rect_norm(self):
        """屏幕显示部分在整图里的归一化范围 (x0, y0, x1, y1)。"""
        vx, vy, vw, vh = self._view_um
        fw, fh = self._field
        x0 = min(max(vx / fw, 0.0), 1.0)
        y0 = min(max(vy / fh, 0.0), 1.0)
        x1 = min(max((vx + vw) / fw, 0.0), 1.0)
        y1 = min(max((vy + vh) / fh, 0.0), 1.0)
        if x1 - x0 < 1e-4 or y1 - y0 < 1e-4:
            return (0.0, 0.0, 1.0, 1.0)
        return (x0, y0, x1, y1)

    # ---------------------------------------------------------- 坐标换算
    def _view_rect(self):
        return self._rect_for(self._pix_um)

    def _rect_for(self, pum):
        """当前预览图在控件里的绘制矩形（按它覆盖的物理范围算）。"""
        if pum is None:
            return QRect(0, 0, self.width(), self.height())
        ox, oy, sx, sy = pum
        px0, py0, k = self._px_map()
        x = px0 + (ox - self._view_um[0]) * k
        y = py0 + (oy - self._view_um[1]) * k
        w = sx * k
        h = sy * k
        return QRect(int(round(x)), int(round(y)),
                     max(1, int(round(w))), max(1, int(round(h))))

    def _px_map(self):
        """(画布内左上角像素, 缩放比例)：等比缩放，非正方形图自动留边。"""
        vx, vy, vw, vh = self._view_um
        k = min(self.width() / max(1e-9, vw), self.height() / max(1e-9, vh))
        px0 = (self.width() - vw * k) / 2.0
        py0 = (self.height() - vh * k) / 2.0
        return px0, py0, k

    def _um_to_px(self, v):
        px0, _py0, k = self._px_map()
        return px0 + (v - self._view_um[0]) * k

    def _um_to_px_y(self, v):
        _px0, py0, k = self._px_map()
        return py0 + (v - self._view_um[1]) * k

    def _um_len_to_px(self, v):
        return v * self._px_map()[2]

    def _um_len_to_px_y(self, v):
        return v * self._px_map()[2]

    def _px_to_um(self, v):
        return v / max(1e-9, self._px_map()[2])

    def _px_to_um_y(self, v):
        return v / max(1e-9, self._px_map()[2])

    def _box_rect(self):
        b = self._box
        return QRect(int(self._um_to_px(b["x"])), int(self._um_to_px_y(b["y"])),
                     max(4, int(self._um_len_to_px(b["w"]))),
                     max(4, int(self._um_len_to_px_y(b["h"]))))

    def _hit(self, pos):
        if not self._show_box:
            return None
        r = self._box_rect()
        k = 10
        near = {
            "nw": QRect(r.left() - k, r.top() - k, 2 * k, 2 * k),
            "ne": QRect(r.right() - k, r.top() - k, 2 * k, 2 * k),
            "sw": QRect(r.left() - k, r.bottom() - k, 2 * k, 2 * k),
            "se": QRect(r.right() - k, r.bottom() - k, 2 * k, 2 * k),
        }
        for name, rect in near.items():
            if rect.contains(pos):
                return name
        return "move" if r.contains(pos) else None

    def _bar_hit(self, pos):
        if not self._bar_zones:
            return None
        for kind in ("bar", "text"):          # 线优先：贴着线的文字不去抢
            rect = self._bar_zones.get(kind)
            if rect is not None and rect.adjusted(-8, -8, 8, 8).contains(pos):
                return kind
        return None

    # ---------------------------------------------------------- 交互
    def mousePressEvent(self, ev):
        pos = ev.position().toPoint()
        self.setFocus(Qt.MouseFocusReason)
        if self._roi_kind and ev.button() == Qt.LeftButton:
            # armed 着工具时点到已有 ROI：不画新的，改成选中它（这样还能接着拖）
            hit0 = self._roi_hit(pos)
            if hit0 is not None:
                rid0 = hit0[0]
                self._roi_kind = ""
                self.roi_mode_changed.emit("")
                self.setCursor(Qt.ArrowCursor)
                self._roi_sel = rid0
                self.roi_selected.emit(rid0)
                self._roi_op = dict(rid=rid0, mode=hit0[1], start=self._frame_pt(pos),
                                    pts=[tuple(p) for p in
                                         next((s for s in self._roi_shapes
                                               if s["rid"] == rid0), {"pts": []})["pts"]])
                self.roi_drag_started.emit()
                self.update()
                return
            if self._roi_kind == "point":
                # 点工具：按一下就在那个位置落一个点（不用拖）
                u, v = self._norm_of(ev.position())
                self.roi_done.emit("point", u, v, u, v)
                self.update()
                return
            self._roi_drag = self._norm_of(ev.position())
            self.update()
            return
        if self._line_mode and ev.button() == Qt.LeftButton:
            self._line.append(self._norm_of(ev.position()))
            if len(self._line) >= 2:
                self._line = self._line[-2:]
                self.line_done.emit(self._line[0][0], self._line[0][1],
                                    self._line[1][0], self._line[1][1])
            self.update()
            return
        if ev.button() == Qt.LeftButton:
            kind = self._bar_hit(pos)
            if kind and self._bar_anchors:
                self._bar_drag = dict(kind=kind, start=pos,
                                      anchor=self._bar_anchors.get(kind))
                return
            # ROI 优先于裁剪框：点在图上的 ROI 就是要拖它（P1-6 2026-09-26）
            hit = self._roi_hit(pos)
            if hit is not None:
                rid, mode = hit
                if rid != self._roi_sel:
                    self._roi_sel = rid
                    self.roi_selected.emit(rid)
                sh = next((s for s in self._roi_shapes if s["rid"] == rid), None)
                if sh is not None:
                    self._roi_op = dict(rid=rid, mode=mode, start=self._frame_pt(pos),
                                        pts=[tuple(p) for p in sh["pts"]])
                    self.roi_drag_started.emit()      # 撤销栈在改动前取快照
                self.update()
                return
            if self._roi_sel:                          # 点空白处 = 取消选中
                self._roi_sel = ""
                self.roi_selected.emit("")
                self.update()
        if ev.button() == Qt.MiddleButton:
            if self.zoom() > 1.0001:
                self._pan = dict(start=pos, view=self._view_um)
            return
        if ev.button() != Qt.LeftButton:
            return
        hit = self._hit(pos)
        if not hit:
            if self.zoom() > 1.0001:
                self._pan = dict(start=pos, view=self._view_um)
            return
        self._drag = dict(mode=hit, start=pos, box=dict(self._box))
        self.box_drag_started.emit()          # 拖之前的状态要先记下来

    def mouseMoveEvent(self, ev):
        pos = ev.position().toPoint()
        if self._roi_drag is not None:
            self.update()
            return
        if self._roi_op is not None:
            self._roi_apply_drag(self._frame_pt(ev.position()))
            return
        if self._bar_drag is not None:
            d = self._bar_drag
            size = self._bar_anchors.get("size") or (self.width(), self.height())
            anchor = d.get("anchor") or (0.5, 0.5)
            nx = anchor[0] + (pos.x() - d["start"].x()) / max(1.0, float(size[0]))
            ny = anchor[1] + (pos.y() - d["start"].y()) / max(1.0, float(size[1]))
            self.bar_dragged.emit(d["kind"], min(max(nx, 0.0), 1.0), min(max(ny, 0.0), 1.0))
            return
        if self._pan is not None:
            vx, vy, vw, vh = self._pan["view"]
            k = max(1e-9, self._px_map()[2])
            dx = (pos.x() - self._pan["start"].x()) / k
            dy = (pos.y() - self._pan["start"].y()) / k
            fw, fh = self._field
            nx = min(max(vx - dx, 0.0), max(0.0, fw - vw))
            ny = min(max(vy - dy, 0.0), max(0.0, fh - vh))
            self._view_um = (nx, ny, vw, vh)
            self.update()
            self.view_changed.emit()
            return
        if self._drag is None:
            hit = self._roi_hit(pos)
            if hit is not None:
                mode = hit[1]
                self.setCursor({"nw": Qt.SizeFDiagCursor, "se": Qt.SizeFDiagCursor,
                                "ne": Qt.SizeBDiagCursor, "sw": Qt.SizeBDiagCursor,
                                "p0": Qt.CrossCursor, "p1": Qt.CrossCursor}.get(
                                    mode, Qt.SizeAllCursor))
                return
            hit = self._hit(pos)
            if hit in ("nw", "se"):
                self.setCursor(Qt.SizeFDiagCursor)
            elif hit in ("ne", "sw"):
                self.setCursor(Qt.SizeBDiagCursor)
            elif hit == "move":
                self.setCursor(Qt.SizeAllCursor)
            elif self._bar_hit(pos):
                self.setCursor(Qt.OpenHandCursor)
            else:
                self.setCursor(Qt.ArrowCursor)
            return
        d = self._drag
        dx = self._px_to_um(pos.x() - d["start"].x())
        dy = self._px_to_um_y(pos.y() - d["start"].y())
        s = d["box"]
        fw, fh = self._field          # 横向用宽、纵向用高（竖构图的图以前会被卡住）
        minw = 2.0
        if d["mode"] == "move":
            self._box["x"] = min(max(s["x"] + dx, 0.0), max(0.0, fw - s["w"]))
            self._box["y"] = min(max(s["y"] + dy, 0.0), max(0.0, fh - s["h"]))
        else:
            left, top = s["x"], s["y"]
            right, bottom = s["x"] + s["w"], s["y"] + s["h"]
            if "w" in d["mode"]:
                left = min(max(s["x"] + dx, 0.0), right - minw)
            if "e" in d["mode"]:
                right = min(max(s["x"] + s["w"] + dx, left + minw), fw)
            if "n" in d["mode"]:
                top = min(max(s["y"] + dy, 0.0), bottom - minw)
            if "s" in d["mode"]:
                bottom = min(max(s["y"] + s["h"] + dy, top + minw), fh)
            if self._lock:
                size = max(right - left, bottom - top)
                if "w" in d["mode"]:
                    left = max(0.0, right - size)
                else:
                    right = min(fw, left + size)
                if "n" in d["mode"]:
                    top = max(0.0, bottom - size)
                else:
                    bottom = min(fh, top + size)
            self._box.update(x=left, y=top, w=right - left, h=bottom - top)
        self.update()
        self.box_changed.emit()

    def mouseReleaseEvent(self, _ev):
        if self._roi_op is not None:
            op = self._roi_op
            self._roi_op = None
            sh = next((s for s in self._roi_shapes if s["rid"] == op["rid"]), None)
            if sh is not None and sh["pts"] != op["pts"]:
                self.roi_edited.emit(op["rid"], [list(p) for p in sh["pts"]])
            self.setCursor(Qt.ArrowCursor)
            self.update()
            return
        if self._roi_drag is not None:
            start = self._roi_drag
            self._roi_drag = None
            end = self._norm_of(_ev.position()) if hasattr(_ev, "position") else start
            kind = self._roi_kind                 # 工具保持 armed（点一次一直画）
            self.update()
            if abs(end[0] - start[0]) > 1e-4 and abs(end[1] - start[1]) > 1e-4:
                self.roi_done.emit(kind, start[0], start[1], end[0], end[1])
            return
        if self._bar_drag is not None:
            self._bar_drag = None
            self.bar_drag_done.emit()          # 标尺拖完了：撤销栈在这一次提交
            return
        self._drag = None
        self._pan = None
        self.box_changed.emit()
        self.box_committed.emit()

    def mouseDoubleClickEvent(self, ev):
        self.set_zoom(1.0, anchor=ev.position())

    def keyPressEvent(self, ev):
        """Delete / Backspace 删掉选中的 ROI，Esc 退出画 ROI 或取消选中。"""
        if ev.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self._roi_sel:
            self.roi_delete.emit(self._roi_sel)
            ev.accept()
            return
        if ev.key() == Qt.Key_Escape:
            if self._roi_kind:
                self._roi_kind = ""
                self._roi_drag = None
                self.setCursor(Qt.ArrowCursor)
                self.roi_mode_changed.emit("")
                self.update()
            elif self._roi_sel:
                self._roi_sel = ""
                self.roi_selected.emit("")
                self.update()
            ev.accept()
            return
        super().keyPressEvent(ev)

    def contextMenuEvent(self, ev):
        """在 ROI 上点右键 → 交给主窗口弹菜单（删除 / 背景 / 改名 …）。"""
        hit = self._roi_hit(ev.pos())
        if hit is None:
            ev.ignore()
            return
        rid = hit[0]
        if rid != self._roi_sel:
            self._roi_sel = rid
            self.roi_selected.emit(rid)
            self.update()
        self.roi_menu.emit(rid, ev.globalPos())
        ev.accept()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.view_changed.emit()

    # ---------------------------------------------------------- 绘制
    def paintEvent(self, _ev):
        p = QPainter(self)
        # 拆分显示时底色换成中间那块"台面"的淡灰：这样每个大黑框是**独立的框**，
        # 框之间露出灰缝；单图模式下仍然是深灰画布（跟整体一个色系）
        p.fillRect(self.rect(), QColor("#18181C"))     # 深灰，跟整体一个色系
        if self._pix is None:
            p.setPen(QColor("#8a8698"))
            p.drawText(self.rect(), Qt.AlignCenter, "还没有载入图片")
            return
        r = self._view_rect()
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        if self._base is not None:
            p.drawPixmap(self._rect_for(self._base_um), self._base)
        p.drawPixmap(r, self._pix)
        if self._overlay is not None:
            p.drawPixmap(r, self._overlay)
        if self._line_mode and len(self._line) >= 2:
            a, b = self._pt_of(self._line[0]), self._pt_of(self._line[1])
            p.setRenderHint(QPainter.Antialiasing, True)
            p.setPen(QPen(QColor("#FF3B30"), 2))
            p.drawLine(a, b)
            p.setBrush(QColor("#FFFFFF"))
            for pt in (a, b):
                p.drawEllipse(pt, 4.0, 4.0)
            if self._line_px > 0:
                p.setPen(QColor("#FF3B30"))
                f = QFont(self.font())
                f.setBold(True)
                p.setFont(f)
                mid = QPointF((a.x() + b.x()) / 2.0, (a.y() + b.y()) / 2.0 - 14.0)
                p.drawText(mid, "%.1f px" % self._line_px)
        if self._show_box:
            self._draw_box(p)
        # 识别标记画在压暗层之后：不然落在裁剪框外的部分会被压暗，徽标看着发灰
        if self._detect is not None and self._show_box:
            self._draw_detect(p)
        if self._roi_shapes or self._roi_drag is not None:
            self._draw_rois(p)
        if self.zoom() > 1.0001:
            self._draw_zoom_tip(p)

    def _draw_box(self, p):
        # 用"整图"的绘制矩形来压暗框外区域：这样放大时框外也是暗的（不会只暗一小块）
        r = self._rect_for(self._base_um) if self._base_um is not None else self._view_rect()
        r = r.united(QRect(0, 0, self.width(), self.height()))
        b = self._box_rect()
        dim = QColor(6, 6, 12, 150)
        p.fillRect(QRect(r.left(), r.top(), r.width(), b.top() - r.top()), dim)
        p.fillRect(QRect(r.left(), b.bottom(), r.width(), r.bottom() - b.bottom()), dim)
        p.fillRect(QRect(r.left(), b.top(), b.left() - r.left(), b.height()), dim)
        p.fillRect(QRect(b.right(), b.top(), r.right() - b.right(), b.height()), dim)
        p.setPen(QPen(ACCENT, 2))
        p.setBrush(Qt.NoBrush)
        p.drawRect(b)
        p.setBrush(QColor("#ffffff"))
        for pt in (b.topLeft(), b.topRight(), b.bottomLeft(), b.bottomRight()):
            p.drawRect(QRect(pt.x() - 5, pt.y() - 5, 10, 10))
        label = "%g × %g µm" % (self._box["w"], self._box["h"])
        f = QFont(self.font())
        f.setPointSizeF(max(8.0, self.font().pointSizeF()))
        p.setFont(f)
        tw = p.fontMetrics().horizontalAdvance(label) + 16
        lx = min(max(b.center().x() - tw // 2, 2), max(2, self.width() - tw - 2))
        ly = max(2, b.top() - 24)
        p.setPen(Qt.NoPen)
        p.setBrush(ACCENT)
        p.drawRoundedRect(QRect(lx, ly, tw, 20), 10, 10)
        p.setPen(QColor("#ffffff"))
        p.drawText(QRect(lx, ly, tw, 20), Qt.AlignCenter, label)

    def _draw_detect(self, p):
        """把"识别到的标尺线"画在图上（青绿色，跟裁剪框的紫、画线标定的红区分开）。"""
        d = self._detect
        # 先画"其它候选"（琥珀色、细一点、带编号），最高分的青绿线最后画在最上面
        for i, alt in enumerate(d.get("alts") or []):
            aa = self._pt_of(self.norm_to_view(*alt["p0"]))
            bb = self._pt_of(self.norm_to_view(*alt["p1"]))
            p.setRenderHint(QPainter.Antialiasing, True)
            p.setPen(QPen(QColor("#E8A33D"), 2))
            p.drawLine(aa, bb)
            f = QFont(self.font())
            f.setBold(True)
            p.setFont(f)
            tag = "%d" % (i + 2)
            fm = p.fontMetrics()
            tw, th = fm.horizontalAdvance(tag) + 10, fm.height() + 2
            tx = min(max(aa.x() - tw / 2.0, 2.0), max(2.0, self.width() - tw - 2.0))
            ty = min(max(bb.y() - th - 6.0, 2.0), max(2.0, self.height() - th - 2.0))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#E8A33D"))
            p.drawRoundedRect(QRect(int(tx), int(ty), int(tw), int(th)), th / 2.0, th / 2.0)
            p.setPen(QColor("#ffffff"))
            p.drawText(QRect(int(tx), int(ty), int(tw), int(th)), Qt.AlignCenter, tag)
        a = self._pt_of(self.norm_to_view(*d["p0"]))
        b = self._pt_of(self.norm_to_view(*d["p1"]))
        p.setRenderHint(QPainter.Antialiasing, True)
        col = QColor("#00C2A8")
        p.setPen(QPen(col, 3))
        p.drawLine(a, b)
        p.setBrush(col)
        for pt in (a, b):
            p.drawEllipse(pt, 3.5, 3.5)
        # 右上角置信度徽标
        conf = d.get("conf") or ""
        if conf:
            badge = "识别置信度 %s" % conf
            bg = {"高": QColor(0, 150, 120, 220), "中": QColor(200, 130, 0, 220)}.get(
                conf, QColor(110, 110, 125, 220))
            f = QFont(self.font())
            f.setBold(True)
            p.setFont(f)
            fm = p.fontMetrics()
            bw = fm.horizontalAdvance(badge) + 16
            bh = fm.height() + 4
            bx, by = max(2, self.width() - bw - 10), 10
            p.setPen(Qt.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(QRect(int(bx), by, int(bw), int(bh)), bh / 2.0, bh / 2.0)
            p.setPen(QColor("#ffffff"))
            p.drawText(QRect(int(bx), by, int(bw), int(bh)), Qt.AlignCenter, badge)
        # 标注：读到多少 µm → 算出多少 µm/px
        txt = d.get("label") or ""
        if not txt:
            return
        f = QFont(self.font())
        f.setBold(True)
        p.setFont(f)
        fm = p.fontMetrics()
        tw = fm.horizontalAdvance(txt) + 14
        th = fm.height() + 4
        mx, my = (a.x() + b.x()) / 2.0, (a.y() + b.y()) / 2.0
        lx = min(max(mx - tw / 2.0, 2.0), max(2.0, self.width() - tw - 2.0))
        ly = min(max(my - th - 10.0, 2.0), max(2.0, self.height() - th - 2.0))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 194, 168, 225))
        p.drawRoundedRect(QRect(int(lx), int(ly), int(tw), int(th)), th / 2.0, th / 2.0)
        p.setPen(QColor("#ffffff"))
        p.drawText(QRect(int(lx), int(ly), int(tw), int(th)), Qt.AlignCenter, txt)

    def _draw_rois(self, p):
        """画 ROI 轮廓（半透明填充 + 名字）和正在拉的橡皮筋。

        坐标是原图整帧归一化，绘制时走 norm_to_view() —— 放大/平移后位置才对。
        背景 ROI 用青色虚线（跟测量 ROI 的橙色实线分开，一眼能看出哪个是背景）。
        """
        p.setRenderHint(QPainter.Antialiasing, True)
        col_roi = QColor("#FFB020")
        col_bg = QColor("#22D3EE")
        f = QFont(self.font())
        f.setBold(True)
        p.setFont(f)

        def draw(kind, a, b, label="", bg=False, sel=False):
            col = col_bg if bg else col_roi
            ra = QRect(int(min(a.x(), b.x())), int(min(a.y(), b.y())),
                       max(2, int(abs(b.x() - a.x()))), max(2, int(abs(b.y() - a.y()))))
            pen = QPen(col, 2)
            if bg:
                pen.setStyle(Qt.DashLine)
            p.setPen(pen)
            p.setBrush(QColor(34, 211, 238, 34) if bg else QColor(255, 176, 32, 40))
            if kind == "ellipse":
                p.drawEllipse(ra)
            elif kind == "line":
                p.setBrush(Qt.NoBrush)
                p.drawLine(a, b)
            elif kind == "point":
                # 点：一个实心小圆 + 十字丝（看得见、又不遮住信号）
                p.setBrush(col)
                p.setPen(QPen(QColor("#FFFFFF"), 1))
                p.drawEllipse(a, 4.0, 4.0)
                p.setPen(QPen(col, 1.5))
                p.drawLine(QPointF(a.x() - 8.0, a.y()), QPointF(a.x() + 8.0, a.y()))
                p.drawLine(QPointF(a.x(), a.y() - 8.0), QPointF(a.x(), a.y() + 8.0))
                p.setBrush(Qt.NoBrush)
            else:
                p.drawRect(ra)
            if sel:                                   # 选中：方框四角画把手，点画虚线圈
                if kind == "point":
                    p.setBrush(Qt.NoBrush)
                    p.setPen(QPen(QColor("#FFFFFF"), 2, Qt.DashLine))
                    p.drawEllipse(a, 8.0, 8.0)
                else:
                    p.setBrush(QColor("#FFFFFF"))
                    p.setPen(QPen(col, 2))
                    for pt in (a, QPointF(a.x(), b.y()), QPointF(b.x(), a.y()), b):
                        p.drawRect(QRectF(pt.x() - 4.0, pt.y() - 4.0, 8.0, 8.0))
                p.setPen(pen)
                p.setBrush(QColor(34, 211, 238, 34) if bg else QColor(255, 176, 32, 40))
            if label:
                th = p.fontMetrics().height() + 2
                tw = p.fontMetrics().horizontalAdvance(label) + 10
                ly = max(2, ra.top() - th - 2)
                p.setPen(Qt.NoPen)
                p.setBrush(col)
                p.drawRoundedRect(QRect(ra.left(), ly, tw, th), th / 2.0, th / 2.0)
                p.setPen(QColor("#ffffff"))
                p.drawText(QRect(ra.left(), ly, tw, th), Qt.AlignCenter, label)
                p.setPen(pen)
                p.setBrush(QColor(34, 211, 238, 34) if bg else QColor(255, 176, 32, 40))

        for sh in self._roi_shapes:
            if not sh["pts"]:
                continue
            sc = self._roi_screen(sh)
            if sc is None:
                continue
            draw(sh["kind"], sc[0], sc[1], sh["label"], sh["bg"],
                 sh["rid"] == self._roi_sel)
        if self._roi_drag is not None:
            cur = self.mapFromGlobal(self.cursor().pos())
            draw(self._roi_kind, self._pt_of(self._roi_drag),
                 QPointF(float(cur.x()), float(cur.y())), "")

    def _draw_zoom_tip(self, p):
        tip = "×%.1f　滚轮缩放 · 拖动平移 · 双击复位" % self.zoom()
        f2 = QFont(self.font())
        f2.setPointSizeF(max(7.5, self.font().pointSizeF() - 0.5))
        p.setFont(f2)
        tw2 = p.fontMetrics().horizontalAdvance(tip) + 16
        tx, ty = 10, self.height() - 32
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(10, 10, 16, 170))
        p.drawRoundedRect(QRect(tx, ty, tw2, 22), 11, 11)
        p.setPen(QColor("#f0f0f6"))
        p.drawText(QRect(tx, ty, tw2, 22), Qt.AlignCenter, tip)
