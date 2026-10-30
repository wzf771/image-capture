# -*- coding: utf-8 -*-
"""读图：原生读 Olympus OIB/OIF，也读 TIFF / PNG / JPG / BMP。

统一把像素规整成 (T, C, Y, X)：T 时间帧、C 通道、Y/X 行列。
"""
from __future__ import annotations

import hashlib
import os
import re

import numpy as np
from PIL import Image

# 科研大图动辄上亿像素（拼图 / 共聚焦扫描），PIL 默认的"解压炸弹"上限
# （1.79 亿像素）会把它们当成可疑文件拒掉，这里放开。
Image.MAX_IMAGE_PIXELS = None

import paths
from core.model import (BLUE, CYAN, GRAY, GREEN, MAGENTA, RED, YELLOW, Channel,
                        ImageItem, color_for_dye, looks_brightfield)

SUPPORTED = (".oib", ".oif", ".tif", ".tiff", ".png", ".jpg", ".jpeg", ".bmp")
OIB_EXT = (".oib", ".oif")
CZI_EXT = (".czi",)
LIF_EXT = (".lif", ".lof", ".xlif", ".xlef", ".xlcf")
SUPPORTED = SUPPORTED + CZI_EXT + LIF_EXT


def is_supported(path):
    return os.path.splitext(path)[1].lower() in SUPPORTED


def scan_paths(items, recursive=True):
    """把一个或多个文件/目录摊平成文件列表。"""
    found, seen = [], set()

    def add(p):
        if p not in seen and is_supported(p):
            seen.add(p)
            found.append(p)

    for it in items:
        if os.path.isfile(it):
            add(it)
        elif os.path.isdir(it):
            if recursive:
                for root, _dirs, files in os.walk(it):
                    for name in sorted(files):
                        add(os.path.join(root, name))
            else:
                for name in sorted(os.listdir(it)):
                    add(os.path.join(it, name))
    return found


# ---------------------------------------------------------------- 元数据探测

def to_tczyx(arr, axes):
    """按元数据声明的轴顺序把数组摆成 (T, C, Z, Y, X)；看不出来就返回 None。

    规格书 3.18.2 的硬规则：**先按元数据显式重排**，再交给 `_canonical`。
    老代码用 `shape[:2] == (C, T)`、`shape[0] > shape[1]` 这类启发式判断，
    OIB 的 Z 栈（axes="CZYX"）会被读成"3 个通道 × N 帧"，Z 层当成帧、通道数错乱。
    """
    a = np.asarray(arr)
    ax = "".join(axes or "").upper()
    if a.ndim < 2 or len(ax) != a.ndim or any(ch not in "TCZYX" for ch in ax):
        return None                                   # 元数据缺失/带 S 等轴 → 交回兜底
    present = [ch for ch in "TCZYX" if ch in ax]
    perm = [ax.index(ch) for ch in present]
    x = np.transpose(a, perm) if perm != list(range(a.ndim)) else a
    shape = [(int(x.shape[present.index(ch)]) if ch in present else 1) for ch in "TCZYX"]
    return x.reshape(shape)


def infer_axes(arr, decl_shape, axes):
    """推断 `asarray()` 返回的数组**实际**是哪个轴在前。

    为什么需要这个：oiffile 对某些文件并不按 `axes` 的顺序返回数组 ——
    实测 FRAPR1.oib 声明 `axes='TCYX'`、`f.shape=(50,2,1024,1024)`，
    但 `asarray()` 给的是 `(2,50,1024,1024)`（通道在前）。
    盲目信 `axes` 会把 50 个时间点读成 50 个通道。

    做法：拿每根轴声明的**尺寸**去匹配数组的维度（尺寸不同就能唯一定位）。
    返回推断出来的轴顺序字符串（如 "CTYX"），推不出来返回 None。
    """
    a = [int(v) for v in np.shape(arr)]
    decl = [int(v) for v in (decl_shape or ())]
    letters = list(axes or "")
    if not letters or len(letters) != len(a) or len(decl) != len(letters):
        return None
    used, order = [False] * len(letters), []
    for dim in a:
        cand = [i for i in range(len(letters))
                if not used[i] and decl[i] == dim]
        if not cand:
            return None
        i = cand[0]                           # 尺寸撞车（如 T=C=2）时按声明顺序
        used[i] = True
        order.append(letters[i])
    return "".join(order)


def set_dims(item, t_count=1, z_count=1, declared=False, t_declared=None):
    """写 t/z 计数，并让 frames = t × z（规格书 3.18.1 的关键约定）。

    `declared` / `t_declared` = 这次是不是"元数据明确说了"（决定界面上要不要给
    "多帧到底是 Z 还是时间"的声明胶囊；说不出才问，说得清就别打扰用户）。
    """
    item.t_count = max(1, int(t_count or 1))
    item.z_count = max(1, int(z_count or 1))
    item.frames = item.t_count * item.z_count
    item.z_meta_declared = bool(declared)      # 每次都重写，别留上一次的结论
    if t_declared is not None:
        item.t_meta_declared = bool(t_declared)
    return item.frames


def sane_z_step(um: float) -> float:
    """Z 步进的合理范围过滤：0.05~50 µm 之外一律当"未知"。

    为什么不让它乱猜：各家存 Z 的单位不一样（OIB 是 nm 级的整数、CZI 是米、
    OME 是 µm），猜错会让 3D 的物理比例整个歪掉。宁可为 0（界面显示"步进未知"）。
    """
    try:
        v = float(um)
    except Exception:                                 # noqa: BLE001
        return 0.0
    return v if 0.05 <= v <= 50.0 else 0.0


def sane_interval_s(sec: float) -> float:
    """时间间隔的合理范围过滤：0.001 s ~ 24 h 之外当"未知"。"""
    try:
        v = float(sec)
    except Exception:                                 # noqa: BLE001
        return 0.0
    return v if 0.001 <= v <= 86400.0 else 0.0


def _oib_axis_step_um(mf, code, count):
    """OIB：从 `Axis N Parameters Common` 里找某根轴的 Start/EndPosition → 步进（µm）。

    单位要靠数值量级猜（Olympus 这里 Z 的位置是 nm 级整数、T 常见是 ms），
    所以两边都试一遍，再用 sane_z_step / sane_interval_s 过滤。
    """
    if count is None or int(count) < 2:
        return None
    for i in range(12):
        p = mf.get("Axis %d Parameters Common" % i)
        if not p or str(p.get("AxisCode", "")).upper() != code:
            continue
        try:
            a, b = float(p.get("StartPosition")), float(p.get("EndPosition"))
        except Exception:                             # noqa: BLE001
            return None
        return abs(b - a) / (int(count) - 1)
    return None

def _probe_oib(path, item):
    import oiffile
    with oiffile.OifFile(path) as f:
        mf = f.mainfile
        ref = mf.get("Reference Image Parameter", {})
        item.width = int(ref.get("ImageWidth") or 0)
        item.height = int(ref.get("ImageHeight") or 0)
        item.bits = int(ref.get("ValidBitCounts") or 12)
        um = ref.get("WidthConvertValue")
        if um:
            item.umpp = float(um)
            item.calib = "OIB 内嵌标定"
        axes = f.axes or ""
        shape = tuple(f.shape)
        t_n = int(shape[axes.index("T")]) if "T" in axes else 1
        z_n = int(shape[axes.index("Z")]) if "Z" in axes else 1
        set_dims(item, t_n, z_n, declared=("Z" in axes), t_declared=("T" in axes))
        # Z 步进：Axis N Parameters Common（单位要靠量级猜，见 _oib_axis_step_um）
        raw = _oib_axis_step_um(mf, "Z", z_n)
        if raw is not None:
            for k in (1e-3, 1.0, 1e6):        # 依次按 nm / µm / m 试
                v = sane_z_step(raw * k)
                if v:
                    item.z_step_um = v
                    break
        raw_t = _oib_axis_step_um(mf, "T", t_n)
        if raw_t is not None:
            for k in (1e-3, 1.0):             # T 常见是 ms；也试秒
                v = sane_interval_s(raw_t * k)
                if v:
                    item.t_interval_s = v
                    break
        chans = []
        for i in range(1, 7):
            ch = mf.get("Channel %d Parameters" % i)
            if not ch:
                continue
            chans.append(dict(name=ch.get("CH Name") or ("CH%d" % i),
                              light=ch.get("LightType") or "",
                              ex=int(ch.get("ExcitationWavelength") or 0),
                              em=int(ch.get("EmissionWavelength") or 0)))
        item.channels = _assign_roles(chans, item.bits)
        acq = mf.get("Acquisition Parameters Common", {})
        date = (mf.get("File Info", {}) or {}).get("ImageCaputreDate")
        item.note = "%s · 变倍 %s" % (acq.get("Acquisition Device", "Olympus"),
                                      acq.get("ZoomValue", "1.0"))
        if item.z_step_um > 0 or item.t_interval_s > 0:
            bits = []
            if item.z_step_um > 0:
                bits.append("Z 步进 %.3g µm" % item.z_step_um)
            if item.t_interval_s > 0:
                bits.append("间隔 %.3g s" % item.t_interval_s)
            item.note += " · " + " · ".join(bits)
        if date:
            item.note += " · " + str(date)
    return item


def _assign_roles(chans, bits=12, base_gray=True):
    """配色：明场/透射光→灰底，荧光通道按染料给颜色（YFP 黄、GFP 绿、mCherry 红…）。

    认明场看名字和照明类型（蔡司的通道常叫 "T PMT"，徕卡叫 BF/TL，奥林巴斯叫 TD1）。
    base_gray=True 时，若整张图没有明场通道，就把第一个通道当灰底（OIB、LIF 常见）；
    CZI 纯荧光图用 base_gray=False，直接彩色叠加，背景才是黑的。

    **单通道例外**（用户实测反馈）：只有一路、且它明确是荧光（照明类型写了
    Fluorescence / 名字或染料能认出 GFP 之类 / 记了激发发射波长）时，不能再把它
    改成灰底 —— 以前单通道 GFP 图会显示成灰度，很不合理。
    """
    maxv = float(2 ** bits - 1) if bits < 16 else 65535.0
    out, fluor, used = [], 0, []
    fallback = [GREEN, RED, MAGENTA, CYAN, BLUE, YELLOW]
    for i, c in enumerate(chans):
        name = c.get("name", "") or ""
        light = c.get("light", "") or ""
        dye = c.get("dye", "") or ""
        if looks_brightfield(name, light, dye):
            role, color = "gray", GRAY
        else:
            fluor += 1
            color = color_for_dye(name) or color_for_dye(dye)
            if color is None:
                # **只有"认不出染料"才按顺序补备用色**（尽量挑还没用过的）。
                # 历史 bug（用户实测反馈）：老写法是 `color is None or color in used`
                # ——两路同名染料（蔡司 Processing 文件里的 FITC-T1 / EGFP-T2 本来就是
                # 同一路绿色）会因为"绿的已用过"被改成备用色，第二路凭空变红，
                # 合并成一层后用户看到的就是红图 / 黄图。认出来的染料可以同色。
                for k in range(len(fallback)):
                    cand = fallback[(fluor - 1 + k) % len(fallback)]
                    if cand not in used:
                        color = cand
                        break
                else:
                    color = fallback[(fluor - 1) % len(fallback)]
            role = "green"                        # 非灰底 = 叠加层，颜色看 color
            used.append(color)
        out.append(Channel(index=i, name=name or ("CH%d" % (i + 1)), light=light,
                           ex=c.get("ex", 0), em=c.get("em", 0),
                           color=color, black=0.0, white=maxv, role=role))
    if out and all(ch.role != "gray" for ch in out) and base_gray:
        # 只有"第一路不像荧光"时才把它当灰底：
        # 单通道 GFP（CHS1 + LightType=Fluorescence）以前会被无条件改成灰度；
        # 三通道全荧光（LiveStop.oib）同理，第一路也不该变成灰的。
        # 反过来，第一路没有任何荧光线索（说不出名字、没有照明类型/波长）时，
        # 仍然按老习惯当灰底 —— 这条比原来"无条件"更保守，不会把明场判成彩色。
        if not _is_fluor_hint(chans[0]):
            out[0].role, out[0].color = "gray", GRAY
    return out


def _is_fluor_hint(c: dict) -> bool:
    """这一路有"它是荧光"的证据吗：照明类型 / 染料名 / 激发发射波长。

    奥林巴斯 OIB 的单通道荧光常写作 CHS1 + LightType=Fluorescence（名字里没有 GFP），
    所以照明类型是这里最可靠的线索。
    """
    light = str(c.get("light", "") or "").lower()
    if "fluor" in light or "laser" in light:
        return True
    if color_for_dye(c.get("name") or "") or color_for_dye(c.get("dye") or ""):
        return True
    try:
        return bool(float(c.get("ex") or 0) > 0 or float(c.get("em") or 0) > 0)
    except Exception:                                # noqa: BLE001
        return False


def _czi_channel_info(xml, nch=None):
    """从 CZI 的 ImageDocument 里读出通道名/照明类型/染料/颜色。

    返回 (名字列表, XML 声明的通道数)。

    **只认"真的带通道定义的那个 Image"**（用户实测反馈）：Zeiss 的 Processing
    文件里常有**多个 `<Image>` 元素**（预览壳 + 数据体，或 processed + raw），
    以前一口气扫整个文档，会把别的 Image、甚至 raw 变体（名字带 `#`）一起算进来 ——
    结果 2 通道的文件显示出 5 路，名字长成 "EGFP / EGFP# / CH5" 这种。
    现在按 Pixels 的 SizeC 挑最大的那个 Image，名字里的 `#` 也去掉。
    """
    import xml.etree.ElementTree as ET
    info, size_c = [], 0
    try:
        root = ET.fromstring(xml)
        best = None
        for im in root.iter("Image"):
            chans = [ch for ch in im.iter("Channel") if ch.get("Name")]
            if not chans:
                continue
            px = next(im.iter("Pixels"), None)
            c_here = int(px.get("SizeC") or 0) if px is not None else 0
            if best is None or c_here > best[0]:
                best = (c_here, chans)
        if best is None:
            return info, size_c
        size_c, chans = best
        picked = [e for e in chans if e.find("IlluminationType") is not None] or chans
        plain = [e for e in picked if "#" not in (e.get("Name") or "")]
        if plain:                                # 有正常名字就别用 raw(#) 变体
            picked = plain
        if not picked:
            return info, size_c
        for e in picked[:max(0, size_c) or None]:
            info.append(dict(name=re.sub(r"#+$", "", e.get("Name") or ""),
                             light=(e.findtext("IlluminationType") or "").strip(),
                             dye=(e.findtext("DyeName") or "").strip(),
                             color=(e.findtext("Color") or "").strip()))
    except Exception:                            # noqa: BLE001
        return info, size_c
    return (info[:nch] if nch else info), (size_c or len(info))


def _raster_layout(im):
    """判断一张图片文件是什么：gray（真灰度）/ rgb（彩色）。

    **图片格式一律"原样进、原样出"**（用户明确要求）：
    BMP / PNG / JPG / 普通 TIFF 里本来就是 RGB 像素，软件不该再给它套颜色。
    老写法还有一档 `tint`（只测到一个通道有能量时）——它会把这种文件当成
    "单色通道"，只取能量最强的那一层、再按绿色重新上色，于是
    一张偏绿的 BMP 进来会被整张染成绿的（实测最大差 208）。
    所以现在只分 gray / rgb 两档；`tint` 那档保留常量名只为兼容旧数据。
    """
    # 先缩到 96×96 再转 RGB：以前是对整张图做 convert("RGB")，
    # 一张 16000×16000 的图光是这一步就要开 768 MB，慢得离谱。
    try:
        small = im.resize((96, 96))
    except Exception:                            # noqa: BLE001
        small = im.copy()
    if small.mode != "RGB":
        small = small.convert("RGB")
    a = np.asarray(small).astype(np.float32)
    strength = []
    for c in range(3):
        ch = a[..., c]
        strength.append(float(ch.mean() + 2.0 * ch.std()))
    hi = max(strength)
    active = [c for c in range(3) if strength[c] > max(4.0, hi * 0.35)]
    if len(active) >= 1:
        return "rgb", active          # 有颜色信息就原样当彩色图（含"只测到一路"的情况）
    return "gray", [0]


# ---------------------------------------------------------------- 蔡司 CZI

def _probe_czi(path, item):
    """蔡司 CZI：像素、通道、帧数、标定（Scaling 里的 Distance，单位是米）。"""
    import czifile
    with czifile.CziFile(path) as czi:
        subs = list(czi.subblocks())
        if not subs:
            raise ValueError("CZI 里没有图像数据")
        de = subs[0].directory_entry
        size = dict(zip(tuple(getattr(de, "dims", ()) or ()), tuple(de.shape)))
        item.width = int(size.get("X") or 0)
        item.height = int(size.get("Y") or 0)
        item.bits = int(np.dtype(de.dtype).itemsize * 8)
        c_dim = max(1, int(size.get("C", 1) or 1))
        t_dim = int(size.get("T", 1) or 1)
        z_dim = int(size.get("Z", 1) or 1)
        _dims = tuple(getattr(de, "dims", ()) or ())
        set_dims(item, t_dim, z_dim, declared=("Z" in _dims), t_declared=("T" in _dims))
        # Airyscan 这类文件是"一个通道一个子块"，这时通道数要看子块数
        nch = c_dim
        planes = [s for s in subs
                  if not getattr(s.directory_entry, "is_pyramid", False)]
        if c_dim == 1 and t_dim == 1 and z_dim == 1 and 1 < len(planes) <= 8:
            nch = len(planes)
        xml = czi.metadata()
    m = re.search(r'<Distance Id="X">\s*<Value>([0-9.eE+-]+)</Value>', xml)
    if m:
        um = float(m.group(1)) * 1e6          # CZI 里存的是米
        if um > 0:
            item.umpp = um
            item.calib = "CZI 内嵌标定"
    mz = re.search(r'<Distance Id="Z">\s*<Value>([0-9.eE+-]+)</Value>', xml)
    if mz:
        try:
            item.z_step_um = sane_z_step(float(mz.group(1)) * 1e6)   # 米 → µm
        except Exception:                     # noqa: BLE001
            pass
    mt = re.search(r'<Distance Id="T">\s*<Value>([0-9.eE+-]+)</Value>', xml)
    if mt:
        try:
            item.t_interval_s = sane_interval_s(float(mt.group(1)))  # CZI 的 T 是秒
        except Exception:                     # noqa: BLE001
            pass
    infos, xml_c = _czi_channel_info(xml, nch)
    # **XML 说的算**：Zeiss 的 Processing 文件里子块数常常不等于通道数
    # （raw + processed 各一份、或者多 Scene），拿子块数当通道数会凭空多出几路
    if xml_c > 0:
        nch = int(xml_c)
    if nch <= 0:
        nch = 1
    chans = [dict(name=(infos[i].get("name") if i < len(infos) else "") or ("CH%d" % (i + 1)),
                  light=(infos[i].get("light") if i < len(infos) else ""),
                  dye=(infos[i].get("dye") if i < len(infos) else ""),
                  ex=0, em=0) for i in range(nch)]
    item.channels = _assign_roles(chans, item.bits, base_gray=False)
    obj = re.search(r"<ObjectiveName>([^<]*)</ObjectiveName>", xml)
    cam = re.search(r"<CameraName>([^<]*)</CameraName>", xml)
    item.note = "Zeiss CZI"
    if obj:
        item.note += " · " + obj.group(1)
    if cam:
        item.note += " · " + cam.group(1)
    return item


def _load_czi(item):
    import czifile
    with czifile.CziFile(item.path) as czi:
        arr = np.asarray(czi.asarray())
        subs = list(czi.subblocks())
        de = subs[0].directory_entry
        size = dict(zip(tuple(getattr(de, "dims", ()) or ()), tuple(de.shape)))
    c_dim = int(size.get("C", 1) or 1)
    t_dim = int(size.get("T", 1) or 1)
    z_dim = int(size.get("Z", 1) or 1)
    planes = [s for s in subs if not getattr(s.directory_entry, "is_pyramid", False)]
    if c_dim == 1 and t_dim == 1 and z_dim == 1 and 1 < len(planes) <= 8:
        c_dim = len(planes)
    arr5 = to_tczyx(arr, "".join(tuple(getattr(de, "dims", ()) or ())))
    # 元数据自洽才走显式重排；对不上（比如 Airyscan 一个通道一个子块）走老兜底
    if arr5 is not None and arr5.shape[1] == c_dim and arr5.shape[0] * arr5.shape[2] == t_dim * z_dim:
        return _canonical(arr5, c_dim, t_dim, z_dim)
    return _canonical(arr, c_dim, t_dim, z_dim)


# ---------------------------------------------------------------- 徕卡 LIF

def _lif_pick(ims):
    """LIF 里可能有多个序列，取像素最多的那一张。"""
    def area(im):
        sizes = getattr(im, "sizes", {}) or {}
        return int(sizes.get("Y", 0) or 0) * int(sizes.get("X", 0) or 0)
    return max(ims, key=area)


def _probe_lif(path, item, index=None):
    """徕卡 LIF/LOF/XLIF 等：像素、通道、帧数、标定（坐标值单位是米）。"""
    import liffile
    with liffile.LifFile(path) as f:
        ims = list(iter(f.images))
        if not ims:
            raise ValueError("LIF 里没有图像")
        if index is None:
            im = _lif_pick(ims)
        else:
            index = max(0, min(int(index), len(ims) - 1))
            im = ims[index]
            item.series = index
        sizes = dict(getattr(im, "sizes", {}) or {})
        item.width = int(sizes.get("X") or 0)
        item.height = int(sizes.get("Y") or 0)
        t_n = int(sizes.get("T", 1) or 1)
        z_n = int(sizes.get("Z", 1) or 1)
        set_dims(item, t_n, z_n, declared=("Z" in sizes), t_declared=("T" in sizes))
        try:                                  # Z 步进：坐标差分（单位米）
            co = getattr(im, "coords", None) or {}
            arrz = co.get("Z")
            if arrz is not None and len(arrz) > 1:
                item.z_step_um = sane_z_step(float(arrz[1] - arrz[0]) * 1e6)
            arrt = co.get("T")
            if arrt is not None and len(arrt) > 1:
                item.t_interval_s = sane_interval_s(float(arrt[1] - arrt[0]))
        except Exception:                     # noqa: BLE001
            pass
        nch = max(1, int(sizes.get("C", 1) or 1))
        samples = 3 if int(sizes.get("S", 1) or 1) >= 3 else 1
        item.bits = 8 if np.dtype(getattr(im, "dtype", np.uint8)).itemsize == 1 else 16
        um = 0.0
        try:
            co = getattr(im, "coords", None) or {}
            for key in ("Y", "X"):
                arr = co.get(key)
                if arr is not None and len(arr) > 1:
                    step = float(arr[1] - arr[0])
                    if step > 0:
                        um = step * 1e6
                        break
        except Exception:                      # noqa: BLE001
            um = 0.0
        if um <= 0:
            xml = f.xml_header()
            m = re.search(r'<DimensionDescription DimID="1"[^>]*NumberOfElements="(\d+)"'
                          r'[^>]*Length="([0-9.eE+-]+)"', xml)
            if m and float(m.group(1)) > 0:
                um = float(m.group(2)) / float(m.group(1)) * 1e6
        if um > 0:
            item.umpp = um
            item.calib = "LIF 内嵌标定"
        if samples == 3:
            item.channels = [Channel(i, n, "", 0, 0, (255, 255, 255), 0.0, 255.0, role="rgb")
                             for i, n in enumerate(("红", "绿", "蓝"))]
        else:
            chans = [dict(name="CH%d" % (i + 1), light="", ex=0, em=0) for i in range(nch)]
            item.channels = _assign_roles(chans, item.bits)
        if len(ims) > 1 and index is not None:
            item.name = "%s · 序列 %d/%d" % (os.path.basename(path), index + 1, len(ims))
            item.note = ("Leica LIF · 第 %d/%d 个序列（%s），尺寸 %d×%d"
                         % (index + 1, len(ims), getattr(im, "name", "?"),
                            item.width, item.height))
        else:
            item.note = "Leica LIF · 共 %d 个序列（取最大的一张：%s）" % (
                len(ims), getattr(im, "name", "?"))
    return item


def probe_all(path, group="g1"):
    """探测一个路径会出几个条目。

    徕卡 LIF 一个文件里经常有好几个序列（不同视野/不同处理），
    这里每个序列都单独出一个条目；其它格式就是一条。
    """
    ext = os.path.splitext(path)[1].lower()
    if ext in LIF_EXT:
        try:
            import liffile
            with liffile.LifFile(path) as f:
                n = len(list(iter(f.images)))
        except Exception:                        # noqa: BLE001
            n = 0
        if n > 1:
            out = []
            for i in range(n):
                it = ImageItem(path="%s#%d" % (path, i + 1), group=group)
                try:
                    _probe_lif(path, it, index=i)
                except Exception as exc:         # noqa: BLE001
                    it.note = "读取失败：%s" % exc
                    it.calib = "失败"
                out.append(it)
            return out
    return [probe(path, group)]


def _load_lif(item):
    import liffile
    with liffile.LifFile(item.file_path) as f:
        ims = list(iter(f.images))
        im = ims[item.series] if 0 <= item.series < len(ims) else _lif_pick(ims)
        arr = np.asarray(im.asarray())
        sizes = dict(getattr(im, "sizes", {}) or {})
        axes = getattr(im, "axes", "") or ""
        if isinstance(axes, (list, tuple)):
            axes = "".join(str(a) for a in axes)
    nch = max(1, int(sizes.get("C", 1) or 1))
    samples = 3 if int(sizes.get("S", 1) or 1) >= 3 else 1
    if samples == 3:
        # 每个通道本来就是彩色图：按最大合图，按 (T, 3, Y, X) 交给界面
        if arr.ndim == 3:                       # (Y, X, 3)
            merged = arr
            return np.transpose(merged, (2, 0, 1))[None]
        if arr.ndim == 4:                       # (C, Y, X, 3) 或 (T, Y, X, 3)
            if arr.shape[1] == item.height and arr.shape[0] == nch:
                merged = arr.max(axis=0)
                return np.transpose(merged, (2, 0, 1))[None]
            merged = arr.max(axis=0) if arr.shape[0] == nch else arr
            return np.transpose(merged, (2, 0, 1))[None]
        if arr.ndim == 5:                       # (T, C, Y, X, 3)
            merged = arr.max(axis=1)
            return np.transpose(merged, (0, 3, 1, 2))
        raise ValueError("LIF 彩色数据维度看不懂：%s" % (arr.shape,))
    t_dim = int(sizes.get("T", 1) or 1)
    z_dim = int(sizes.get("Z", 1) or 1)
    arr5 = to_tczyx(arr, axes)
    if arr5 is not None and arr5.shape[1] == nch and arr5.shape[0] * arr5.shape[2] == t_dim * z_dim:
        return _canonical(arr5, nch, t_dim, z_dim)
    return _canonical(arr, nch, t_dim, z_dim)


def _canonical(arr, c_count=1, t_count=1, z_count=1):
    """把各种读进来的数组摆成 (帧, 通道, Y, X)；Z 也当帧用。"""
    arr = np.asarray(arr)
    if arr.ndim == 2:
        return arr[None, None]
    if arr.ndim == 3:
        if arr.shape[0] == c_count:
            return arr[None]
        return arr[:, None]
    if arr.ndim == 4:
        if arr.shape[1] == c_count:
            return arr
        if arr.shape[0] == c_count:
            return np.transpose(arr, (1, 0, 2, 3))
        return arr
    if arr.ndim == 5:                            # (T, C, Z, Y, X)
        a = np.transpose(arr, (0, 2, 1, 3, 4))   # → (T, Z, C, Y, X)
        t, z, c = a.shape[0], a.shape[1], a.shape[2]
        return a.reshape(t * z, c, a.shape[3], a.shape[4])
    raise ValueError("看不懂的图像维度：%s" % (arr.shape,))


def _probe_raster(path, item):
    im = Image.open(path)
    item.width, item.height = im.size
    item.frames = int(getattr(im, "n_frames", 1) or 1)
    ext_p = os.path.splitext(path)[1].lower()
    if ext_p in (".tif", ".tiff"):
        _probe_tiff_dims(path, item)          # OME 的 SizeT/SizeZ/DimensionOrder
    if int(item.t_count or 1) * int(item.z_count or 1) != int(item.frames or 1):
        # 元数据说不清就默认「全是时间序列」，界面上可以手动改（规格书 3.18.3）
        set_dims(item, item.frames, 1, declared=False, t_declared=False)
    item.bits = 16 if im.mode.startswith("I;16") else 8
    maxv = 65535.0 if item.bits == 16 else 255.0
    layout, active = _raster_layout(im)
    if im.mode.startswith("I;16") or im.mode == "L":
        layout, active = "gray", [0]
    ext = os.path.splitext(path)[1].lower()
    umpp = _umpp_from_tiff(path) if ext in (".tif", ".tiff") else 0.0
    if not umpp:
        dpi = im.info.get("dpi")
        if dpi and dpi[0]:
            umpp = 25400.0 / float(dpi[0])
    if ext_p in (".tif", ".tiff") and _probe_tiff_channels(path, item):
        pass                                       # 多通道 TIFF：按 SizeC 建好了通道表
    elif layout == "rgb":
        names = ("红", "绿", "蓝")
        item.channels = [Channel(index=c, name=names[c], light="",
                                 color=(255, 255, 255), black=0.0, white=255.0, role="rgb")
                         for c in range(3)]
        item.calib = item.calib or "未标定"
    else:
        # 真灰度图（L / I;16 / 单色 BMP-PNG）：当灰底，像素值本身不动
        item.channels = [Channel(index=0, name="灰度图", light="", color=GRAY,
                                 black=0.0, white=maxv, role="gray")]
    if umpp > 0:
        item.umpp = float(umpp)
        item.calib = "文件内分辨率"
    im.close()
    mark_private(item, path)
    return item


def mark_private(item, path):
    """本软件导出的原始位深 TIFF 里带私有 tag：标注出来（规格书 3.11.7）。

    只认 tag 不读数据 —— 读几十 MB 的内嵌数据要等用户真的点「还原」。
    """
    try:
        from core import raw as raw_mod
        ids = raw_mod.tag_ids(path)
        if raw_mod.TAG_PROC in ids:
            item.has_proc = True
            item.embed_ok = raw_mod.TAG_BLOB0 in ids
            if "（带处理记录）" not in (item.calib or ""):
                item.calib = (item.calib or "未标定") + "（带处理记录）"
    except Exception:                            # noqa: BLE001
        pass


def _probe_tiff_dims(path, item):
    """TIFF 的 T/Z 从哪来（规格书 3.18.2）。

    有 OME 就认 OME 的 SizeT / SizeZ / PhysicalSizeZ / DimensionOrder 和 tifffile 给的
    `series.axes`；**多页无元数据的 TIFF**（相机拍的 Z 序列）说不清 → 默认全当时间序列，
    界面上给个胶囊让用户自己声明（3.18.3）。
    """
    try:
        import tifffile
        with tifffile.TiffFile(path) as tf:
            ser = tf.series[0] if tf.series else None
            axes = "".join(str(a) for a in (getattr(ser, "axes", "") or ""))
            ome = getattr(tf, "ome_metadata", None) or ""
            if ser is not None and "Z" in axes.upper() and "T" in axes.upper():
                t_n = int(ser.shape[axes.upper().index("T")])
                z_n = int(ser.shape[axes.upper().index("Z")])
                set_dims(item, t_n, z_n, declared=True, t_declared=True)
            elif "Z" in axes.upper() and "T" not in axes.upper():
                z_n = int(ser.shape[axes.upper().index("Z")])
                set_dims(item, 1, z_n, declared=True, t_declared=False)
            elif "T" in axes.upper():
                t_n = int(ser.shape[axes.upper().index("T")])
                set_dims(item, t_n, 1, declared=False, t_declared=True)
            elif ome:
                m_t = re.search(r'SizeT="(\d+)"', ome)
                m_z = re.search(r'SizeZ="(\d+)"', ome)
                t_n = int(m_t.group(1)) if m_t else 1
                z_n = int(m_z.group(1)) if m_z else 1
                set_dims(item, t_n, z_n, declared=bool(m_z and z_n > 1),
                         t_declared=bool(m_t))
            if ome:
                mz = re.search(r'PhysicalSizeZ="([0-9.eE+-]+)"', ome)
                if mz:
                    item.z_step_um = sane_z_step(float(mz.group(1)))
                mt = re.search(r'TimeIncrement="([0-9.eE+-]+)"', ome)
                if mt:
                    item.t_interval_s = sane_interval_s(float(mt.group(1)))
    except Exception:                                 # noqa: BLE001
        pass
    return item


def _probe_tiff_channels(path, item):
    """多通道 TIFF / OME-TIFF 的通道表。

    老代码对位图格式一律只建**一个**通道，于是 3 通道的 OME-TIFF 在界面上只有 1 路，
    原始位深导出还会因为"通道表长度对不上"写不出 OME（实测踩过）。
    这里按 SizeC / series.axes 建够，通道名/波长/颜色优先用 OME 里声明的。
    """
    try:
        import tifffile
        with tifffile.TiffFile(path) as tf:
            ser = tf.series[0] if tf.series else None
            axes = "".join(str(a) for a in (getattr(ser, "axes", "") or "")).upper()
            c_n = 1
            if ser is not None and "C" in axes:
                c_n = int(ser.shape[axes.index("C")])
            ome = tf.ome_metadata or ""
        if c_n <= 1:
            return False
        names = re.findall(r'<Channel[^>]*\sName="([^"]*)"', ome)
        exs = [int(float(v)) for v in re.findall(r'ExcitationWavelength="([0-9.eE+-]+)"', ome)]
        ems = [int(float(v)) for v in re.findall(r'EmissionWavelength="([0-9.eE+-]+)"', ome)]
        cols = re.findall(r'Color="([^"]*)"', ome)
        chans = []
        for i in range(c_n):
            chans.append(dict(name=(names[i] if i < len(names) else "") or ("CH%d" % (i + 1)),
                              light="",
                              ex=(exs[i] if i < len(exs) else 0),
                              em=(ems[i] if i < len(ems) else 0)))
        item.channels = _assign_roles(chans, item.bits)
        for i, c in enumerate(cols[:c_n]):        # OME 声明了颜色就用它
            rgb = _ome_color(c)
            if rgb:
                item.channels[i].color = rgb
        return True
    except Exception:                             # noqa: BLE001
        return False


def _ome_color(spec):
    """OME 的 Channel Color：可能是 #RRGGBB，也可能是带符号整数（ARGB）。"""
    try:
        s = str(spec).strip()
        if s.startswith("#"):
            v = int(s[1:], 16)
        else:
            v = int(float(s)) & 0xFFFFFFFF
        return ((v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF)
    except Exception:                             # noqa: BLE001
        return None


def _umpp_from_tiff(path):
    """TIFF 分辨率标签 / OME 元数据里的 µm/px。"""
    try:
        import tifffile
        with tifffile.TiffFile(path) as tf:
            ome = getattr(tf, "ome_metadata", None)
            if ome:
                m = re.search(r'PhysicalSizeX="([0-9.eE+-]+)"', ome)
                if m and float(m.group(1)) > 0:
                    return float(m.group(1))
            page = tf.pages[0]
            xres = page.tags.get("XResolution")
            unit = page.tags.get("ResolutionUnit")
            if xres is not None:
                val = xres.value
                num, den = (val[0], val[1]) if isinstance(val, tuple) else (val, 1)
                ppu = float(num) / float(den or 1)
                if ppu > 0:
                    u = int(unit.value) if unit is not None else 2
                    if u == 3:
                        return 10000.0 / ppu
                    if u == 2:
                        return 25400.0 / ppu
    except Exception:                            # noqa: BLE001
        pass
    return 0.0


def probe(path, group="g1"):
    """只读元数据、不解码像素。"""
    item = ImageItem(path=path, group=group)
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext in OIB_EXT:
            _probe_oib(path, item)
        elif ext in CZI_EXT:
            _probe_czi(path, item)
        elif ext in LIF_EXT:
            _probe_lif(path, item)
        else:
            _probe_raster(path, item)
    except Exception as exc:                     # noqa: BLE001
        item.note = "读取失败：%s" % exc
        item.calib = "失败"
    return item


# ---------------------------------------------------------------- 读像素

def load_stack(item: ImageItem):
    """返回 (T, C, Y, X) 数组；结果缓存在 item 上。

    处理链（配准 / 背景扣除 / 漂移）在这里生效。**缓存 key 必须含处理链指纹**
    （规格书 2.3）：老写法只看 `_cache is not None`，改一下配准参数界面还是旧数据。
    """
    from core import register as reg
    from core.model import process_fingerprint
    key = (process_fingerprint(item), item.path)
    cached = item._cache
    if cached is not None:
        if getattr(item, "_cache_key", None) == key:
            reg.cache_note(item, int(cached.nbytes))
            return cached
        if getattr(item, "_cache_key", None) is None and not (item.process or []):
            return cached          # 手工/测试塞进来的缓存，且没有处理链：原样用
    # 链前数据单独缓存一份：换处理参数时不用重新解码原文件（大图能省几秒）
    raw = getattr(item, "_raw_cache", None)
    if raw is None:
        raw = read_source(item)
        item._raw_cache = raw
    arr = reg.apply_chain(raw, item) if (item.process or []) else raw
    item._cache = arr
    item._cache_key = key
    item.frames = max(1, arr.shape[0])
    # 兜底：元数据声明的通道数多于数据里真有的通道数时，按数据为准裁掉多余的
    # （Zeiss 的多 Image / raw+processed 文件很容易多报，界面上就会凭空多出几路）
    try:
        real_c = int(arr.shape[1])
        if real_c >= 1 and len(item.channels or []) > real_c:
            item.note = ((item.note or "") +
                         "　元数据多报了通道（%d > %d），已按数据裁掉多余的"
                         % (len(item.channels), real_c)).strip()
            item.channels = list(item.channels[:real_c])
    except Exception:                            # noqa: BLE001
        pass
    # 再兜一条更常见的：元数据声明了、但**数据其实是全黑的**通道
    # （蔡司偶尔会记一路空的 Bright/T-PMT，留在界面上就是多一行灰通道 —— 用户实测反馈）。
    # 判据很保守：99.9 分位 ≤ 1 且非零像素 < 1%，这种通道本来就是黑的，删掉不丢信息。
    try:
        chans = list(item.channels or [])
        if len(chans) > 1:
            keep, dropped = [], []
            for c in chans:
                idx = int(getattr(c, "index", 0))
                if idx >= arr.shape[1]:
                    dropped.append(c.name or "CH%d" % (idx + 1))
                    continue
                plane = np.asarray(arr[0, idx], np.float32)[::2, ::2]
                empty = (float(np.percentile(plane, 99.9)) <= 1.0
                         and float((plane > 0).mean()) < 0.01)
                if empty and len(chans) - len(dropped) > 1:
                    dropped.append(c.name or "CH%d" % (idx + 1))
                else:
                    keep.append(c)
            if dropped and keep:
                item.channels = keep
                item.note = ((item.note or "") +
                             "　已隐藏空通道：%s" % "、".join(dropped)).strip()
    except Exception:                            # noqa: BLE001
        pass
    # 再一条：同一路的"原始版 + 处理版"会被存成两个通道（蔡司 Airyscan 常见）——
    # 两层高度重合（相关系数 ≥ 0.98）且亮度差 ≥ 3 倍时，只留**亮的那层（处理版）**。
    # 实测：Snap-14700 在 ZEN 里就是一路绿，文件里却有两层（相关 0.986、亮度差 18.6 倍）。
    try:
        chans = list(item.channels or [])
        if len(chans) > 1:
            prof = {}
            for c in chans:
                idx = int(getattr(c, "index", 0))
                if idx < arr.shape[1]:
                    pl = _block_mean(np.asarray(arr[0, idx], np.float32))
                    prof[idx] = pl

            def _corr(a, b):
                a = a - a.mean()
                b = b - b.mean()
                d = float(np.linalg.norm(a) * np.linalg.norm(b))
                return float((a * b).sum() / d) if d > 0 else 0.0

            drop, keep2 = set(), []
            for i, c in enumerate(chans):
                ci = int(getattr(c, "index", 0))
                if ci in drop or ci not in prof:
                    continue
                for c2 in chans[i + 1:]:
                    cj = int(getattr(c2, "index", 0))
                    if cj in drop or cj not in prof:
                        continue
                    a, b = prof[ci], prof[cj]
                    if a.shape != b.shape or _corr(a, b) < 0.98:
                        continue
                    ma, mb = float(a.mean()), float(b.mean())
                    if min(ma, mb) <= 0:
                        continue
                    ratio = max(ma, mb) / min(ma, mb)
                    if ratio < 3.0:                  # 亮度差不够大，不当重复
                        continue
                    dull = ci if ma < mb else cj
                    drop.add(dull)
            if drop:
                for c in chans:
                    n = c.name or ("CH%d" % (int(getattr(c, "index", 0)) + 1))
                    if int(getattr(c, "index", 0)) in drop:
                        kept = next(x.name for x in chans
                                    if int(getattr(x, "index", 0)) not in drop)
                        item.note = ((item.note or "") +
                                     "　已合并重复通道：%s（与 %s 是同一路的原始版）"
                                     % (n, kept)).strip()
                    else:
                        keep2.append(c)
                if keep2:
                    item.channels = keep2
    except Exception:                            # noqa: BLE001
        pass
    _auto_ranges(item, raw if arr is not raw else arr)   # 显示区间按**链前**数据估
    if arr is not raw:
        reg.cache_note(item, int(arr.nbytes))
    return arr


def read_source(item: ImageItem):
    """从文件里直接读像素（**不查缓存、不过处理链**）。"""
    # 拼图条目：工程文件里只存了来源与布局，重开时按参数重拼（P1-9 4.22.1）
    doc = getattr(item, "stitch", None)
    if doc and doc.get("sources") and not os.path.exists(item.file_path):
        from core import stitch as stitch_mod
        try:
            stitch_mod.restitch(item)
        except Exception:                            # noqa: BLE001
            pass
    ext = os.path.splitext(item.file_path)[1].lower()
    if ext in OIB_EXT:
        return _load_oib(item)
    if ext in CZI_EXT:
        return _load_czi(item)
    if ext in LIF_EXT:
        return _load_lif(item)
    return _load_raster(item)


def _block_mean(plane, target: int = 256):
    """块平均降采样（到约 target 边长）。

    做"两层是不是同一张图"这类相关比较时**必须用块平均**，不能用 [::4] 抽点：
    共聚焦图有散斑，抽点会把相关系数从 0.99 拉到 0.80（实测），
    判据就会失灵。
    """
    a = np.asarray(plane, np.float32)
    k = max(1, int(max(a.shape) // max(32, int(target))))
    if k <= 1:
        return a
    h, w = a.shape
    h2, w2 = (h // k) * k, (w // k) * k
    if h2 < 16 or w2 < 16:
        return a
    return a[:h2, :w2].reshape(h2 // k, k, w2 // k, k).mean(axis=(1, 3))


def raw_stack(item: ImageItem):
    """**链前**原始像素（不查缓存、不过处理链）。

    规格书 3.11.7：原始位深导出内嵌的"可精确还原"数据必须是这一份。
    今天 `load_stack()` 就等于它（还没有处理链）；P1-7 上了处理链之后，
    `load_stack()` 会变成"按链重建"，而这个函数必须保持原样。
    """
    cached = getattr(item, "_raw_cache", None)
    if cached is not None:
        return cached
    raw = read_source(item)
    item._raw_cache = raw
    return raw


def _auto_ranges(item, arr):
    """第一次读像素时按数据本身定一套显示区间（黑点/白点）。

    2026-09-26 改了两处（用户反馈"黑白不是默认的最大最小值 + 颜色发白"）：

    ① **黑/白点默认 = 该通道数据的实际最小/最大值**（`estimate_ranges` 现在这么返回）。
       以前是 55 / 99.8 分位（自动拉伸），导出彩图也跟着被拉伸，跟原始观感对不上。
       想要拉伸的用通道行 ⋯ →「重置为自动区间（1%~99.8 分位）」。
    ② **按 `ch.index`（数据面序号）取区间，不能按列表位置**：
       前面只要有通道被"隐藏空通道/合并重复层"删掉，后面的通道就会拿到别人的
       黑白点 —— 实测 ER1.oib 的明场拿到了荧光通道的区间（13.9% 像素压成纯白），
       Snap-14700 的 EGFP 拿到了被丢弃那层的区间（2.17% 过曝）。
    """
    if getattr(item, "_ranges_ready", False):
        return
    item._ranges_ready = True
    try:
        if all(ch.role == "rgb" for ch in item.channels):
            return
        rng = estimate_ranges(arr)
        for ch in item.channels:
            idx = int(getattr(ch, "index", 0))
            if 0 <= idx < len(rng):
                lo, hi, top = rng[idx]
            else:                                # 兜底：按这一路数据自己的范围
                try:
                    plane = np.asarray(arr[0, idx], np.float32)
                    lo, hi = float(plane.min()), float(plane.max())
                except Exception:                # noqa: BLE001
                    lo, hi = 0.0, float(full_scale(arr.dtype))
                top = max(hi, 16.0)
            if hi > lo:
                ch.black, ch.white = lo, hi
            ch.vmax = max(16.0, float(top))
    except Exception:                            # noqa: BLE001
        pass


def full_scale(dtype) -> float:
    """这个 dtype 的满量程（整数取 iinfo.max，浮点取 1.0）。"""
    try:
        d = np.dtype(dtype)
        if np.issubdtype(d, np.integer):
            return float(np.iinfo(d).max)
        return 1.0
    except Exception:                            # noqa: BLE001
        return 255.0


def compute_frame_ranges(item, report=None, only_frame=None):
    """逐帧 / 按参考帧的显示区间（规格书 3.25.3）。

    返回 {(帧号, 通道序号): (黑点, 白点)}；`range_mode == "global"` 时返回 {}。

    抗光漂白原理：
      · per_frame —— 每帧自己算分位点。抗漂白最好，但会**抹掉真实的强度衰减**，
                    所以界面上必须提示"定量分析别开"。
      · ref       —— 以参考帧窗口的**宽度**为准，整体平移到当前帧的黑点上。
                    这样相对强弱还在（亮的还是亮的），只是把整体变暗修正回来。

    逐帧分位数是 frames × channels 次计算，大图上很慢 → 抽样 + 走后台线程。
    `only_frame` 只算一帧（界面刚切模式时先算当前帧，用户立刻看到变化）；
    这时**不**写 `_frame_ranges_key`，后台线程随后会把整批补全。
    """
    mode = getattr(item, "range_mode", "global") or "global"
    if mode == "global":
        return {}
    stack = load_stack(item)
    frames, c_count, h, w = stack.shape
    step = max(1, int(max(h, w) / 512))
    p_lo = float(getattr(item, "range_p_lo", 55.0) or 55.0)
    p_hi = float(getattr(item, "range_p_hi", 99.8) or 99.8)
    ref = max(0, min(int(getattr(item, "ref_frame", 0) or 0), frames - 1))
    partial = only_frame is not None
    out = dict(getattr(item, "_frame_ranges", None) or {}) if partial else {}
    # "按参考帧"要先算出参考帧自己的窗口（宽度），帧号比参考帧小的那些也要用得上
    ref_win = {}
    if mode == "ref":
        for c in range(c_count):
            plane = stack[ref, c][::step, ::step].astype(np.float32)
            ref_win[c] = (float(np.percentile(plane, p_lo)),
                          float(np.percentile(plane, p_hi)))
    todo = [max(0, min(int(only_frame), frames - 1))] if partial else list(range(frames))
    total = max(1, len(todo))
    for i, f in enumerate(todo):
        if callable(report):
            report(i, total, "第 %d 帧" % (f + 1))
        for c in range(c_count):
            plane = stack[f, c][::step, ::step].astype(np.float32)
            lo = float(np.percentile(plane, p_lo))
            hi = float(np.percentile(plane, p_hi))
            if mode == "ref":
                lo0, hi0 = ref_win.get(c, (lo, hi))
                width = max(1.0, hi0 - lo0)
                out[(f, c)] = (lo, lo + width)
            else:
                out[(f, c)] = (lo, hi if hi > lo else lo + 1.0)
    try:
        item._frame_ranges = out
        if not partial:                          # 全量算完才算"缓存有效"
            item._frame_ranges_key = (item.path, mode, ref, frames, p_lo, p_hi)
    except Exception:                            # noqa: BLE001
        pass
    return out


def has_frame_ranges(item) -> bool:
    """缓存还有效吗（帧数 / 模式 / 参考帧 / 分位数变了就要重算）。"""
    key = (getattr(item, "path", ""), getattr(item, "range_mode", "global"),
           int(getattr(item, "ref_frame", 0) or 0), int(getattr(item, "frames", 1) or 1),
           float(getattr(item, "range_p_lo", 55.0) or 55.0),
           float(getattr(item, "range_p_hi", 99.8) or 99.8))
    return (getattr(item, "_frame_ranges", None) is not None
            and getattr(item, "_frame_ranges_key", None) == key)


def _load_oib(item):
    import oiffile
    with oiffile.OifFile(item.path) as f:
        arr = np.asarray(f.asarray())
        axes = f.axes or ""
        decl = tuple(f.shape)
    order = infer_axes(arr, decl, axes) or axes
    arr5 = to_tczyx(arr, order)
    if arr5 is None:                                 # 元数据缺失 → 老兜底
        if arr.ndim == 2:
            return arr[None, None]
        if arr.ndim == 3:
            return arr[None] if arr.shape[0] in (1, 2, 3, 4) else arr[:, None]
        return arr if arr.ndim == 4 else arr.reshape(-1, 1, *arr.shape[-2:])
    t_n, c_n, z_n = arr5.shape[0], arr5.shape[1], arr5.shape[2]
    if item.t_count * item.z_count == t_n * z_n:      # 探测值和实际一致就用探测的
        t_n, z_n = item.t_count, item.z_count
    return _canonical(arr5, c_n, t_n, z_n)


def _load_raster(item):
    ext = os.path.splitext(item.file_path)[1].lower()
    if ext in (".tif", ".tiff"):
        try:
            import tifffile
            with tifffile.TiffFile(item.file_path) as tf:
                ser = tf.series[0] if tf.series else None
                arr = np.asarray(ser.asarray() if ser is not None else tf.asarray())
                axes = "".join(str(a) for a in (getattr(ser, "axes", "") or ""))
            # OME / SGD 那种"存储顺序 ≠ TCZYX"的文件，按声明顺序显式重排（3.18.2 硬规则）
            arr5 = to_tczyx(arr, axes)
            if arr5 is not None and arr5.shape[-2:] == (item.height, item.width):
                return _canonical(arr5, arr5.shape[1], arr5.shape[0], arr5.shape[2])
            if arr.ndim == 2:
                return arr[None, None]
            if arr.ndim == 3:
                if arr.shape[-1] in (3, 4) and arr.shape[0] > 4:
                    return arr.transpose(2, 0, 1)[None] if arr.shape[-1] == 3 else arr[..., :3].transpose(2, 0, 1)[None]
                if arr.shape[0] in (3, 4) and arr.shape[0] < arr.shape[1]:
                    return arr[None]
                return arr[:, None]
            if arr.ndim == 4:
                if arr.shape[0] > arr.shape[1]:
                    arr = np.transpose(arr, (1, 0, 2, 3))
                return arr
        except Exception:                        # noqa: BLE001
            pass
    im = Image.open(item.file_path)
    frames = int(getattr(im, "n_frames", 1) or 1)
    layout, _active = _raster_layout(im)
    if im.mode.startswith("I;16") or im.mode == "L":
        layout = "gray"
    planes = []
    for i in range(frames):
        if frames > 1:
            im.seek(i)
        if layout == "rgb":
            a = np.asarray(im.convert("RGB")).astype(np.uint8)
            planes.append(a.transpose(2, 0, 1))
        else:
            a = np.asarray(im)
            if a.ndim == 3:
                a = a[..., 0]
            planes.append(a[None])
    im.close()
    return np.stack(planes)


def release(item):
    item._cache = None
    item._raw_cache = None
    item._cache_key = None


# ---------------------------------------------------------------- 缩略图与区间

def thumb_path(item, size=256):
    try:
        st = os.stat(item.path)
        stamp = "%s|%s" % (st.st_mtime, st.st_size)
    except OSError:
        stamp = "?"
    # 通道配色/显示区间变了，缩略图也要重出（否则会一直是旧图）
    sig = "|".join("%s:%s:%s:%d:%d" % (c.name, c.role, tuple(c.color),
                                       round(c.black), round(c.white))
                   for c in (item.channels or []))
    # 投影/归一化改了，缩略图也得重出（否则一直显示旧样子）
    sig += "|proj:%s:%s:%d:%d:%d" % (getattr(item, "proj_mode", "none") or "none",
                                     getattr(item, "proj_range_mode", "all") or "all",
                                     int(getattr(item, "proj_n", 0) or 0),
                                     int(getattr(item, "proj_from", 0) or 0),
                                     int(getattr(item, "proj_to", -1) or -1))
    sig += "|z:%d:%d" % (int(getattr(item, "proj_center", 0) or 0),
                         int(getattr(item, "z_count", 1) or 1))
    key = "%s|%s|%s|%s" % (item.path, stamp, size, sig)
    return os.path.join(paths.THUMB_DIR, hashlib.md5(key.encode("utf-8")).hexdigest() + ".jpg")


def estimate_ranges(stack):
    """每个通道一套默认显示区间 + 滑条上限：(黑, 白, 上限)。

    **黑/白 = 该通道数据的实际最小/最大值**（2026-09-26 用户口径：默认就是最大最小）。
    第三个数是滑条上限，取"99.99 分位与实际最大值的较大者"—— 只取分位数的话，
    个别通道的滑条够不到真实最亮像素。

    历史 bug（规格书 3.25.1）：老写法是 `range(min(c_count, 3))`，只给前 3 个通道估，
    第 4 个及以后硬编码成 (0, 255, 255)。而共聚焦 4 通道的数据是 4095 量级 →
    那个通道一打开就是**全白**，滑条范围还只有 0–255，拖不到有效区间。
    """
    out = []
    frames, c_count, h, w = stack.shape
    step = max(1, int(max(h, w) / 512))
    for c in range(c_count):
        ch = stack[0, c][::step, ::step].astype(np.float32)
        top = max(float(np.percentile(ch, 99.99)), float(ch.max()))
        out.append((float(ch.min()), float(ch.max()), top))
    return out
