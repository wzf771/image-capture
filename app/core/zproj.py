# -*- coding: utf-8 -*-
"""Z 投影（P1-5 4.3.1）。

为什么投影做成"帧维归约"而不是新对象：投影只改 Z 方向，
**XY 物理标定不变** → 裁剪框、标尺、导出流程原样复用（改动面最小）。
用法上就是在 `load_stack()` 之后、`compose()` 之前插一步。

文件名叫 zproj.py 而不是规格书写的 project.py —— 那个名字被 P0-1 的工程文件占了。
"""
from __future__ import annotations

import numpy as np

MODES = ("max", "sum", "mean", "sd")
MODE_CN = {"max": "MIP", "sum": "求和", "mean": "平均", "sd": "标准差"}
MODE_TAG = {"max": "MIP", "sum": "SUM", "mean": "MEAN", "sd": "SD"}

# 单次处理的像素上限（与 compose() 的 band 同量级），超了按 Y 方向分条
MAX_PIXELS = 40_000_000


def proj_label(mode) -> str:
    return MODE_CN.get(mode or "none", "无")


def proj_tag(mode) -> str:
    return MODE_TAG.get(mode or "none", "")


def proj_range(item):
    """当前投影覆盖哪几层（0 基，闭区间）。

    三种范围各用一个字段，别互相兼职（第一版拿 proj_to<0 表示"当前层 ± n"，
    结果默认值 proj_to=-1 被解释成"±0"，一开投影只剩一层 —— 实测踩过）。
    """
    zc = max(1, int(getattr(item, "z_count", 1) or 1))
    mode = (getattr(item, "proj_range_mode", "all") or "all").lower()
    if mode == "manual":
        lo = int(getattr(item, "proj_from", 0) or 0)
        hi = int(getattr(item, "proj_to", -1) or -1)
        if hi < lo:
            hi = lo
    elif mode == "around":
        cur = int(getattr(item, "proj_center", 0) or 0)
        n = max(0, int(getattr(item, "proj_n", 3) or 0))
        lo, hi = cur - n, cur + n
    else:
        lo, hi = 0, zc - 1
    lo = max(0, min(int(lo), zc - 1))
    hi = max(lo, min(int(hi), zc - 1))
    return lo, hi


def project_frame(stack, item, t=0, mode=None, z_from=None, z_to=None):
    """把 (F, C, Y, X) 里某个"时间点"的 Z 范围投影成 (C, Y, X)。

    stack 的展平顺序是 t * z_count + z（与 `_canonical` 一致），
    所以同一时间点的 Z 层就是连续的一段索引。
    """
    mode = (mode or getattr(item, "proj_mode", "none") or "none").lower()
    if mode not in MODES:
        return None
    zc = max(1, int(getattr(item, "z_count", 1) or 1))
    tc = max(1, int(getattr(item, "t_count", 1) or 1))
    if z_from is None or z_to is None:
        z_from, z_to = proj_range(item)
    z_from = max(0, min(int(z_from), zc - 1))
    z_to = max(z_from, min(int(z_to), zc - 1))
    t = max(0, min(int(t), tc - 1))
    base = t * zc
    _f, c, h, w = stack.shape
    out = None
    # 按 Y 分条：一次只开 (nz, C, band, W) 的工作数组（规格书 4.3.1 的约束）
    band = max(1, int(MAX_PIXELS // max(1, c * (z_to - z_from + 1) * max(1, w))))
    dt = _out_dtype(stack.dtype, mode)
    for y0 in range(0, h, band):
        y1 = min(h, y0 + band)
        chunk = stack[base + z_from: base + z_to + 1, :, y0:y1, :]
        if out is None:
            out = np.zeros((c, h, w), dtype=dt)
        if mode == "max":
            part = chunk.max(axis=0)
        elif mode == "sum":
            part = chunk.astype(np.float64).sum(axis=0)
            top = (float(np.iinfo(stack.dtype).max)
                   if np.issubdtype(stack.dtype, np.integer) else 1e30)
            part = np.clip(part, 0, min(top, float(np.iinfo(dt).max)
                                        if np.issubdtype(dt, np.integer) else top))
        elif mode == "mean":
            part = chunk.astype(np.float64).mean(axis=0)
        else:                                  # sd：看"哪里在变"
            part = chunk.astype(np.float64).std(axis=0)
        out[:, y0:y1, :] = part.astype(out.dtype, copy=False)
    if out is None:                            # 空栈兜底
        out = np.zeros((max(1, c), h, w), dtype=dt)
    return out


def _out_dtype(dtype, mode):
    """投影结果的 dtype：max 保持原位深；sum/mean/sd 提一档，别把结果截掉。"""
    d = np.dtype(dtype)
    if mode == "max":
        return d
    if mode == "sd":
        return np.float32        # 标准差数值小，转整数会被截成 0（实测踩过）
    if d == np.uint8:
        return np.uint16
    if d == np.uint16:
        return np.uint32 if mode == "sum" else np.uint16
    return np.float32


def ortho_slab(stack, item, x0, y0, x1, y1, ch=None, t=0):
    """沿取样线抽 (Z, L) 剖面（正交视图用）。

    返回 (slab, meta)：slab = (C, Z, L)（指定单通道时是 (Z, L)），
    meta 里有 step_xy / step_z / length_um / depth_um / scaled。
    """
    zc = max(1, int(getattr(item, "z_count", 1) or 1))
    tc = max(1, int(getattr(item, "t_count", 1) or 1))
    f, c, h, w = stack.shape
    n = max(2, int(round(max(abs(x1 - x0), abs(y1 - y0)))) + 1)
    xs = np.clip(np.linspace(x0, x1, n).round().astype(int), 0, w - 1)
    ys = np.clip(np.linspace(y0, y1, n).round().astype(int), 0, h - 1)
    # 正交视图默认看**整段 Z**（20 层就画 20 行）；只有用户手动限定了起止层才跟着限
    if (getattr(item, "proj_range_mode", "all") or "all") == "manual":
        z0, z1 = proj_range(item)
    else:
        z0, z1 = 0, zc - 1
    t = max(0, min(int(t), tc - 1))
    idx = [t * zc + z for z in range(z0, z1 + 1)]
    slab = np.transpose(stack[idx][:, :, ys, xs], (1, 0, 2))   # (C, Z, L)
    if ch is not None:
        slab = slab[int(ch)]
    umpp = float(getattr(item, "umpp", 0.0) or 0.0)
    zs = float(getattr(item, "z_step_um", 0.0) or 0.0)
    nz = slab.shape[-2] if slab.ndim == 2 else slab.shape[-2]
    meta = dict(step_xy=umpp, step_z=zs, n_l=n, n_z=nz,
                length_um=n * umpp, depth_um=(nz - 1) * zs, scaled=bool(zs > 0))
    return slab, meta
