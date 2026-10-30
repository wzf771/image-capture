# -*- coding: utf-8 -*-
"""多 tile / 拼图（规格书 P1-9）。

三种场景（4.22.1）：单文件多 Scene / 单文件 tiled / **多文件阵列**。
本次把"多文件阵列"做到可用：文件名解析行列 → 元数据位置优先 →
（可选的）相邻相位相关微调 → 逐 tile 落盘。

**内存与写入（4.22.3，关键）**：拼好的画布用**磁盘 memmap**当缓冲，一片一片贴，
最后让 tifffile 从 memmap 流式写出 → 峰值内存 ≈ 一个 tile，而不是整张拼图。

拼接结果就是一个普通 `ImageItem`（带 `stitch` 字段）：照常参与分组/裁剪/标尺/导出；
`stitch` 只记来源与布局，进 `.icproj` 不存像素，重开工程时按参数重拼。
"""
from __future__ import annotations

import os
import re

import numpy as np

from core import loader

try:
    import cv2
except Exception:                                    # noqa: BLE001
    cv2 = None

_GRID_PATTERNS = (
    re.compile(r"[rR](\d+)[_\-]?[cC](\d+)"),          # r01c02
    re.compile(r"[xX](\d+)[_\-]?[yY](\d+)"),           # x03_y05
    re.compile(r"tile[_\-]?(\d+)[_\-](\d+)"),          # tile_3_5
)


def parse_grid(paths):
    """从文件名里解析行列：{(row, col): path}；解析不出来返回 None。"""
    cells = {}
    for p in paths:
        stem = os.path.splitext(os.path.basename(p))[0]
        for pat in _GRID_PATTERNS:
            m = pat.search(stem)
            if m:
                cells[(int(m.group(1)), int(m.group(2)))] = p
                break
    return cells if len(cells) >= 4 else None


def grid_shape(cells):
    rows = max(r for r, _c in cells) - min(r for r, _c in cells) + 1
    cols = max(c for _r, c in cells) - min(c for _r, c in cells) + 1
    return rows, cols


def _stage_pos(path):
    """下机文件里的 tile 绝对位置（µm）。拿不到返回 None。"""
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext in (".oib", ".oif"):
            import oiffile
            with oiffile.OifFile(path) as f:
                mf = f.mainfile
                x = y = None
                for i in range(12):
                    pa = mf.get("Axis %d Parameters Common" % i)
                    if not pa:
                        continue
                    code = str(pa.get("AxisCode", "")).upper()
                    if code == "X":
                        x = float(pa.get("AbsolutePosition") or 0.0)
                    elif code == "Y":
                        y = float(pa.get("AbsolutePosition") or 0.0)
                if x is not None and y is not None:
                    return (x, y)
        elif ext == ".czi":
            import czifile
            with czifile.CziFile(path) as czi:
                xml = czi.metadata()
            mx = re.search(r"<PositionX>([0-9.eE+-]+)</PositionX>", xml)
            my = re.search(r"<PositionY>([0-9.eE+-]+)</PositionY>", xml)
            if mx and my:
                return (float(mx.group(1)), float(my.group(1)))
    except Exception:                                # noqa: BLE001
        return None
    return None


def plan(paths, overlap=0.10, tile_shape=None, overlap_px=None):
    """算布局：元数据位置优先，其次按均匀网格 + 重叠率。

    `overlap` 是比例（两轴相同，够用）；已知具体重叠像素时传 `overlap_px=(oy, ox)`，
    更准（真实拼图的横向/纵向重叠像素常常不一样，比例口径会把步进算歪）。
    """
    grid = parse_grid(paths)
    if grid is None:                                 # 没编号：按文件名排序当一维阵列
        ordered = sorted(paths)
        cols = max(1, int(round(len(ordered) ** 0.5)))
        grid = {(i // cols, i % cols): p for i, p in enumerate(ordered)}
    rows, cols = grid_shape(grid)
    r0 = min(r for r, _c in grid)
    c0 = min(c for _r, c in grid)
    if tile_shape is None:
        it0 = loader.probe(grid[(r0, c0)])
        tile_shape = (max(1, len(it0.channels)), it0.height, it0.width)
    c_n, h, w = tile_shape
    ext_ok = all(os.path.splitext(p)[1].lower() in (".oib", ".oif", ".czi")
                 for p in grid.values())
    pos = None
    if ext_ok:
        got = {rc: _stage_pos(p) for rc, p in grid.items()}
        if all(v is not None for v in got.values()):
            pos = got
    if pos:
        it0 = loader.probe(grid[(r0, c0)])
        umpp = float(it0.umpp or 0.0)
        if umpp > 0:
            xs = [v[0] for v in pos.values()]
            ys = [v[1] for v in pos.values()]
            dx = (max(xs) - min(xs)) / max(1, cols - 1) if cols > 1 else w * umpp
            dy = (max(ys) - min(ys)) / max(1, rows - 1) if rows > 1 else h * umpp
            offsets = {rc: (int(round((x - min(xs)) / umpp)),
                            int(round((y - min(ys)) / umpp)))
                       for rc, (x, y) in pos.items()}
            return dict(mode="meta", rows=rows, cols=cols, c_count=c_n, tile=(h, w),
                        offsets=_json_offsets(offsets),
                        canvas=[int(round((max(ys) - min(ys)) / umpp)) + h,
                                int(round((max(xs) - min(xs)) / umpp)) + w],
                        step=[round(dy / umpp, 2), round(dx / umpp, 2)],
                        umpp=umpp, sources=[grid[k] for k in sorted(grid)])
    if overlap_px:
        step_y = int(round(h - float(overlap_px[0])))
        step_x = int(round(w - float(overlap_px[1])))
    else:
        step_x = int(round(w * (1.0 - float(overlap))))
        step_y = int(round(h * (1.0 - float(overlap))))
    offsets = {rc: ((rc[1] - c0) * step_x, (rc[0] - r0) * step_y) for rc in grid}
    return dict(mode="grid", rows=rows, cols=cols, c_count=c_n, tile=(h, w),
                offsets=_json_offsets(offsets),
                canvas=[(rows - 1) * step_y + h, (cols - 1) * step_x + w],
                step=[step_y, step_x], umpp=float(loader.probe(grid[(r0, c0)]).umpp or 0.0),
                overlap=(list(overlap_px) if overlap_px else float(overlap)),
                sources=[grid[k] for k in sorted(grid)])


def _json_offsets(offsets):
    """{(r,c): (x,y)} → {"r,c": [x,y]}：工程文件里键必须是字符串。"""
    return {"%d,%d" % k: [int(v[0]), int(v[1])] for k, v in offsets.items()}


def _offsets_pairs(doc):
    out = []
    for k, v in (doc.get("offsets") or {}).items():
        if isinstance(k, str):
            r, c = [int(x) for x in k.split(",")]
        else:
            r, c = int(k[0]), int(k[1])
        out.append(((r, c), (int(v[0]), int(v[1]))))
    return sorted(out, key=lambda kv: kv[0])


def free_space_ok(path, need_bytes) -> bool:
    try:
        import shutil as _sh
        root = os.path.dirname(os.path.abspath(path)) or "."
        return _sh.disk_usage(root).free > need_bytes
    except Exception:                                # noqa: BLE001
        return True


def build(doc, out_path, progress=None, refine=True):
    """按布局把 tile 贴成一张图并写盘，返回写好的 doc（含 path）。

    画布是**磁盘 memmap**：一次只驻留一个 tile，写 TIFF 时 tifffile 从 memmap
    流式读 → 峰值内存 ≈ 一个 tile（规格书 4.22.3 的硬约束）。
    """
    import tifffile
    h, w = doc["tile"]
    canvas_h, canvas_w = doc["canvas"][0], doc["canvas"][1]
    c_n = int(doc.get("c_count") or 1)
    srcs = list(doc["sources"])
    pairs = dict(_offsets_pairs(doc))
    keys = [k for k, _v in _offsets_pairs(doc)]
    need = int(canvas_h) * int(canvas_w) * c_n * 2 * 2      # memmap + 输出，留 2 倍余量
    if not free_space_ok(out_path, need):
        raise RuntimeError("磁盘空间不足：这张拼图大约需要 %.0f MB" % (need / (1 << 20)))
    tmp = out_path + ".canvas.tmp"
    buf = np.memmap(tmp, dtype=np.uint16, mode="w+",
                    shape=(c_n, int(canvas_h), int(canvas_w)))
    buf[:] = 0
    try:
        placed = {}
        for i, src in enumerate(srcs):
            if callable(progress):
                progress(i, len(srcs), os.path.basename(src))
            it = loader.probe(src)
            plane = loader.read_source(it)[0]
            key = keys[i] if i < len(keys) else (0, i)
            ox, oy = pairs.get(key, (0, 0))
            if refine and doc.get("mode") == "grid":
                ref = _neighbor(placed, key)
                if ref is not None:
                    dx, dy = _refine_shift(ref, plane[0])
                    ox, oy = ox + int(round(dx)), oy + int(round(dy))
            _paste(buf, plane, int(ox), int(oy))
            placed[key] = plane
        buf.flush()
        umpp = float(doc.get("umpp") or 0.0)
        kw = dict(photometric="minisblack", compression="zlib")
        if umpp > 0:
            kw.update(resolution=(1e4 / umpp, 1e4 / umpp), resolutionunit="CENTIMETER")
        tifffile.imwrite(out_path, np.asarray(buf), **kw)
    finally:
        del buf
        try:
            os.remove(tmp)
        except OSError:
            pass
    out = dict(doc)
    out["path"] = out_path
    out["refine"] = bool(refine and doc.get("mode") == "grid")
    return out


def _paste(buf, plane, ox, oy):
    """把一个 tile 贴到画布上（越界自动裁）。"""
    c_n, ch, cw = buf.shape
    for c in range(min(c_n, plane.shape[0])):
        src = plane[c]
        sh, sw = src.shape
        x0, y0 = max(0, ox), max(0, oy)
        x1, y1 = min(cw, ox + sw), min(ch, oy + sh)
        if x1 <= x0 or y1 <= y0:
            continue
        buf[c, y0:y1, x0:x1] = src[y0 - oy:y1 - oy, x0 - ox:x1 - ox]


def _neighbor(placed, key):
    """相位相关只用**真邻接**的 tile 当参考：优先左邻，其次上邻。

    栅格扫描顺序里前一块可能是对角（比如 (1,0) 的前一块是 (0,1)），
    拿对角去做相关是纯噪声 —— 实测这种"参考选错"会把 tile 挪飞。
    """
    r, c = key
    for cand in ((r, c - 1), (r - 1, c)):
        if cand in placed:
            return placed[cand]
    return None


def _refine_shift(prev_plane, plane, limit=5.0):
    """相邻 tile 的相位相关微调（重叠太小或置信度低就返回 0）。"""
    if cv2 is None:
        return 0.0, 0.0
    try:
        (dx, dy), resp = cv2.phaseCorrelate(np.asarray(prev_plane[-1], np.float32),
                                            np.asarray(plane[0], np.float32))
        if abs(dx) > limit or abs(dy) > limit or resp < 0.05:
            return 0.0, 0.0
        return float(dx), float(dy)
    except Exception:                                # noqa: BLE001
        return 0.0, 0.0


def stitch_paths(paths, out_dir, overlap=0.10, progress=None):
    """多文件阵列 → 一个 ImageItem（规格书 4.22.4）。"""
    doc = plan(paths, overlap=overlap)
    stem = os.path.splitext(os.path.basename(paths[0]))[0]
    out_path = os.path.join(out_dir, stem + "_拼接.tif")
    doc = build(doc, out_path, progress=progress)
    it = loader.probe(out_path)
    it.stitch = doc
    it.name = "%s · 拼接 %d×%d · %d×%d" % (stem, doc["cols"], doc["rows"],
                                           doc["canvas"][1], doc["canvas"][0])
    it.note = "拼接来源 %d 个 tile（%s）" % (len(paths), doc["mode"])
    return it


def restitch(item, progress=None):
    """工程文件里只存参数 → 重开时按参数重拼（4.22.1 的取舍）。"""
    doc = dict(getattr(item, "stitch", None) or {})
    if not doc.get("sources"):
        return None
    out = build(doc, doc.get("path") or (item.file_path + ".rebuilt.tif"),
                progress=progress, refine=bool(doc.get("refine")))
    item.stitch = out
    return out
