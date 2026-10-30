# -*- coding: utf-8 -*-
"""定量分析（规格书 P1-6 4.8）。

**铁律（4.8.1）**：所有统计都读**原始位深**数据 —— 用 `loader.load_stack()`，
它本来就是"没过链 = 原始 / 过了链 = 链后重建"的那一份。
显示区间、逐帧归一化、通道配色、屏幕锐化（`sharpen_display`）**一律不参与计算**。
结果里必须写明启用了哪些处理步骤（发表时审稿人会问）。

只用 cv2 + numpy（不引入 scipy）。
"""
from __future__ import annotations

import time

import numpy as np

from core import roi as roi_mod

try:
    import cv2
except Exception:                                    # noqa: BLE001
    cv2 = None


def visible_channels(item):
    return [c for c in (getattr(item, "channels", None) or []) if c.visible]


def _frame_of(stack, item, frame=None):
    return max(0, min(int(frame if frame is not None else 0), stack.shape[0] - 1))


def bg_means(stack, item, frame=None, roi=None):
    """背景 ROI 的各通道均值：{通道序号: 均值}。

    优先用手动背景 ROI（规格书 4.8.4）；没画就返回 {}（不自动猜）。
    """
    rb = roi if roi is not None else roi_mod.bg_roi(item)
    if rb is None:
        return {}
    m = roi_mod.roi_mask(rb, item.width, item.height)
    if m is None or not m.any():
        return {}
    f = _frame_of(stack, item, frame)
    out = {}
    for c in range(stack.shape[1]):
        out[c] = float(np.asarray(stack[f, c], np.float32)[m].mean())
    return out


def roi_stats(stack, item, roi, frame=None, bg=None, chans=None):
    """一个 ROI × 每个可见通道的统计（规格书 4.8.4 的字段表）。

    注意 `IntDen = Mean × Area_px`，**与有没有标定无关**（R2 补注）：
    未标定只是 `Area_um2` 留空，`IntDen` 照算。

    取哪一帧（2026-09-26 修）：ROI 自己写了 t/z 就用它的（`flat_index`，
    顺序是 t*z_count+z）；没写（-1）就跟随当前帧。老写法只认 t 且写成
    `roi.t * z_count`，等于把 Z 层强制成 0 —— ROI 的 z 字段形同虚设。

    `chans` 给了就只算这几路（导出面板里"只看某一通道"用），默认所有可见通道。
    """
    m = roi_mod.roi_mask(roi, item.width, item.height)
    if m is None:
        return []
    if getattr(roi, "t", -1) < 0 and getattr(roi, "z", -1) < 0:
        f = _frame_of(stack, item, frame)
    else:
        t = int(getattr(roi, "t", -1))
        z = int(getattr(roi, "z", -1))
        t = 0 if t < 0 else t
        z = 0 if z < 0 else z
        f = _frame_of(stack, item, item.flat_index(t, z))
    area_px = int(m.sum())
    umpp = float(getattr(item, "umpp", 0.0) or 0.0)
    bg = bg or {}
    rows = []
    for c in (visible_channels(item) if chans is None else list(chans)):
        idx = int(getattr(c, "index", 0))
        if idx >= stack.shape[1] or (roi.ch >= 0 and roi.ch != idx):
            continue
        v = np.asarray(stack[f, idx], np.float32)[m]
        if v.size == 0:
            continue
        mean = float(v.mean())
        sd = float(v.std(ddof=0))
        raw = float(v.sum())
        # 中心坐标：点的定量报告要用（"这个点是哪个位置"），其它形状也顺手给上
        try:
            ys, xs = np.nonzero(m)
            cx = float(xs.mean()) if xs.size else 0.0
            cy = float(ys.mean()) if ys.size else 0.0
        except Exception:                            # noqa: BLE001
            cx = cy = 0.0
        # 不再输出内部 id（rid）：表格里那一列对用户没意义（2026-09-26）
        row = dict(roi=roi.label, channel=(c.name or ("CH%d" % (idx + 1))),
                   Area_px=area_px,
                   Area_um2=(round(area_px * umpp * umpp, 4) if umpp > 0 else ""),
                   Mean=round(mean, 4), SD=round(sd, 4),
                   Min=round(float(v.min()), 4), Max=round(float(v.max()), 4),
                   Median=round(float(np.median(v)), 4),
                   IntDen=round(mean * area_px, 3), RawIntDen=round(raw, 3))
        if umpp > 0:
            row["中心X_µm"] = round(cx * umpp, 3)
            row["中心Y_µm"] = round(cy * umpp, 3)
        else:
            row["中心X_px"] = round(cx, 1)
            row["中心Y_px"] = round(cy, 1)
        b = bg.get(idx)
        if b is not None:
            row["Mean_bg_corr"] = round(mean - b, 4)
            row["IntDen_bg_corr"] = round((mean - b) * area_px, 3)
        rows.append(row)
    return rows


def line_profile(stack, item, roi, frame=None, width=0):
    """线剖面：沿线**双线性插值**取样（不要最近邻，会阶梯状）。

    返回 dict(um=[…], series={通道名: [强度…]}, length_um, note)
    """
    p = roi_mod.roi_px_pts(roi, item.width, item.height)
    if p is None:
        return {}
    (ax, ay), (bx, by) = p
    n = max(2, int(round(max(abs(bx - ax), abs(by - ay)))) + 1)
    xs = np.linspace(ax, bx, n)
    ys = np.linspace(ay, by, n)
    f = _frame_of(stack, item, frame)
    series = {}
    for c in visible_channels(item):
        idx = int(getattr(c, "index", 0))
        if idx >= stack.shape[1]:
            continue
        plane = np.asarray(stack[f, idx], np.float32)
        if cv2 is not None:
            vals = [_bilinear(plane, x, y) for x, y in zip(xs, ys)]
        else:
            vals = [float(plane[int(round(y)), int(round(x))])
                    for x, y in zip(xs, ys)]
        if width and cv2 is not None and n > 1:      # 可选：垂直方向 ±n 平均抗噪
            dx, dy = bx - ax, by - ay
            L = max(1e-6, float(np.hypot(dx, dy)))
            nx, ny = -dy / L, dx / L
            acc = np.asarray(vals, np.float32)
            for k in range(1, int(width) + 1):
                for sgn in (1, -1):
                    vv = [_bilinear(plane, x + sgn * k * nx, y + sgn * k * ny)
                          for x, y in zip(xs, ys)]
                    acc = acc + np.asarray(vv, np.float32)
            vals = list(acc / (2.0 * int(width) + 1.0))
        series[c.name or ("CH%d" % (idx + 1))] = [round(float(v), 4) for v in vals]
    umpp = float(getattr(item, "umpp", 0.0) or 0.0)
    return dict(um=[round(float(t) * umpp, 4) for t in range(n)],
                series=series, n=n, length_um=round(n * umpp, 4),
                scaled=bool(umpp > 0))


def _bilinear(plane, x, y):
    h, w = plane.shape[:2]
    x = min(max(0.0, x), w - 1.001)
    y = min(max(0.0, y), h - 1.001)
    x0, y0 = int(np.floor(x)), int(np.floor(y))
    fx, fy = x - x0, y - y0
    x1, y1 = min(x0 + 1, w - 1), min(y0 + 1, h - 1)
    return float(plane[y0, x0] * (1 - fx) * (1 - fy) + plane[y0, x1] * fx * (1 - fy)
                 + plane[y1, x0] * (1 - fx) * fy + plane[y1, x1] * fx * fy)


# ------------------------------------------------------------------ 共定位
def pearson(a, b):
    x = np.asarray(a, np.float32).ravel()
    y = np.asarray(b, np.float32).ravel()
    if x.size < 2:
        return 0.0
    x = x - x.mean()
    y = y - y.mean()
    d = float(np.linalg.norm(x) * np.linalg.norm(y))
    return float((x * y).sum() / d) if d > 0 else 0.0


def overlap_coef(a, b):
    x = np.asarray(a, np.float32).ravel()
    y = np.asarray(b, np.float32).ravel()
    d = float(np.linalg.norm(x) * np.linalg.norm(y))
    return float((x * y).sum() / d) if d > 0 else 0.0


def manders(a, b, thr_b=0.0, thr_a=0.0):
    x = np.asarray(a, np.float32).ravel()
    y = np.asarray(b, np.float32).ravel()
    sx, sy = float(x.sum()), float(y.sum())
    m1 = float(x[y > thr_b].sum() / sx) if sx > 0 else 0.0
    m2 = float(y[x > thr_a].sum() / sy) if sy > 0 else 0.0
    return round(m1, 4), round(m2, 4)


def otsu_threshold(plane):
    """Otsu 阈值，**换算回原始数据单位**。

    坑：Otsu 是在归一化到 0~255 的图上算的，直接 `t/255*max` 会把阈值算错 ——
    实测"背景 120 + 亮点 3000"的图 Otsu 给 t=0，`0/255*3000 = 0`，
    于是 `v > 0` 把整个背景都当成了前景（本该只留下亮点）。
    正确换算是 `lo + t/255*(hi-lo)`。
    """
    v = np.asarray(plane, np.float32)
    lo, hi = float(v.min()), float(v.max())
    if cv2 is None or hi <= lo:
        return float((lo + hi) / 2.0)
    u8 = _to_u8(v)
    t, _img = cv2.threshold(u8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return lo + float(t) / 255.0 * (hi - lo)


def _to_u8(plane):
    v = np.asarray(plane, np.float32)
    lo, hi = float(v.min()), float(v.max())
    if hi <= lo:
        return np.zeros(v.shape, np.uint8)
    return np.clip((v - lo) / (hi - lo) * 255.0, 0, 255).astype(np.uint8)


def colocalization(stack, item, ch_a=0, ch_b=1, roi=None, frame=None,
                   thr_mode="otsu", manual=(0.0, 0.0)):
    """两通道的共定位指标（规格书 4.8.6）。返回 dict（含"未配准"标注）。"""
    f = _frame_of(stack, item, frame)
    c_n = stack.shape[1]
    a_i = max(0, min(int(ch_a), c_n - 1))
    b_i = max(0, min(int(ch_b), c_n - 1))
    a = np.asarray(stack[f, a_i], np.float32)
    b = np.asarray(stack[f, b_i], np.float32)
    mask = roi_mod.roi_mask(roi, item.width, item.height) if roi is not None else None
    if mask is not None and mask.any():
        a, b = a[mask], b[mask]
    if thr_mode == "otsu":
        ta, tb = otsu_threshold(a), otsu_threshold(b)
    elif thr_mode == "percentile":
        ta, tb = float(np.percentile(a, 90)), float(np.percentile(b, 90))
    else:
        ta, tb = float(manual[0]), float(manual[1])
    m1, m2 = manders(a, b, thr_b=tb, thr_a=ta)
    reg = any(s.kind == "register" and getattr(s, "enabled", True)
              for s in (getattr(item, "process", None) or []))
    return dict(Pearson_r=round(pearson(a, b), 4),
                Overlap=round(overlap_coef(a, b), 4),
                M1=round(m1, 4), M2=round(m2, 4),
                thr_a=round(ta, 3), thr_b=round(tb, 3),
                registered=bool(reg),
                note="" if reg else "未配准：结果可能不可靠，建议先在「处理」里做通道配准")


# ------------------------------------------------------------------ 粒子计数
def count_particles(plane, thr=None, min_area_px=4, max_area_px=10 ** 9,
                    open_k=1, close_k=1):
    """阈值 + 形态学 + 连通域（规格书 4.8.7）。返回 dict(count, particles…)。"""
    v = np.asarray(plane, np.float32)
    if thr is None:
        thr = otsu_threshold(v)
    th = (v > float(thr)).astype(np.uint8)
    if cv2 is None:                                  # 没 cv2 时的纯 numpy 兜底
        return dict(count=int(th.sum()), thr=round(float(thr), 3), particles=[],
                    note="没有 cv2：只给了阈值像素数，没做连通域分析")
    if open_k > 1:
        th = cv2.morphologyEx(th, cv2.MORPH_OPEN,
                              cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                                        (open_k, open_k)))
    if close_k > 1:
        th = cv2.morphologyEx(th, cv2.MORPH_CLOSE,
                              cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                                        (close_k, close_k)))
    n, labels, stats, centroids = cv2.connectedComponentsWithStats(th, 8)
    parts = []
    for i in range(1, n):
        area = int(stats[i, cv2.CC_STAT_AREA])
        if area < min_area_px or area > max_area_px:
            continue
        cx, cy = centroids[i]
        parts.append(dict(label=i, area_px=area, cx=round(float(cx), 2),
                          cy=round(float(cy), 2),
                          mean=round(float(v[labels == i].mean()), 4)))
    return dict(count=len(parts), thr=round(float(thr), 3), particles=parts)


# ------------------------------------------------------------------ 报告
def csv_header(item, umpp_note="", extra=()):
    """CSV 头部注释行（方法学可追溯性的最低要求，规格书 4.8.8）。"""
    cn = {"register": "配准", "bg": "扣背景", "drift": "漂移校正",
          "deconvolve": "去卷积"}
    steps = ["%s%s" % (cn.get(s.kind, s.kind),
                       "" if getattr(s, "enabled", True) else "(关闭)")
             for s in (getattr(item, "process", None) or [])]
    reg = "是" if any(getattr(s, "kind", "") == "register"
                      and getattr(s, "enabled", True)
                      for s in (getattr(item, "process", None) or [])) else "否"
    lines = ["# Image capture 定量结果（只读原始位深数据，未经过显示区间）",
             "# 图片：%s" % getattr(item, "name", ""),
             "# µm/px：%g" % float(getattr(item, "umpp", 0.0) or 0.0),
             "# ROI 坐标基准：归一化到原图整帧（0~1）",
             "# 处理链：%s" % ("、".join(steps) if steps else "无"),
             "# 是否已配准：%s" % reg,
             "# 时间：%s" % time.strftime("%Y-%m-%d %H:%M:%S")]
    if umpp_note:
        lines.append("# " + umpp_note)
    for x in (extra or ()):
        lines.append("# " + str(x))
    return lines


def rows_to_csv(rows, header_lines=()):
    """行列表 → CSV 文本（调用方用 utf-8-sig 写文件，Excel 打开中文不乱码）。"""
    if not rows:
        return "\n".join(list(header_lines) + ["（没有数据）"])
    cols = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    out = list(header_lines)
    out.append(",".join(cols))
    for r in rows:
        out.append(",".join("" if r.get(c) is None else str(r.get(c, "")) for c in cols))
    return "\n".join(out)
