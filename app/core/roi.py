# -*- coding: utf-8 -*-
"""ROI 定义（规格书 P1-6 4.8.2）。

**坐标基准：归一化到原图整帧（0~1），不相对裁剪框。**
这样换 Z 层、换时间点、改裁剪框、改缩放都不影响 ROI 的位置语义。
ROI 挂在 ImageItem 上（不挂组），进 `.icproj`。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import numpy as np


@dataclass
class Roi:
    rid: str = ""
    kind: str = "rect"                 # rect / ellipse / line / point
    points: list = field(default_factory=list)    # [[nx, ny], …] 归一化
    z: int = -1                        # -1 = 跟随当前 Z 层
    t: int = -1                        # -1 = 跟随当前时间点
    ch: int = -1                       # -1 = 所有可见通道
    label: str = ""
    is_bg: bool = False                # 背景 ROI：其它 ROI 自动扣它的均值
    radius: float = 0.0                # 只有 point 用：取样半径（像素），0 = 默认 3

    def __post_init__(self):
        if not self.rid:
            self.rid = "r" + uuid.uuid4().hex[:8]
        if not self.label:
            self.label = {"rect": "矩形", "ellipse": "椭圆",
                          "line": "直线", "point": "点"}.get(self.kind, self.kind)

    # ---- 序列化（进 .icproj）
    def to_dict(self) -> dict:
        return dict(rid=self.rid, kind=self.kind,
                    points=[[float(p[0]), float(p[1])] for p in self.points],
                    z=int(self.z), t=int(self.t), ch=int(self.ch),
                    label=self.label, is_bg=bool(self.is_bg),
                    radius=float(self.radius or 0.0))

    @classmethod
    def from_dict(cls, d: dict) -> "Roi":
        pts = [[float(p[0]), float(p[1])] for p in (d.get("points") or [])
               if len(p) >= 2]
        return cls(rid=str(d.get("rid") or ""), kind=str(d.get("kind") or "rect"),
                   points=pts, z=int(d.get("z", -1)), t=int(d.get("t", -1)),
                   ch=int(d.get("ch", -1)), label=str(d.get("label") or ""),
                   is_bg=bool(d.get("is_bg", False)),
                   radius=float(d.get("radius", 0.0) or 0.0))


POINT_R = 3.0          # 点 ROI 的默认取样半径（像素）


def roi_px(roi: Roi, width: int, height: int):
    """归一化 → 像素包围盒（x0, y0, x1, y1），已裁到图像内（x1/y1 不含）。"""
    if not roi.points:
        return None
    if roi.kind == "point":
        # 点 ROI：不管存了几个点，都只看第一个点，包围盒按取样半径算
        # （拖动后 points 里可能有两个相同的点，不能因此判成"没面积"）
        r = float(roi.radius or 0.0) or POINT_R
        cx = roi.points[0][0] * width
        cy = roi.points[0][1] * height
        x0 = int(max(0, cx - r))
        x1 = int(min(width, cx + r + 1))
        y0 = int(max(0, cy - r))
        y1 = int(min(height, cy + r + 1))
        if x1 - x0 < 1 or y1 - y0 < 1:
            return None
        return x0, y0, x1, y1
    if len(roi.points) < 2:
        return None
    xs = [p[0] * width for p in roi.points]
    ys = [p[1] * height for p in roi.points]
    x0 = int(max(0, min(xs)))
    x1 = int(min(width, max(xs) + 0.5))
    y0 = int(max(0, min(ys)))
    y1 = int(min(height, max(ys) + 0.5))
    if roi.kind == "line":
        # 水平/垂直的线，包围盒只有 1 像素厚（甚至 0），不能按"宽高都 ≥1"判无效 ——
        # 老写法会让一条水平线整条测不出来（2026-09-26 自检抓到）
        x1 = min(width, max(x1, x0 + 1))
        y1 = min(height, max(y1, y0 + 1))
    if x1 - x0 < 1 or y1 - y0 < 1:
        return None
    return x0, y0, x1, y1


def roi_mask(roi: Roi, width: int, height: int):
    """ROI 的布尔掩膜 (H, W)。矩形/椭圆按几何算，直线按沿线像素。"""
    if roi.kind == "line":
        p = roi_px_pts(roi, width, height)
        if p is None:
            return None
        (ax, ay), (bx, by) = p
        n = max(2, int(round(max(abs(bx - ax), abs(by - ay)))) + 1)
        xs = np.clip(np.linspace(ax, bx, n).round().astype(int), 0, width - 1)
        ys = np.clip(np.linspace(ay, by, n).round().astype(int), 0, height - 1)
        m = np.zeros((height, width), bool)
        m[ys, xs] = True
        return m
    if roi.kind == "point":
        # 点 ROI：以该点为中心的小圆盘（默认半径 3 px）——
        # 直接取单像素太容易被噪点带偏，取个小区均值更稳（2026-09-28 用户要的点工具）
        box = roi_px(roi, width, height)
        if box is None:
            return None
        x0, y0, x1, y1 = box
        cx = roi.points[0][0] * width
        cy = roi.points[0][1] * height
        r = float(roi.radius or 0.0) or POINT_R
        yy, xx = np.mgrid[y0:y1, x0:x1]
        m = np.zeros((height, width), bool)
        m[y0:y1, x0:x1] = ((xx - cx) ** 2 + (yy - cy) ** 2) <= (r * r)
        return m
    box = roi_px(roi, width, height)
    if box is None:
        return None
    x0, y0, x1, y1 = box
    if roi.kind == "ellipse":
        yy, xx = np.mgrid[y0:y1, x0:x1]
        cx, cy = (x0 + x1 - 1) / 2.0, (y0 + y1 - 1) / 2.0
        rx, ry = max(0.5, (x1 - x0) / 2.0), max(0.5, (y1 - y0) / 2.0)
        m = np.zeros((height, width), bool)
        m[y0:y1, x0:x1] = ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2 <= 1.0
        return m
    m = np.zeros((height, width), bool)
    m[y0:y1, x0:x1] = True
    return m


def roi_px_pts(roi: Roi, width: int, height: int):
    """直线的两个端点（像素坐标）。"""
    if len(roi.points) < 2:
        return None
    (nx0, ny0), (nx1, ny1) = roi.points[0], roi.points[-1]
    return ((nx0 * width, ny0 * height), (nx1 * width, ny1 * height))


def rois_of(item) -> list:
    return list(getattr(item, "rois", None) or [])


def bg_roi(item):
    return next((r for r in rois_of(item) if getattr(r, "is_bg", False)), None)


def kind_name(kind: str) -> str:
    return {"rect": "矩形", "ellipse": "椭圆", "line": "直线", "point": "点"}.get(
        str(kind or ""), str(kind or "ROI"))


def next_label(rois, kind: str) -> str:
    """给新建的 ROI 起个不重名的名字：矩形 1、矩形 2…

    历史 bug（用户实测）：以前所有矩形都叫「矩形」、所有椭圆都叫「椭圆」，
    画三个以后右栏列表和结果表里全是「矩形」，根本分不清哪个是哪个。
    删掉中间的编号不回收（避免"矩形 2"改名叫"矩形 1"让人对不上历史记录）。
    """
    base = kind_name(kind)
    used = {str(getattr(r, "label", "")) for r in (rois or [])}
    n = 1
    while ("%s %d" % (base, n)) in used:
        n += 1
    return "%s %d" % (base, n)
