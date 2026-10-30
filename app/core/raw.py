# -*- coding: utf-8 -*-
"""原始位深导出的私有 TIFF tag：处理记录 + 链前数据（规格书 3.11.7 / 3.11.8）。

**为什么内嵌"链前数据"而不做逆运算**（写在这里，免得以后有人"优化"掉）：

1. 亚像素平移不可逆：`warpAffine` 正向插值一次、再反向插一次 ≠ 原图（会糊一点点）；
2. 背景扣除 clip 到 0 之后，负值信息已经没了；
3. 去卷积本质不可逆。

所以"精确还原"只能靠内嵌链前数据；处理记录仍然要写 —— 用户要看"做过哪几步"，
合作者要照参数复现。两者缺一不可。

**本软件唯一的专有格式是 `.icproj`**：这里不生成 `.icraw`、不生成 sidecar，
一切都塞进同一条标准 TIFF 的私有 tag 里，别的软件当未知 tag 忽略即可。

tag 布局：
  65000           处理记录 JSON（UTF-8，人能读、机器也能读）
  65001、65002…   链前数据分块（每块前 32 字节小端头 + zlib 载荷）
"""
from __future__ import annotations

import json
import struct
import zlib

import numpy as np

ICRAW_MAGIC = b"ICRAW1"
TAG_PROC = 65000
TAG_BLOB0 = 65001
HDR = 32
MAX_BLOCK = 1 << 30          # 单块 ≤ 1 GB（TIFF 的 tag 值偏移是 32 位）
MAX_EMBED = 8 << 30          # 链前数据 > 8 GB 就不内嵌，只写处理记录
PROC_SCHEMA = 1

_CODE = {np.dtype(np.uint8): 1, np.dtype(np.uint16): 2,
         np.dtype(np.uint32): 3, np.dtype(np.float32): 4}
_CODE_R = {v: k for k, v in _CODE.items()}


class RawError(Exception):
    """私有 tag 读不出来（数据块损坏等）。"""


# ------------------------------------------------------------------ 数据块
def pack_block(arr) -> bytes:
    """一个数据块：32 字节头（magic + dtype + 形状 + crc32）+ zlib 载荷。"""
    a = np.ascontiguousarray(arr)
    code = _CODE.get(a.dtype)
    if code is None:
        raise RawError("不支持的数据类型：%s" % a.dtype)
    if a.ndim == 2:                     # (Y, X) → (1, 1, Y, X)
        a = a[None, None]
    elif a.ndim == 3:                   # (C, Y, X) → (1, C, Y, X)
        a = a[None]
    if a.ndim != 4:
        raise RawError("看不懂的维度：%s" % (a.shape,))
    f, c, h, w = a.shape
    raw = a.tobytes()
    head = struct.pack("<6sBBIIIII", ICRAW_MAGIC, code, 0, c, h, w, f, len(raw))
    head += struct.pack("<I", zlib.crc32(raw) & 0xFFFFFFFF)
    return head + zlib.compress(raw, 6)


def unpack_block(blob) -> np.ndarray:
    """还原一个数据块 → (F, C, Y, X)。CRC 不过就抛 RawError。"""
    b = bytes(blob)
    if len(b) < HDR:
        raise RawError("数据块太短")
    magic, code, _rsv, c, h, w, f, nbytes = struct.unpack("<6sBBIIIII", b[:28])
    crc = struct.unpack("<I", b[28:32])[0]
    if magic != ICRAW_MAGIC:
        raise RawError("不是 ICRAW 数据块")
    if code not in _CODE_R:
        raise RawError("未知的 dtype 代码：%d" % code)
    try:
        raw = zlib.decompress(b[HDR:])
    except Exception as exc:                             # noqa: BLE001
        raise RawError("数据块解压失败（%s）" % exc)
    if (zlib.crc32(raw) & 0xFFFFFFFF) != crc or len(raw) != nbytes:
        raise RawError("数据块校验不过（文件可能损坏）")
    return np.frombuffer(raw, dtype=_CODE_R[code]).reshape((f, c, h, w)).copy()


def encode_blocks(arr, limit: int = MAX_BLOCK):
    """按帧切块；一帧就超过 limit 时改按通道切。返回 [blob, …]。"""
    a = np.ascontiguousarray(arr)
    if a.ndim == 3:
        a = a[None]
    blocks = [pack_block(a[i:i + 1]) for i in range(a.shape[0])]
    if len(blocks) == 1 and len(blocks[0]) > limit:
        blocks = [pack_block(a[:, j:j + 1]) for j in range(a.shape[1])]
    return blocks


def unpack_blocks(blobs) -> np.ndarray:
    """把若干块拼回 (F, C, Y, X)。"""
    parts = [unpack_block(b) for b in (blobs or [])]
    if not parts:
        raise RawError("没有数据块")
    if len(parts) == 1:
        return parts[0]
    c0 = parts[0].shape[1]
    axis = 0 if all(p.shape[1] == c0 for p in parts) else 1
    return np.concatenate(parts, axis=axis)


# ------------------------------------------------------------------ 写 / 读
def save_raw_tiff(path: str, data, umpp: float = 0.0, ome: dict = None,
                  proc: dict = None, blobs=(), compression="zlib"):
    """写原始位深 TIFF：**不 rescale、不降位深**，可选 OME-XML 与私有 tag。"""
    import tifffile
    kw = dict(photometric="minisblack", compression=compression)
    if umpp and umpp > 0:
        kw.update(resolution=(1e4 / float(umpp), 1e4 / float(umpp)),
                  resolutionunit="CENTIMETER")
    if ome:
        kw.update(ome=True, metadata=ome)
    extra = []
    if proc is not None:
        blob = json.dumps(proc, ensure_ascii=False).encode("utf-8")
        extra.append((TAG_PROC, "B", len(blob), blob, True))
        for i, b in enumerate(blobs or ()):
            if b:
                extra.append((TAG_BLOB0 + i, "B", len(b), b, True))
    if extra:
        kw.update(extratags=extra)
    tifffile.imwrite(path, np.ascontiguousarray(data), **kw)


def read_private(path: str) -> dict:
    """读出私有 tag。返回 {}（没有）或 {proc:…, blobs:[…]}。

    任何异常都当"没有私有 tag"处理 —— 不能因为一个坏 tag 就打不开图片。
    """
    try:
        import tifffile
        with tifffile.TiffFile(path) as tf:
            if not tf.pages:
                return {}
            tags = tf.pages[0].tags
            out = {}
            if TAG_PROC in tags:
                raw = bytes(tags[TAG_PROC].value)
                try:
                    out["proc"] = json.loads(raw.decode("utf-8"))
                except Exception:                        # noqa: BLE001
                    out["proc"] = {"raw": raw.decode("utf-8", "replace")}
            blobs, i = [], 0
            while (TAG_BLOB0 + i) in tags:
                blobs.append(bytes(tags[TAG_BLOB0 + i].value))
                i += 1
            if blobs:
                out["blobs"] = blobs
            return out
    except Exception:                                    # noqa: BLE001
        return {}


def tag_ids(path: str) -> set:
    """这条 TIFF 里有哪些 tag id（判断有没有处理记录 / 链前数据）。"""
    try:
        import tifffile
        with tifffile.TiffFile(path) as tf:
            if not tf.pages:
                return set()
            return set(int(k) for k in tf.pages[0].tags.keys())
    except Exception:                                    # noqa: BLE001
        return set()


def has_proc(path: str) -> bool:
    return TAG_PROC in tag_ids(path)


def has_embed(path: str) -> bool:
    return TAG_BLOB0 in tag_ids(path)


def restore_planes(path: str):
    """取链前像素 → (F, C, Y, X)；没有内嵌或读坏了就返回 None。"""
    info = read_private(path)
    if not info.get("blobs"):
        return None
    try:
        return unpack_blocks(info["blobs"])
    except RawError:
        return None


def process_line(proc: dict) -> str:
    """处理记录 → 人能读的一句话（写进 OME 的 Description，规格书 3.11.7）。"""
    if not proc:
        return ""
    steps = proc.get("steps") or []
    if not steps:
        return ""
    bits = []
    for s in steps:
        name = s.get("kind") or "step"
        flag = "" if s.get("enabled", True) else "(关闭)"
        bits.append("%s%s" % (name, flag))
    return "Processed by Image capture: " + ", ".join(bits)
