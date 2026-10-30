# -*- coding: utf-8 -*-
"""工程文件（.icproj）：把整个工作区落盘，以及撤销栈。

规格书 P0-1。为什么要有这个文件：裁剪框位置是主观判断，关掉软件就丢，
同一批数据两次出的图不一致 —— 这是方法学硬伤，不只是"要重做一遍"。

设计原则（对应规格书 3.4.3 / 3.4.6）：
  · 用**显式白名单**序列化 ImageItem，不用 asdict()。理由不是"会崩"
    （实测 asdict 没问题），而是字段集合必须可控、迁移点必须明确。
  · 白名单一次写全（含 P0/P1 所有字段，未实现的留默认值），
    以后上 P1 项不用再改 schema。
  · 白名单之外的未知字段原样收进 item._extra 再写回，防止"新版本打开过、
    旧版本再打开"静默丢字段。
  · 多序列的 path 带 "#2" 后缀，原样存，不清洗（清洗了 series 就对不上）。
"""
from __future__ import annotations

import json
import os
import time

from core.model import Channel, Group, ImageItem, ProcessStep, Settings
from core.roi import Roi

APP_TAG = "ImageCapture"
SCHEMA = 1

# ImageItem 的白名单（规格书 3.4.3，一次定全）
ITEM_FIELDS = (
    "path", "name", "group", "umpp", "calib", "width", "height",
    "frames", "bits", "series", "note",
    "group_manual", "group_key",
    # P0-3
    "t_count", "z_count", "z_step_um", "t_interval_s", "z_declared_manual",
    "z_meta_declared",
    "t_meta_declared",
    # 2.2 处理链
    "process",
    # P0-4
    "range_mode", "ref_frame", "range_p_lo", "range_p_hi",
    # P1-5
    "proj_mode", "proj_from", "proj_to", "proj_range_mode", "proj_n", "proj_center",
    # P1-6
    "rois",
    # P1-9
    "stitch",
)

CHANNEL_FIELDS = ("index", "name", "light", "ex", "em", "color",
                  "black", "white", "visible", "role", "vmax")

GROUP_FIELDS = ("gid", "key", "title", "title_manual", "sync", "keep_empty",
                "out_dir", "box", "boxes", "bar_anchor", "bar_text_anchor")

# 只在磁盘上用于重定位，不算 item 自己的字段，也不进 _extra
RESOLVE_FIELDS = ("rel", "rel_base")

# 运行时字段（本来就不是 dataclass 字段，白名单天然排除；写下来当文档）
RUNTIME_FIELDS = ("_cache", "_preview", "_ranges_ready", "_cache_key",
                  "detect", "missing")


class ProjectError(Exception):
    """工程文件读不了（不是 JSON / 不是本软件的工程 / 版本太新）。"""


def _split_series(path):
    """'x.lif#2' → ('x.lif', '#2')。多序列条目靠这个找回真文件。"""
    p = path or ""
    i = p.rfind("#")
    if i > 0 and p[i + 1:].isdigit():
        return p[:i], p[i:]
    return p, ""


def _jsonable(v):
    """tuple / numpy 标量统一成 JSON 能写的形状。"""
    if isinstance(v, tuple):
        return [_jsonable(x) for x in v]
    if isinstance(v, list):
        return [_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    try:
        import numpy as np
        if isinstance(v, np.generic):
            return v.item()
    except Exception:                                    # noqa: BLE001
        pass
    return str(v)


# ------------------------------------------------------------------ 通道 / 图 / 组
def channel_to_dict(ch: Channel) -> dict:
    return {k: _jsonable(getattr(ch, k, None)) for k in CHANNEL_FIELDS}


def channel_from_dict(d: dict) -> Channel:
    kw = {k: d[k] for k in CHANNEL_FIELDS if k in d}
    if kw.get("color") is not None:
        kw["color"] = tuple(kw["color"])
    return Channel(**kw)


def proc_to_list(proc) -> list:
    """处理链 → 纯 dict 列表（list[ProcessStep] 不能直接 json）。"""
    out = []
    for s in (proc or []):
        if isinstance(s, ProcessStep):
            out.append(dict(kind=s.kind, params=_jsonable(s.params or {}),
                            enabled=bool(s.enabled)))
        elif isinstance(s, dict) and s.get("kind"):
            out.append(dict(kind=str(s.get("kind")), params=_jsonable(s.get("params") or {}),
                            enabled=bool(s.get("enabled", True))))
    return out


def rois_to_list(rois) -> list:
    """ROI → 纯 dict 列表（Roi 是 dataclass，不能直接 dump）。"""
    out = []
    for r in (rois or []):
        if isinstance(r, Roi):
            out.append(r.to_dict())
        elif isinstance(r, dict) and r.get("points"):
            out.append(dict(r))
    return out


def rois_from_list(v) -> list:
    """纯 dict 列表 → list[Roi]（认不出的条目直接丢，别让工程打不开）。"""
    out = []
    for r in (v or []):
        if isinstance(r, dict) and r.get("points"):
            try:
                out.append(Roi.from_dict(r))
            except Exception:                        # noqa: BLE001
                continue
    return out


def proc_from_list(v) -> list:
    """纯 dict 列表 → list[ProcessStep]（认不出的条目直接丢，别让工程打不开）。"""
    out = []
    for s in (v or []):
        if isinstance(s, dict) and s.get("kind"):
            out.append(ProcessStep(kind=str(s["kind"]),
                                   params=dict(s.get("params") or {}),
                                   enabled=bool(s.get("enabled", True))))
    return out


def item_to_dict(it: ImageItem, base: str = "") -> dict:
    """白名单序列化。base 非空时顺带记一份相对路径（拷到别的目录还能打开）。"""
    d = {}
    for k in ITEM_FIELDS:
        d[k] = _jsonable(getattr(it, k, None))
    d["process"] = proc_to_list(getattr(it, "process", None))
    d["rois"] = rois_to_list(getattr(it, "rois", None))
    d["channels"] = [channel_to_dict(c) for c in (it.channels or [])]
    extra = getattr(it, "_extra", None)
    if isinstance(extra, dict):
        for k, v in extra.items():
            if k not in d and k not in RESOLVE_FIELDS:
                d[k] = _jsonable(v)
    real, _sfx = _split_series(it.path)
    if base and real:
        _put_rel(d, real, base)
    return d


def _put_rel(d: dict, real: str, base: str):
    """同盘才写相对路径（跨盘 relpath 会抛异常，也没意义）。"""
    try:
        a, b = os.path.abspath(real), os.path.abspath(base)
        if os.path.splitdrive(a)[0].lower() != os.path.splitdrive(b)[0].lower():
            return
        d["rel"] = os.path.relpath(a, b).replace("\\", "/")
        d["rel_base"] = base.replace("\\", "/")
    except Exception:                                    # noqa: BLE001
        pass


def item_from_dict(d: dict, base_candidates=()) -> ImageItem:
    """从白名单 dict 还原 ImageItem；顺带做路径重定位。"""
    kw = {}
    for k in ITEM_FIELDS:
        if k in d and d[k] is not None:
            kw[k] = d[k]
    kw["channels"] = [channel_from_dict(c) for c in (d.get("channels") or [])]
    kw["process"] = proc_from_list(d.get("process"))
    kw["rois"] = rois_from_list(d.get("rois"))
    it = ImageItem(**kw)
    # 白名单之外的原样留着，保存时写回（版本迁移期很重要）
    extra = {k: v for k, v in d.items()
             if k not in ITEM_FIELDS and k not in RESOLVE_FIELDS
             and k != "channels"}
    if extra:
        it._extra = extra
    it.path = resolve_path(d, base_candidates)
    it.missing = not os.path.exists(it.file_path)
    return it


def resolve_path(d: dict, base_candidates=()) -> str:
    """先认绝对路径，再拿 rel 试几个可能的根目录，最后原样返回（留作灰色占位）。"""
    stored = d.get("path") or ""
    real, sfx = _split_series(stored)
    series = d.get("series") or 0
    if not sfx and series:
        sfx = "#%d" % (series + 1)
    if real and os.path.exists(real):
        return stored
    rel = (d.get("rel") or "").replace("/", os.sep)
    roots = [r for r in (tuple(base_candidates) + (d.get("rel_base"),)) if r]
    if rel:
        for root in roots:
            cand = os.path.normpath(os.path.join(root, rel))
            if os.path.exists(cand):
                return cand + sfx
    return stored


def group_to_dict(g: Group) -> dict:
    return {k: _jsonable(getattr(g, k, None)) for k in GROUP_FIELDS}


def group_from_dict(d: dict) -> Group:
    kw = {k: d[k] for k in GROUP_FIELDS if k in d}
    for k in ("bar_anchor", "bar_text_anchor"):
        if kw.get(k) is not None:
            kw[k] = tuple(kw[k])
    key = kw.pop("key", "") or ""
    if not key:                                  # 老工程没写 key：补一个
        key = Group.new_key()
    else:
        Group.reserve_key(key)
    kw["key"] = key
    kw.setdefault("gid", "")
    kw.setdefault("title", "")
    return Group(**kw)


# ------------------------------------------------------------------ 工程文件
def build_doc(settings: Settings, groups, items, view=None) -> dict:
    return dict(app=APP_TAG, schema=SCHEMA,
                saved_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                settings=settings.to_dict(),
                groups=[group_to_dict(g) for g in groups],
                items=[item_to_dict(it) for it in items],
                view=dict(view or {}))


def save_project(path: str, doc: dict, base: str = "") -> str:
    """写工程文件：先写 .tmp 再 os.replace，断电不会留半个坏文件。"""
    out = dict(doc)
    items = []
    for it in doc.get("items") or []:
        d = dict(it)
        real, _sfx = _split_series(it.get("path") or "")
        if base and real:
            _put_rel(d, real, base)
        items.append(d)
    out["items"] = items
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return path


def load_project(path: str) -> dict:
    """读工程文件并做基本校验；坏了抛 ProjectError（带人话原因）。"""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except FileNotFoundError:
        raise ProjectError("找不到工程文件：%s" % path)
    except Exception as exc:                             # noqa: BLE001
        raise ProjectError("文件损坏或不是工程文件（%s）" % exc)
    if not isinstance(doc, dict) or doc.get("app") != APP_TAG:
        raise ProjectError("这个文件不是 Image capture 工程文件")
    schema = int(doc.get("schema") or 0)
    if schema > SCHEMA:
        raise ProjectError("工程由更新版本创建（schema %d > 本程序支持的 %d），"
                           "请升级软件后再打开" % (schema, SCHEMA))
    if schema < SCHEMA:
        doc = migrate(doc)
    return doc


def migrate(doc: dict) -> dict:
    """旧 schema → 新 schema。现在只有 1，留着钩子；以后每加一版写一段。"""
    out = dict(doc)
    out["schema"] = SCHEMA
    return out


def settings_from_dict(d: dict, base: Settings = None) -> Settings:
    """settings 段缺字段就用默认值补齐，不报错（规格书 3.5）。"""
    st = base or Settings()
    for k, v in (d or {}).items():
        if hasattr(st, k):
            try:
                setattr(st, k, v)
            except Exception:                            # noqa: BLE001
                pass
    return st


def load_into(doc: dict, base_candidates=()):
    """把 doc 还原成 (settings, groups, items, orphan, view)。

    items 先建好，再按 group / group_key 把图挂回组；不重新探测元数据（会卡几十秒）。
    """
    st = settings_from_dict(doc.get("settings"))
    items = [item_from_dict(d, base_candidates) for d in (doc.get("items") or [])]
    groups = []
    seen_keys = set()
    for gd in (doc.get("groups") or []):
        # 同一个工程里 key 撞车（手改过 / 合并过）→ 只给重复的那个重新发号，
        # 别的 key 一律原样保留：it.group_key 指着它，换了图就串组（规格书 3.4.6 坑 2）
        k = gd.get("key") or ""
        if k and k in seen_keys:
            gd = dict(gd, key="")
        seen_keys.add(gd.get("key") or "")
        g = group_from_dict(gd)
        seen_keys.add(g.key)
        g.images = [x for x in items
                    if x.group == g.gid or (getattr(x, "group_key", "")
                                            and x.group_key == g.key)]
        groups.append(g)
    orphan = [x for x in items if not any(x in g.images for g in groups)]
    return st, groups, items, orphan, (doc.get("view") or {})


# ------------------------------------------------------------------ 撤销栈
class UndoStack:
    """快照式撤销（规格书 3.4.7）。

    · 快照只含 items/groups 的**纯数据**（剥掉 _cache / _preview），一次几百 KB；
    · 同时限步数（50）与体积（≤200 MB）—— 只限步数在超大工程上会吃光内存（E12）；
    · 只在"提交"时入栈，不在拖动过程中入栈。
    """

    def __init__(self, max_steps: int = 50, max_bytes: int = 200 * 1024 * 1024):
        self.max_steps = int(max_steps)
        self.max_bytes = int(max_bytes)
        self._undo = []              # [(name, doc)]
        self._redo = []
        self.last_name = ""
        self.last_time = 0.0

    def can_undo(self):
        return bool(self._undo)

    def can_redo(self):
        return bool(self._redo)

    def names(self):
        up = self._undo[-1][0] if self._undo else ""
        re_ = self._redo[-1][0] if self._redo else ""
        return (up, re_)

    def depth(self):
        return (len(self._undo), len(self._redo))

    def sizes(self):
        return (_weight(self._undo), _weight(self._redo))

    def push(self, name: str, doc: dict, coalesce: float = 0.0):
        """入栈"动作发生前"的快照。coalesce 窗口内同名动作只记第一次（拖滑块用）。"""
        now = time.monotonic()
        if coalesce and self._undo and self.last_name == name:
            if now - self.last_time < coalesce:
                self.last_time = now
                return False
        self._undo.append((name, doc))
        self._redo.clear()
        self.last_name = name
        self.last_time = now
        self._trim()
        return True

    def undo(self, current: dict):
        if not self._undo:
            return None
        name, doc = self._undo.pop()
        self._redo.append((name, current))
        self.last_name = ""
        return name, doc

    def redo(self, current: dict):
        if not self._redo:
            return None
        name, doc = self._redo.pop()
        self._undo.append((name, current))
        self.last_name = ""
        return name, doc

    def clear(self):
        self._undo.clear()
        self._redo.clear()
        self.last_name = ""
        self.last_time = 0.0

    def _trim(self):
        while len(self._undo) > self.max_steps:
            self._undo.pop(0)
        while self._undo and _weight(self._undo) > self.max_bytes:
            self._undo.pop(0)


def _weight(stack) -> int:
    """粗略算快照占的字节数（只算一次 JSON，够用于限额判断）。"""
    total = 0
    for _n, doc in stack:
        try:
            total += len(json.dumps(doc, ensure_ascii=False))
        except Exception:                                # noqa: BLE001
            total += 4096
    return total
