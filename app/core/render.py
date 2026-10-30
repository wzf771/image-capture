# -*- coding: utf-8 -*-
"""合成彩色图、裁剪、画标尺、导出、缩略图。"""
from __future__ import annotations

import os

import numpy as np
from PIL import Image, ImageFilter

import paths
from core import bar as bar_mod
from core import loader, zproj
import copy
from core import raw as raw_mod
from core.model import GRAY, nice_bar_length


# ---------------------------------------------------------------- 合成

def view_item(item, frame=0):
    """显示 / 彩图导出用的"替身 item"：开着 Z 投影时，它的第 0 帧就是投影结果。

    为什么要替身：预览（`preview_for_view`）、合成（`compose`）、裁剪、标尺、缩略图
    这几条路径对清晰度是冻结的（规格书 §2.7）。投影只该改"看到哪一份数据"，
    不该改这些算法 —— 所以这里做一次浅拷贝，把 `_cache` 换成 (1, C, Y, X) 的投影结果，
    下游一行都不用动。XY 标定不变，裁剪框与标尺照旧。
    """
    mode = (getattr(item, "proj_mode", "none") or "none").lower()
    if mode == "none" or int(getattr(item, "z_count", 1) or 1) <= 1:
        return item
    try:
        stack = loader.load_stack(item)
        t, _z = item.tz_of(frame)
        plane = zproj.project_frame(stack, item, t=t, mode=mode)
    except Exception:                            # noqa: BLE001
        return item
    if plane is None:
        return item
    sub = copy.copy(item)                        # 浅拷贝：path / 标定 / 通道 / 裁剪框全共享
    sub._cache = np.ascontiguousarray(plane[None])
    sub.frames = sub.t_count = 1
    sub.z_count = 1
    sub.proj_mode = "none"                       # 防止递归
    sub._preview = None
    sub._ranges_ready = True                     # 别按投影结果重算显示区间（沿用原图的）
    sub._frame_ranges = None
    sub.range_mode = "global"
    return sub


def _map_channel(plane, ch, rng=None):
    v = plane.astype(np.float32)
    if rng:
        lo, hi = float(rng[0]), float(rng[1])       # 逐帧归一化给的区间
    else:
        lo, hi = float(ch.black), float(ch.white)
    if hi <= lo:
        hi = lo + 1.0
    return np.clip((v - lo) / (hi - lo), 0.0, 1.0)


def ranges_for(item, frame):
    """这一帧要用的显示区间覆盖（P0-4 逐帧归一化）；统一区间时返回 None。

    **只影响显示与合成彩图**；原始位深导出走 crop_planes，不碰这里（规格书 3.25.3）。
    """
    if getattr(item, "range_mode", "global") == "global":
        return None
    fr = getattr(item, "_frame_ranges", None)
    if not fr:
        return None
    f = int(frame)
    out = {c: v for (ff, c), v in fr.items() if ff == f}
    return out or None


WHITE_TINT = np.asarray((1.0, 1.0, 1.0), np.float32)


def compose(frame: np.ndarray, channels, ranges=None, mode="add") -> np.ndarray:
    """把一帧多通道数据合成 24bit 彩色（各通道按颜色叠加）。

    大图按横条分批算：一次只开几百行的工作数组。以前是整张图开 (h, w, 3) 的
    float32，16000×16000 就是 3 GB，机器直接被拖死。
    `ranges` = {通道序号: (黑, 白)}，给逐帧归一化用；None 时用通道自己的黑白点。

    `mode`（2026-09-26 用户反馈"弱荧光在 merge 里消失"）：
      · "add"（默认）：**加法完全叠加** `Σ(强度 × 颜色)`。每个通道的信息都留下，
        重叠区会叠成对应混合色（红+绿=黄）—— 但重叠很亮时会顶到纯白，这是正常的。
      · "max"：老行为，逐分量取最大 —— 谁亮谁覆盖，某路在 R/G/B 三路都弱就会被
        整路吃掉（实测 11% 的绿 + 73% 的红 = 只剩红）。留作可选项。
    明场（role=gray）一律按**灰阶**上色（三路等量），所以不会带任何色偏。
    """
    if channels and all(ch.role == "rgb" for ch in channels):
        # 本来就是彩色图（导出的合并图）：直接原样输出
        data = frame
        if data.ndim == 3 and data.shape[0] >= 3:
            return np.clip(np.transpose(data[:3], (1, 2, 0)), 0, 255).astype(np.uint8)
        if data.ndim == 3 and data.shape[-1] >= 3:
            return np.clip(data[..., :3], 0, 255).astype(np.uint8)
    add = str(mode or "add").lower() != "max"
    h, w = frame.shape[-2], frame.shape[-1]
    use = [ch for ch in channels
           if ch.role != "rgb" and ch.visible and ch.index < frame.shape[0]]
    out = np.zeros((h, w, 3), np.uint8)
    band = max(64, min(h, int(4_000_000 // max(1, w))))     # 每条约 400 万像素
    tints = {id(ch): np.asarray(ch.color, np.float32) / 255.0 for ch in use}
    for y0 in range(0, h, band):
        y1 = min(h, y0 + band)
        base = np.zeros((y1 - y0, w), np.float32)
        overlay = np.zeros((y1 - y0, w, 3), np.float32)
        for ch in use:
            v = _map_channel(frame[ch.index][y0:y1], ch,
                             (ranges or {}).get(ch.index))
            tint = WHITE_TINT if ch.role == "gray" else tints[id(ch)]
            if add:
                overlay += v[..., None] * tint
            elif ch.role == "gray":
                np.maximum(base, v, out=base)
            else:
                np.maximum(overlay, v[..., None] * tint, out=overlay)
        if not add:
            np.maximum(base[..., None], overlay, out=overlay)
        out[y0:y1] = (np.clip(overlay, 0.0, 1.0) * 255.0).astype(np.uint8)
    return out


def preview_planes(item, frame=0, max_side=1100):
    """把某一帧降采样后缓存起来，供界面反复合成、拖动时用。"""
    key = ("planes", frame, max_side)
    cached = getattr(item, "_preview", None)
    if cached and cached[0] == key:
        return cached[1]
    stack = loader.load_stack(item)
    frame = max(0, min(frame, stack.shape[0] - 1))
    data = stack[frame]
    c, h, w = data.shape[:3]
    step = max(1, int(np.ceil(max(h, w) / float(max_side))))
    if step > 1:
        img = Image.fromarray(data[0]) if c else None
        planes = []
        for i in range(c):
            im = Image.fromarray(data[i])
            planes.append(np.asarray(im.resize((max(1, w // step), max(1, h // step)),
                                               Image.BILINEAR)))
        small = np.stack(planes)
    else:
        small = data
    item._preview = (key, small)
    return small


def preview_for_view(item, frame, rect_norm, target):
    """按"当前可见范围"直接从原分辨率重采样一次，得到锐利的预览图。

    rect_norm = (x0, y0, x1, y1) 归一化可见范围；target = (宽, 高) 目标像素。
    只重采样一次（LANCZOS），避免"先缩小再缩放"造成的发糊。
    """
    stack = loader.load_stack(item)
    t_count, c_count, h, w = stack.shape
    frame = max(0, min(frame, t_count - 1))
    x0 = int(max(0, min(w - 1, rect_norm[0] * w)))
    y0 = int(max(0, min(h - 1, rect_norm[1] * h)))
    x1 = int(max(x0 + 1, min(w, rect_norm[2] * w)))
    y1 = int(max(y0 + 1, min(h, rect_norm[3] * h)))
    tw, th = max(16, int(target[0])), max(16, int(target[1]))
    data = stack[frame][:, y0:y1, x0:x1]
    shrink = (x1 - x0) / float(max(1, tw))
    planes = []
    for c in range(data.shape[0]):
        plane = data[c]
        if shrink >= 3:                     # 缩得很狠时先用箱式平均粗缩，快很多
            k = max(2, int(shrink // 2))
            ph, pw = plane.shape
            h2, w2 = (ph // k) * k, (pw // k) * k
            if h2 >= 16 and w2 >= 16:
                box = plane[:h2, :w2].reshape(h2 // k, k, w2 // k, k).mean(axis=(1, 3))
                plane = box.astype(plane.dtype if plane.dtype != np.uint8 else np.uint8)
        im = Image.fromarray(plane)
        planes.append(np.asarray(im.resize((tw, th), Image.LANCZOS)))
    used = (x0 / float(w), y0 / float(h), x1 / float(w), y1 / float(h))
    return np.stack(planes), used


def sharpen_display(rgb, radius=1.3, percent=75, threshold=2):
    """屏幕上看的图补一点锐度（整图挤进屏幕必然发软，看着像"糊"）。

    只作用于界面预览；导出走的是另一条路，一个像素都不动。
    输入必须是 8bit 的 RGB（合成之后的）。
    """
    if rgb is None or rgb.dtype != np.uint8 or rgb.ndim != 3:
        return rgb
    try:
        im = Image.fromarray(rgb).filter(
            ImageFilter.UnsharpMask(radius=radius, percent=percent, threshold=threshold))
        return np.asarray(im)
    except Exception:                            # noqa: BLE001
        return rgb


# ---------------------------------------------------------------- 裁剪

def crop_rect(item, box, st):
    """把 µm 的裁剪框换成像素矩形；返回 (x, y, w, h, pad)。"""
    umpp = item.umpp if item.umpp > 0 else 0.0
    if umpp <= 0:
        return (0, 0, item.width, item.height, False)
    wpx = int(round(box["w"] / umpp))
    hpx = int(round(box["h"] / umpp))
    pad = False
    if wpx > item.width or hpx > item.height:
        if st.too_small == "skip":
            return None
        if st.too_small == "shrink":
            wpx, hpx = min(wpx, item.width), min(hpx, item.height)
        else:
            pad = True
    x = int(round(box["x"] / umpp))
    y = int(round(box["y"] / umpp))
    x = max(-wpx + 1, min(x, item.width - 1))
    y = max(-hpx + 1, min(y, item.height - 1))
    return (x, y, wpx, hpx, pad)


def crop_image(rgb_full: np.ndarray, rect, fill=(0, 0, 0)):
    """按矩形裁剪，超出边界的地方补边。"""
    if rect is None:
        return None
    x, y, w, h, pad = rect
    H, W = rgb_full.shape[:2]
    out = np.empty((h, w, 3), np.uint8)
    out[...] = fill
    sx0, sy0 = max(0, x), max(0, y)
    sx1, sy1 = min(W, x + w), min(H, y + h)
    if sx1 > sx0 and sy1 > sy0:
        out[sy0 - y:sy1 - y, sx0 - x:sx1 - x] = rgb_full[sy0:sy1, sx0:sx1]
    return out


def crop_planes(frame_data: np.ndarray, rect):
    """只在裁剪区域内取各通道数据（全分辨率，速度快）。"""
    if rect is None:
        return frame_data
    x, y, w, h, _pad = rect
    c = frame_data.shape[0]
    H, W = frame_data.shape[1], frame_data.shape[2]
    out = np.zeros((c, h, w), dtype=frame_data.dtype)
    sx0, sy0 = max(0, x), max(0, y)
    sx1, sy1 = min(W, x + w), min(H, y + h)
    if sx1 > sx0 and sy1 > sy0:
        out[:, sy0 - y:sy1 - y, sx0 - x:sx1 - x] = frame_data[:, sy0:sy1, sx0:sx1]
    return out


# ---------------------------------------------------------------- 缩略图

def quick_rgb(item, frame=0, max_side=1200, mode="add"):
    """拿一张（可能缩小的）合成图做识别用，同时给出缩小倍数。"""
    planes = preview_planes(item, frame=frame, max_side=max_side)
    factor = item.width / float(planes.shape[2]) if planes.shape[2] else 1.0
    return compose(planes, item.channels, ranges_for(item, frame), mode=mode), factor


def make_thumb(item, size=256, planes=None, mode="add") -> str:
    item = view_item(item, 0)          # 投影模式下缩略图也要跟着投影走
    path = loader.thumb_path(item, size)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    # planes 可以传一份已经缩好的小图，省掉对原图的解码和合成（出缩略图快很多）
    stack = planes if planes is not None else loader.load_stack(item)
    ranges = loader.estimate_ranges(stack)
    # 兜底：只有黑白点还是空的时候才补（按 ch.index 取，别按列表位置 —— 见 loader._auto_ranges）
    for ch in item.channels:
        idx = int(getattr(ch, "index", 0))
        if not (0 <= idx < len(ranges)):
            continue
        lo, hi, _top = ranges[idx]
        if ch.white <= ch.black or ch.white <= 0:
            ch.black, ch.white = lo, hi
    rgb = compose(stack[0], item.channels, ranges_for(item, 0), mode=mode)
    im = Image.fromarray(rgb)
    w, h = im.size
    side = min(w, h)
    im = im.crop(((w - side) // 2, (h - side) // 2, (w + side) // 2, (h + side) // 2))
    im = im.resize((size, size), Image.LANCZOS)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    im.save(tmp, "JPEG", quality=82)
    os.replace(tmp, path)
    return path


# ---------------------------------------------------------------- 导出

def _save(rgb: np.ndarray, path: str, umpp: float = 0.0):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".tif", ".tiff"):
        import tifffile
        if umpp > 0:
            tifffile.imwrite(path, rgb, photometric="rgb",
                             resolution=(1e4 / umpp, 1e4 / umpp), resolutionunit="CENTIMETER",
                             metadata=None, compression="zlib")
        else:
            tifffile.imwrite(path, rgb, photometric="rgb", compression="zlib")
    else:
        im = Image.fromarray(rgb)
        if umpp > 0:
            dpi = 25400.0 / umpp
            im.save(path, dpi=(dpi, dpi))
        else:
            im.save(path)


def out_ext(item, st):
    if st.out_format == "png":
        return ".png"
    if st.out_format == "tiff":
        return ".tif"
    if st.out_format == "jpg":
        return ".jpg"
    src = os.path.splitext(item.file_path)[1].lower()
    if src in (".tif", ".tiff"):
        return ".tif"
    if src in (".jpg", ".jpeg"):
        return ".jpg"
    if src == ".png":
        return ".png"
    return ".tif"                                # OIB 没有对应位图格式，默认 TIFF


def channel_variants(item, st):
    """按导出内容返回 [(文件名后缀, 只显示哪些通道)]。"""
    out = []
    if st.exp_merge:
        out.append((st.out_suffix, None))
    for i, want in enumerate(st.exp_ch[:3]):
        if not want or i >= len(item.channels):
            continue
        ch = item.channels[i]
        out.append((st.out_suffix + "_%s" % _tag(ch, i), [i]))
    return out


def _tag(ch, i):
    if ch.role == "green":
        return "CH%d绿" % (i + 1)
    if ch.role == "red":
        return "CH%d红" % (i + 1)
    if ch.role == "rgb":
        return "RGB"
    return "CH%d灰" % (i + 1)


# ---------------------------------------------------------------- 原始位深导出

def raw_suffix(dtype) -> str:
    """位深后缀：_raw8 / _raw16 / _raw32（规格书 3.11.5）。"""
    d = np.dtype(dtype)
    if d == np.uint8:
        return "_raw8"
    if d in (np.uint32, np.int32):
        return "_raw32"
    if d in (np.float32, np.float64):
        return "_rawf"
    return "_raw16"


def _raw_dtype(planes: np.ndarray):
    """原始导出用的 dtype：**原样**，绝不按最大值拉伸到满量程（规格书 3.11.2）。

    uint16 里装 12bit 数据（最大值 4095）→ 导出来最大值还得是 4095。
    只有 int16/int32/float 这类罕见情形才转 uint16，并由调用方在报告里标注。
    """
    d = np.dtype(planes.dtype)
    if d in (np.uint8, np.uint16, np.uint32, np.float32):
        return d, ""
    if d == np.int16:
        return np.uint16, "int16 → uint16（负值截到 0）"
    if d in (np.int32, np.int64):
        return np.uint32, "整型 → uint32"
    if d in (np.float64,):
        return np.float32, "float64 → float32"
    return np.uint16, "%s → uint16" % d


def build_ome(item, name: str, umpp: float, channels=None, axes="CYX") -> dict:
    """OME-XML 元数据（规格书 3.11.4）。DimensionOrder 由 tifffile 写成 XYCZT。"""
    chans = list(channels if channels is not None else (item.channels or []))
    meta = {"axes": axes, "Name": name}
    if chans:                       # 空列表会让 tifffile 取 Name[0] 时越界（实测踩过）
        meta["Channel"] = {
            "Name": [(ch.name or ("CH%d" % (ch.index + 1))) for ch in chans]}
    if umpp and umpp > 0:                      # 未标定：不写物理尺寸（规格书 3.12）
        meta.update(PhysicalSizeX=float(umpp), PhysicalSizeXUnit="µm",
                    PhysicalSizeY=float(umpp), PhysicalSizeYUnit="µm")
        z = float(getattr(item, "z_step_um", 0.0) or 0.0)
        # 只在数据真的有 Z 轴时才写 PhysicalSizeZ。
        # 我们导出的每个文件都是**单个 Z 平面**（Z 层在文件名里），
        # 写了会让人以为文件里有多层（投影图更是必须不写 —— 验收第 6 条）。
        if z > 0 and "Z" in (axes or "").upper():
            meta.update(PhysicalSizeZ=z, PhysicalSizeZUnit="µm")
    ex = [float(ch.ex or 0.0) for ch in chans]
    em = [float(ch.em or 0.0) for ch in chans]
    if chans and any(ex):
        meta["Channel"]["ExcitationWavelength"] = ex
    if chans and any(em):
        meta["Channel"]["EmissionWavelength"] = em
    if chans:
        meta["Channel"]["Color"] = ["#%02X%02X%02X"
                                    % tuple(int(v) for v in (ch.color or (255, 255, 255))[:3])
                                    for ch in chans]
    return meta


def proc_record(item, umpp: float = 0.0) -> dict:
    """机器读的处理记录（私有 tag 65000）。处理链为空时**不写**（规格书 3.11.8）。"""
    steps = []
    for s in (getattr(item, "process", None) or []):
        steps.append(dict(kind=getattr(s, "kind", ""),
                          params=dict(getattr(s, "params", None) or {}),
                          enabled=bool(getattr(s, "enabled", True))))
    if not steps:
        return {}
    return dict(app="ImageCapture", schema=raw_mod.PROC_SCHEMA, steps=steps,
                ref_frame=int(getattr(item, "ref_frame", 0) or 0),
                umpp=float(umpp or 0.0), ver=1)


def embed_estimate(item, rect, n_chan=1) -> int:
    """内嵌链前数据的体积预估（字节，压缩前）；界面用来提示"约 +xx MB"。"""
    try:
        if rect is None:
            w, h = item.width, item.height
        else:
            w, h = rect[2], rect[3]
        dtype = np.dtype(getattr(item, "bits", 8) > 8 and np.uint16 or np.uint8)
        return int(w) * int(h) * max(1, n_chan) * dtype.itemsize
    except Exception:                                    # noqa: BLE001
        return 0


def export_raw(item, st, stack, frame, rect, folder, stem, log=None):
    """原始位深导出：逐通道 + 多通道栈；OME-XML；处理链非空时内嵌链前数据。

    与彩图的区别（规格书 3.11）：**不烘焙显示区间、不放大、不降位深**。
    """
    written, notes = [], []
    os.makedirs(folder, exist_ok=True)
    planes = crop_planes(stack[frame], rect)             # (C, Y, X) 原始 dtype
    dtype, conv = _raw_dtype(planes)
    if conv:
        planes = planes.astype(dtype, copy=False)
        notes.append(conv)
    suffix = raw_suffix(dtype)
    chans = list(item.channels or [])
    # —— 处理链非空 → 记录 + 内嵌可还原的链前数据（规格书 3.11.7 / N2·N3）
    proc = proc_record(item, item.umpp)
    blobs = []
    if proc and getattr(st, "exp_raw_embed", True):
        try:
            raw_full = loader.raw_stack(item)
            raw_frame = max(0, min(int(frame), raw_full.shape[0] - 1))
            raw_crop = crop_planes(raw_full[raw_frame], rect)
            if raw_crop.nbytes * 1.05 > raw_mod.MAX_EMBED:
                notes.append("链前数据 %.1f GB 超过内嵌上限，未内嵌（无法精确还原）"
                             % (raw_crop.nbytes / float(1 << 30)))
                blobs = []
            else:
                blobs = raw_mod.encode_blocks(raw_crop)
        except Exception as exc:                         # noqa: BLE001
            notes.append("链前数据没能读出（%s），未内嵌" % exc)
            blobs = []
    # —— 单通道
    if getattr(st, "exp_raw_single", True):
        for i in range(planes.shape[0]):
            ch = chans[i] if i < len(chans) else None
            tagname = _tag(ch, i) if ch is not None else "CH%d" % (i + 1)
            p = os.path.join(folder, "%s%s_%s%s.tif" % (stem, st.out_suffix, tagname, suffix))
            ome = (build_ome(item, os.path.splitext(os.path.basename(p))[0], item.umpp,
                             [ch] if ch is not None else [], axes="YX")
                   if st.exp_raw_ome else None)
            if ome and proc:
                line = raw_mod.process_line(proc)
                if line:
                    ome["Description"] = line
            raw_mod.save_raw_tiff(p, planes[i], umpp=item.umpp, ome=ome,
                                  proc=(proc or None), blobs=blobs)
            written.append(p)
            if log:
                log("导出 %s" % os.path.basename(p))
    # —— 多通道栈（一个文件装全部通道，不受导出勾选的前 3 个限制）
    if getattr(st, "exp_raw_stack", False):
        p = os.path.join(folder, "%s%s%s_C%d.tif" % (stem, st.out_suffix, suffix,
                                                     planes.shape[0]))
        ome = (build_ome(item, os.path.splitext(os.path.basename(p))[0], item.umpp,
                         chans) if st.exp_raw_ome else None)
        if ome and proc:
            line = raw_mod.process_line(proc)
            if line:
                ome["Description"] = line
        raw_mod.save_raw_tiff(p, planes, umpp=item.umpp, ome=ome,
                              proc=(proc or None), blobs=blobs)
        written.append(p)
        if log:
            log("导出 %s" % os.path.basename(p))
    if item.umpp <= 0:
        notes.append("未标定：已导出像素，未写 PhysicalSize")
    return written, notes, dtype


def export_item(item, group, st, frame=0, out_root=None, log=None):
    """导出单张（一帧）的所有勾选内容，返回 (写出的文件列表, 报告行)。"""
    # 组里如果设了自定义标尺位置，导出时就用这个位置（和界面上拖好的位置一致）
    if getattr(group, "bar_anchor", None):
        import dataclasses
        st = dataclasses.replace(
            st, bar_position="custom", bar_anchor=tuple(group.bar_anchor),
            bar_text_anchor=(tuple(group.bar_text_anchor)
                             if group.bar_text_anchor else None))
    stack = loader.load_stack(item)
    frame = max(0, min(frame, stack.shape[0] - 1))
    full = compose(stack[frame], item.channels, ranges_for(item, frame),
                   mode=getattr(st, "merge_mode", "add"))
    rect = crop_rect(item, group.box_for(item), st)
    if rect is None:
        return [], dict(path=item.path, group=group.title, note="视野不足且设置为跳过")
    crop = crop_image(full, rect)
    if crop is None:
        return [], dict(path=item.path, group=group.title, note="裁剪失败")
    # 先把图放大到位，再画标尺：这样标尺永远按最终分辨率高清绘制，不跟图片一起变糊
    zoom = max(1, min(8, int(getattr(st, "export_zoom", 1) or 1)))
    if zoom > 1:
        crop = np.asarray(Image.fromarray(crop).resize(
            (crop.shape[1] * zoom, crop.shape[0] * zoom), Image.LANCZOS))
    umpp_eff = item.umpp / zoom if item.umpp > 0 else 0.0
    bar_um = 0.0
    if st.bar_enabled and umpp_eff > 0:
        bar_um = bar_mod.bar_length_for(crop.shape[1], umpp_eff, st)
    out_root = out_root or paths.OUTPUT_DIR
    sub = group.title.replace("/", "_").replace("\\", "_")
    folder = os.path.join(out_root, sub) if st.out_subdir == "by_group" else out_root
    os.makedirs(folder, exist_ok=True)
    stem = os.path.splitext(item.name)[0]
    # 文件名按维度标（规格书 3.18.5）：z003 / t005 / 两者都有就都写上
    t_i, z_i = item.tz_of(frame)
    tag = ""
    if int(getattr(item, "z_count", 1) or 1) > 1:
        tag += "_z%03d" % (z_i + 1)
    if int(getattr(item, "t_count", 1) or 1) > 1:
        tag += "_t%03d" % (t_i + 1)
    if not tag and stack.shape[0] > 1:           # 计数对不上时的兜底
        tag = "_f%03d" % (frame + 1)
    stem += tag
    ext = out_ext(item, st)

    written = []
    for suffix, only in channel_variants(item, st):
        shown = [ch.visible for ch in item.channels]
        if only is not None:
            for i, ch in enumerate(item.channels):
                ch.visible = (i in only)
        try:
            if only is None:
                img = crop
            else:
                img = crop_image(compose(stack[frame], item.channels,
                                         ranges_for(item, frame),
                                         mode=getattr(st, "merge_mode", "add")), rect)
                if zoom > 1:
                    img = np.asarray(Image.fromarray(img).resize(
                        (img.shape[1] * zoom, img.shape[0] * zoom), Image.LANCZOS))
            if st.bar_enabled and umpp_eff > 0:
                img = bar_mod.draw_bar(img, umpp_eff, st, bar_um)
            path = os.path.join(folder, stem + suffix + ext)
            # 写的是放大后的像素，分辨率也必须用放大后的 umpp_eff（2026-10-23 修）：
            # 之前用 item.umpp，导出 4× 的图仍自称原始 µm/px，Fiji 里量标尺会大 4 倍。
            _save(img, path, umpp_eff)
            written.append(path)
            if log:
                log("导出 %s" % os.path.basename(path))
        finally:
            for ch, was in zip(item.channels, shown):
                ch.visible = was

    # 额外送一张只有标尺的透明 PNG：放进 AI 里放大也不糊
    if st.bar_enabled and umpp_eff > 0 and getattr(st, "bar_extra_png", False):
        layer, _len, _lay = bar_mod.bar_layer_only(crop.shape[1], crop.shape[0], umpp_eff,
                                                   st, bar_um)
        p = os.path.join(folder, stem + st.out_suffix + "_标尺.png")
        layer.save(p)
        written.append(p)

    # —— 原始位深导出（P0-2）：不烘焙显示区间、不放大、不降位深，强制 TIFF ——
    raw_notes, raw_dtype = [], ""
    if getattr(st, "exp_raw_single", False) or getattr(st, "exp_raw_stack", False):
        try:
            files, raw_notes, raw_dtype = export_raw(item, st, stack, frame, rect,
                                                     folder, stem, log)
            written.extend(files)
        except Exception as exc:                          # noqa: BLE001
            raw_notes.append("原始位深导出失败：%s" % exc)

    # —— Z 投影图（P1-5）：投影只改 Z，XY 标定不变 → 裁剪框/标尺照旧复用 ——
    if getattr(st, "exp_proj", False) and (item.proj_mode or "none") != "none":
        try:
            tag = zproj.proj_tag(item.proj_mode)
            vit = view_item(item, frame)
            vstack = loader.load_stack(vit)
            vfull = compose(vstack[0], vit.channels, ranges_for(vit, 0),
                            mode=getattr(st, "merge_mode", "add"))
            vcrop = crop_image(vfull, rect)
            if st.bar_enabled and umpp_eff > 0:
                vcrop = bar_mod.draw_bar(vcrop, umpp_eff, st, bar_um)
            p = os.path.join(folder, "%s%s_%s%s" % (stem, st.out_suffix, tag, ext))
            # 同上：投影图用的是放大后的成品像素，分辨率也按 umpp_eff 写。
            _save(vcrop, p, umpp_eff)
            written.append(p)
            if log:
                log("导出 %s" % os.path.basename(p))
            if st.exp_raw_single or st.exp_raw_stack:
                # 原始位深的投影图：SizeZ=1、不写 PhysicalSizeZ（验收第 6 条）
                import dataclasses
                st_p = dataclasses.replace(st, out_suffix="")
                rf, rn, _d = export_raw(vit, st_p, vstack, 0, rect, folder,
                                        "%s%s_%s" % (stem, st.out_suffix, tag), log)
                written.extend(rf)
                raw_notes.extend(rn)
        except Exception as exc:                          # noqa: BLE001
            raw_notes.append("Z 投影导出失败：%s" % exc)

    row = dict(group=group.title, name=item.name, umpp=round(item.umpp, 5),
               calib=item.calib, frame=(frame + 1 if stack.shape[0] > 1 else 1),
               frames=stack.shape[0],
               box="x=%d y=%d %dx%d px" % (rect[0], rect[1], rect[2], rect[3]),
               field="%.2f × %.2f µm" % (rect[2] * item.umpp, rect[3] * item.umpp),
               bar=("%g µm = %d px" % (bar_um, round(bar_um / umpp_eff)) if bar_um else "无"),
               zoom=("放大 %d×" % zoom),
               raw=(str(np.dtype(raw_dtype)) if raw_dtype else ""),
               note="；".join(raw_notes),
               files=len(written), out="; ".join(os.path.basename(p) for p in written))
    return written, row
