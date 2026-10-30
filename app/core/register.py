# -*- coding: utf-8 -*-
"""处理链：通道配准 + 背景扣除 + 时间序列漂移校正（规格书 P1-7）。

三条硬规矩（写在这里，免得以后被"优化"掉）：

1. **原始像素永不被修改**。所有处理都记成 `item.process` 里的步骤，
   预览 / 导出 / 统计时按链重建（规格书 2.2）。
2. **背景扣除保留负值**（float32，不 clip 到 0）：clip 会把"背景估计偏高"
   这个信息一起丢掉，而它正是判断参数对不对的依据。
3. 结果**必须能精确还原**：导出的原始位深文件里内嵌的是链前数据
   （P0-2 的私有 tag），不靠逆运算 —— 平移 / 扣背景 / 去卷积都不可逆。

只用 cv2 + numpy，不引入 scipy（规格书 2.1）。
"""
from __future__ import annotations

import weakref

import numpy as np

try:
    import cv2
except Exception:                                    # noqa: BLE001
    cv2 = None

# 处理后的缓存上限（规格书 4.13.5 要求"必须有内存上限"）：
# float32 的 60 帧 × 1024² × 3 通道 = 754 MB，所以默认给 768 MB
CACHE_BUDGET = 768 * 1024 * 1024
_CACHE = {}          # id(item) -> [weakref, nbytes]
_ORDER = []          # LRU：最近用过的排后面


# ------------------------------------------------------------------ 配准
def _highpass(plane, k=7):
    """先减去高斯模糊 → 抑制大块背景，让相关由结构决定（规格书 4.13.1）。"""
    a = np.asarray(plane, np.float32)
    if cv2 is None:
        return a - a.mean()
    return a - cv2.GaussianBlur(a, (0, 0), k)


def est_shift(ref, mov, highpass=True):
    """估计 mov 相对 ref 的平移（亚像素）。返回 (dx, dy, response)。

    正数表示 mov 要往 +x/+y 移才能对上 ref。
    """
    if cv2 is None:
        return 0.0, 0.0, 0.0
    a = _highpass(ref) if highpass else np.asarray(ref, np.float32)
    b = _highpass(mov) if highpass else np.asarray(mov, np.float32)
    a = a - a.mean()
    b = b - b.mean()
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na <= 0 or nb <= 0:
        return 0.0, 0.0, 0.0
    a, b = a / na, b / nb
    # Hann 窗抑制边缘效应（相位相关对边界很敏感）
    win = (np.hanning(a.shape[0]).astype(np.float32)[:, None]
           * np.hanning(a.shape[1]).astype(np.float32)[None, :])
    try:
        (dx, dy), resp = cv2.phaseCorrelate(a * win, b * win)
    except Exception:                                # noqa: BLE001
        return 0.0, 0.0, 0.0
    return float(dx), float(dy), float(resp)


def apply_shift(plane, dx, dy):
    """把一层按 (dx, dy) 平移回去。

    边界用 **BORDER_REPLICATE**（拿边缘像素往外铺）而不是补 0：
    补 0 会在图里造出一圈假的黑边，把随后的百分位扣背景整个带偏
    （实测：21 层 Z 栈里配准一次的补 0 边就让背景 5% 分位从 86 掉到 50）。
    """
    if cv2 is None or (abs(dx) < 1e-6 and abs(dy) < 1e-6):
        return np.asarray(plane, np.float32)
    m = np.float32([[1, 0, -dx], [0, 1, -dy]])
    return cv2.warpAffine(np.asarray(plane, np.float32), m,
                          (plane.shape[1], plane.shape[0]),
                          flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def channel_shifts(stack, ref_ch=0, frame=0, c_count=None):
    """每个通道相对参考通道的位移：{通道序号: (dx, dy, response)}。"""
    out = {}
    f = max(0, min(int(frame), stack.shape[0] - 1))
    c_n = int(c_count or stack.shape[1])
    ref_ch = max(0, min(int(ref_ch), c_n - 1))
    ref = stack[f, ref_ch]
    for c in range(c_n):
        out[c] = (0.0, 0.0, 1.0) if c == ref_ch else est_shift(ref, stack[f, c])
    return out


def drift_shifts(stack, ref_frame=0, ch=0, report=None):
    """逐帧相对参考帧的平移：{帧号: (dx, dy, response)}。"""
    out = {}
    n = stack.shape[0]
    c = max(0, min(int(ch), stack.shape[1] - 1))
    ref = stack[max(0, min(int(ref_frame), n - 1)), c]
    for f in range(n):
        if callable(report):
            report(f, n, "第 %d 帧" % (f + 1))
        out[f] = (0.0, 0.0, 1.0) if f == ref_frame else est_shift(ref, stack[f, c])
    return out


# ------------------------------------------------------------------ 背景扣除
def bg_values(stack, step, p_lo=5.0):
    """按通道算背景值：{通道: 背景}（规格书 4.13.2）。"""
    vals = {}
    params = dict(getattr(step, "params", None) or {})
    mode = params.get("mode", "percentile")
    for c in range(stack.shape[1]):
        plane = np.asarray(stack[:, c], np.float32)
        if mode == "const":
            vals[c] = float(params.get("c") or 0.0)
        elif mode == "roi":
            roi = params.get("roi")
            if roi:
                x0, y0, x1, y1 = [int(v) for v in roi]
                vals[c] = float(plane[:, max(0, y0):y1, max(0, x0):x1].mean())
            else:
                vals[c] = float(np.percentile(plane, p_lo))
        else:
            p = float(params.get("p", p_lo) or p_lo)
            vals[c] = float(np.percentile(plane, p))
    return vals


# ------------------------------------------------------------------ 整条链
def apply_chain(raw, item, report=None):
    """按 `item.process` 的顺序把链算完，返回 float32 数组。"""
    out = np.asarray(raw)
    steps = [s for s in (getattr(item, "process", None) or [])
             if getattr(s, "enabled", True)]
    if not steps:
        return out
    out = out.astype(np.float32, copy=False)
    for k, step in enumerate(steps):
        kind = (step.kind or "").lower()
        params = dict(step.params or {})
        if callable(report):
            report(k, len(steps), kind)
        if kind == "register":
            out = _apply_register(out, item, params)
        elif kind == "bg":
            out = _apply_bg(out, step)
        elif kind == "drift":
            out = _apply_drift(out, item, params)
        # 其它 kind 原样透传：**去卷积已按用户要求移除**（2026-09-22），
        # 老工程里若还留着 deconvolve 这一步，读进来会被忽略（不会报错、不会改像素）。
    return out


def _apply_register(out, item, params):
    ref_ch = int(params.get("ref_ch", 0) or 0)
    shifts = dict(params.get("shifts") or {})
    manual = dict(params.get("manual") or {})
    frame = int(params.get("frame", 0) or 0)
    if not shifts:
        shifts = {str(c): v[:2] for c, v in
                  channel_shifts(out, ref_ch=ref_ch, frame=frame).items()}
    for c in range(out.shape[1]):
        if c == ref_ch:
            continue
        s = shifts.get(str(c))
        if not s:
            continue
        dx, dy = float(s[0]), float(s[1])
        m = manual.get(str(c)) or manual.get(c)
        if m:
            dx += float(m[0])
            dy += float(m[1])
        if abs(dx) < 1e-6 and abs(dy) < 1e-6:
            continue
        for f in range(out.shape[0]):
            out[f, c] = apply_shift(out[f, c], dx, dy)
    return out


def _apply_bg(out, step):
    for c, v in bg_values(out, step).items():
        if c < out.shape[1] and v:
            out[:, c] = out[:, c] - v
    return out


def _apply_drift(out, item, params):
    shifts = dict(params.get("shifts") or {})
    ch = int(params.get("ch", 0) or 0)
    ref = int(params.get("ref_frame", 0) or 0)
    if not shifts:
        shifts = {str(f): v[:2] for f, v in
                  drift_shifts(out, ref_frame=ref, ch=ch).items()}
    for f in range(out.shape[0]):
        s = shifts.get(str(f))
        if not s:
            continue
        dx, dy = float(s[0]), float(s[1])
        if abs(dx) < 1e-6 and abs(dy) < 1e-6:
            continue
        for c in range(out.shape[1]):
            out[f, c] = apply_shift(out[f, c], dx, dy)
    return out


# ------------------------------------------------------------------ 缓存上限
def cache_note(item, nbytes):
    """登记一次缓存占用；超预算就释放最久没用过的（规格书 4.13.5 / 验收 8）。"""
    key = id(item)
    _CACHE[key] = [weakref.ref(item), int(nbytes)]
    if key in _ORDER:
        _ORDER.remove(key)
    _ORDER.append(key)
    total = sum(v[1] for v in _CACHE.values() if v[0]() is not None)
    while total > CACHE_BUDGET and len(_ORDER) > 1:
        old = _ORDER.pop(0)
        ref, nb = _CACHE.pop(old, [None, 0])
        obj = ref and ref()
        if obj is None:
            continue
        if obj is item:
            _ORDER.append(old)
            _CACHE[old] = [ref, nb]
            break
        obj._cache = None
        obj._raw_cache = None
        obj._cache_key = None
        total -= nb


def cache_info():
    """给自检用：当前登记了几份、共多少字节。"""
    alive = [(k, v[1]) for k, v in _CACHE.items() if v[0]() is not None]
    return len(alive), sum(nb for _k, nb in alive)
