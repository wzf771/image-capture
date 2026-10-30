# -*- coding: utf-8 -*-
"""数据模型：通道、图片、分组、参数。"""
from __future__ import annotations

import json
import re
import os
from dataclasses import dataclass, field, asdict

import paths

# 默认配色（荧光 1 → 绿、荧光 2 → 红、透射光 → 灰阶）
#
# 2026-09-26 用户反馈"彩色通道跟原始有色差"：老的默认色是给界面配的柔和色
# （绿 (47,208,127) 色相 149.8°、红 (255,85,102) 偏粉），跟各家显影软件显示的
# 纯色差 20~30°。现在默认改成纯色（绿 0,255,0 / 红 255,0,0 / 蓝 0,0,255 …），
# 旧的柔和色保留成"·柔和"几个可选项，谁喜欢谁选。
GREEN = (0, 255, 0)
RED = (255, 0, 0)
BLUE = (0, 0, 255)
YELLOW = (255, 255, 0)
CYAN = (0, 255, 255)
MAGENTA = (255, 0, 255)
GRAY = (200, 200, 200)         # 明场通道：纯中性灰（合成时按"灰阶"处理，不会偏色）
WHITE = (255, 255, 255)

# 旧的柔和配色（2026-09-26 之前的所有默认值），保留成可选项
SOFT_GREEN = (47, 208, 127)
SOFT_RED = (255, 85, 102)
SOFT_BLUE = (90, 150, 255)
SOFT_YELLOW = (255, 214, 0)
SOFT_CYAN = (60, 210, 255)
SOFT_MAGENTA = (230, 80, 230)
SOFT_GRAY = (207, 211, 221)

# 通道可选颜色（界面下拉用）
CHANNEL_COLORS = [
    ("绿", GREEN), ("红", RED), ("黄", YELLOW), ("青", CYAN),
    ("品红", MAGENTA), ("蓝", BLUE), ("灰阶", GRAY), ("白", WHITE),
    ("绿·柔和", SOFT_GREEN), ("红·柔和", SOFT_RED), ("蓝·柔和", SOFT_BLUE),
    ("黄·柔和", SOFT_YELLOW), ("青·柔和", SOFT_CYAN), ("品红·柔和", SOFT_MAGENTA),
]

# 染料/通道名 → 颜色（读 CZI/OIB 元数据时用得上）
DYE_COLORS = [
    ("yfp", YELLOW), ("eyfp", YELLOW), ("venus", YELLOW), ("citrine", YELLOW),
    ("gfp", GREEN), ("egfp", GREEN), ("fitc", GREEN), ("alexa488", GREEN),
    ("alexa 488", GREEN), ("488", GREEN), ("dylight488", GREEN),
    ("tritc", RED), ("rfp", RED), ("mcherry", RED), ("tdtomato", RED),
    ("alexa555", RED), ("alexa568", RED), ("alexa 633", RED), ("alexa633", RED),
    ("cy3", RED), ("555", RED), ("568", RED), ("561", RED), ("594", RED), ("640", RED),
    ("cfp", CYAN), ("ecfp", CYAN), ("cyan", CYAN), ("445", CYAN), ("458", CYAN),
    ("bfp", BLUE), ("dapi", BLUE), ("hoechst", BLUE), ("405", BLUE),
    ("cy5", MAGENTA), ("alexa647", MAGENTA), ("647", MAGENTA), ("far red", MAGENTA),
]

# 名字里出现这些 → 明场/透射光（蔡司叫 T PMT，徕卡叫 BF/TL，奥林巴斯叫 TD）
BRIGHTFIELD_KEYS = ("tpmt", "t pmt", "t-pmt", "transmitted", "brightfield",
                    "bright field", "bf", "tl", "dic", "phase contrast")


def looks_brightfield(name="", light="", dye=""):
    text = " %s %s %s " % (name or "", light or "", dye or "")
    low = text.lower()
    flat = re.sub(r"[\s\-_#]+", "", low)
    if "transmitted" in low or "bright" in low:
        return True
    if flat.startswith("bf") or flat in (" bf ",) or " tpmt " in low or "tpmt" in flat:
        return True
    return False


def color_for_dye(text):
    low = (" %s " % (text or "")).lower()
    for key, col in DYE_COLORS:
        if key in low:
            return col
    return None


def color_name(rgb):
    if not rgb:
        return "自定义"
    best, dist = "自定义", 1e9
    for label, col in CHANNEL_COLORS:
        d = sum((int(a) - int(b)) ** 2 for a, b in zip(rgb, col))
        if d < dist:
            best, dist = label, d
    return best

# 标尺可用的字体（都是 Windows 自带，程序只调用不打包）
FONTS = {
    "Arial": "arial.ttf",
    "Arial 粗体": "arialbd.ttf",
    "Times New Roman": "times.ttf",
    "Times New Roman 粗体": "timesbd.ttf",
    "微软雅黑": "msyh.ttc",
    "黑体": "simhei.ttf",
    "宋体": "simsun.ttc",
}
FONT_DIR = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")


@dataclass
class Channel:
    index: int                      # 原始通道序号（0 起）
    name: str = ""                  # CHS1 / TD1
    light: str = ""                 # Fluorescence / Transmitted Light
    ex: int = 0
    em: int = 0
    color: tuple = GREEN
    black: float = 0.0              # 显示区间黑点（原始强度）
    white: float = 4095.0           # 显示区间白点
    visible: bool = True
    role: str = "green"             # green / red / gray
    vmax: float = 0.0               # 数据实际最大值（界面拖条用），0 = 由位深推测


@dataclass
class ProcessStep:
    """处理链的一步（规格书 2.2）。

    原始像素永不被修改 —— 所有处理都记在链上，预览/导出时按链重建。
    """
    kind: str                                   # register / bg / deconvolve
    params: dict = field(default_factory=dict)
    enabled: bool = True


def process_fingerprint(item) -> str:
    """处理链指纹：缓存 key 必须带上它，否则改了参数界面还显示旧数据（规格书 2.3）。"""
    steps = []
    for s in (getattr(item, "process", None) or []):
        steps.append(dict(kind=getattr(s, "kind", ""),
                          params=getattr(s, "params", None) or {},
                          enabled=bool(getattr(s, "enabled", True))))
    return json.dumps(steps, sort_keys=True, ensure_ascii=False)


@dataclass
class ImageItem:
    path: str
    name: str = ""
    group: str = "g1"
    umpp: float = 0.0                # 微米/像素
    calib: str = "未标定"            # 标定来源说明
    width: int = 0
    height: int = 0
    frames: int = 1                  # 时间序列帧数
    bits: int = 8
    channels: list = field(default_factory=list)
    note: str = ""
    series: int = 0                  # 同一文件里的第几个序列（徕卡 LIF 常有多个）
    group_manual: bool = False       # 用户手工归的组，重组时不许被自动分桶打散
    group_key: str = ""              # 手工归组目标的稳定标识（组重排序也认得出）
    # —— P0-3 Z 与 T 分离（先占位，行为在 P0-3 实现；白名单一次写全，见规格书 3.4.3）——
    t_count: int = 1
    z_count: int = 1
    z_step_um: float = 0.0
    t_interval_s: float = 0.0
    z_declared_manual: bool = False
    z_meta_declared: bool = False     # 元数据确实声明了 Z 维度（决定要不要给"手动声明"胶囊）
    t_meta_declared: bool = False     # 元数据确实声明了 T 维度（同上；声明过就别打扰用户）
    # —— 2.2 处理链 ——
    process: list = field(default_factory=list)   # list[ProcessStep]
    # —— P0-4 显示区间 / 配色 ——
    range_mode: str = "global"        # global / per_frame / ref
    ref_frame: int = 0
    range_p_lo: float = 55.0          # 逐帧归一化用的黑点分位（与 estimate_ranges 默认一致）
    range_p_hi: float = 99.8          # 白点分位
    # —— P1-5 Z 投影 ——
    proj_mode: str = "none"
    proj_from: int = 0
    proj_to: int = -1
    proj_range_mode: str = "all"      # all / around（当前层 ± n）/ manual（起止层）
    proj_n: int = 3                   # "当前层 ± n" 的 n
    proj_center: int = 0              # "当前层 ± n" 的中心层（跟随 Z 滑条）
    # —— P1-6 定量分析 ——
    rois: list = field(default_factory=list)
    # —— P1-9 多 tile / 拼图 ——
    stitch: dict = field(default_factory=dict)
    _cache = None
    # 标尺识别的原始结果（bar.detect_umpp 的返回）：界面靠它把"识别到哪根线"画出来。
    # 故意不写进 dataclass 字段 —— asdict() 不带类属性，工程文件里就不会混进这坨临时数据。
    detect = None
    missing = False                  # 工程里记着、但磁盘上找不到的图（灰色占位，导出跳过）
    # 逐帧显示区间的缓存（P0-4）：{(帧, 通道): (黑, 白)}；同样不进工程文件
    _frame_ranges = None
    _frame_ranges_key = None

    def __post_init__(self):
        if not self.name:
            self.name = os.path.basename(self.path)

    @property
    def px_size(self):
        return (self.width, self.height)

    @property
    def file_path(self):
        """真实文件路径：多序列条目的 path 会带 "#2" 这样的后缀。"""
        p = self.path or ""
        i = p.rfind("#")
        if i > 0 and p[i + 1:].isdigit():
            return p[:i]
        return p

    def field_um(self):
        """这张图的物理视野（µm）。"""
        return self.width * self.umpp

    # ---- Z / T 分离（P0-3）。内存里仍然是 (F, C, Y, X)，F = t_count × z_count ----
    @property
    def z_range_um(self):
        return max(0.0, (max(1, int(self.z_count or 1)) - 1) * float(self.z_step_um or 0.0))

    def flat_index(self, t, z):
        """(时间点, Z 层) → 展平帧号。

        **顺序必须是 t * z_count + z** —— 与 `_canonical` 的 `reshape(t*z, ...)` 一致。
        写成 z * t_count + t 会让所有已有数据错位（规格书 3.18.1）。
        """
        zc = max(1, int(self.z_count or 1))
        tc = max(1, int(self.t_count or 1))
        return min(max(0, int(t)), tc - 1) * zc + min(max(0, int(z)), zc - 1)

    def tz_of(self, f):
        """展平帧号 → (时间点, Z 层)。"""
        return divmod(max(0, int(f)), max(1, int(self.z_count or 1)))

    def declare_frames(self, kind):
        """手工声明多帧是"Z 栈"还是"时间序列"（规格书 3.18.3，只在元数据说不清时用）。"""
        n = max(1, int(self.frames or 1))
        if kind == "z":
            self.z_count, self.t_count = n, 1
        else:
            self.t_count, self.z_count = n, 1
        self.z_declared_manual = True
        # 注意：不丢缓存 —— 重新解释 Z/T 只改"含义"，展平顺序和像素都没变
        return self.t_count, self.z_count

    def channel_by_role(self, role):
        for ch in self.channels:
            if ch.role == role:
                return ch
        return None


@dataclass
class Group:
    gid: str
    title: str
    key: str = ""                                   # 稳定标识：重组/重排序都不会变
    images: list = field(default_factory=list)      # list[ImageItem]
    box: dict = field(default_factory=dict)         # x, y, w, h（µm，左上角）
    sync: bool = True                               # 组内裁剪框位置一致
    boxes: dict = field(default_factory=dict)       # 关掉同步后每张各记一份
    out_dir: str = ""
    bar_anchor: tuple = None                        # 自定义标尺位置（0~1，相对裁剪后的画面）
    bar_text_anchor: tuple = None                   # 自定义文字位置；None = 跟着标尺
    title_manual: bool = False                      # 用户改过名字，重组时别覆盖
    keep_empty: bool = False                        # 手工建的空组，重组时保留

    def __post_init__(self):
        if not self.key:
            self.key = Group.new_key()

    @classmethod
    def _used_keys(cls):
        used = getattr(cls, "_used", None)
        if used is None:
            used = cls._used = set()
        return used

    @classmethod
    def new_key(cls):
        """生成一个从没用过的 key。

        历史坑（规格书 3.4.6 坑 2）：老写法只看类级计数器，载入工程后计数器从 0 重来，
        新建组会造出跟工程里一模一样的 k1/k2，`_regroup()` 按 key 匹配就把图放错组。
        这里多维护一个"用过的 key"集合，撞了就往后跳。
        """
        used = cls._used_keys()
        while True:
            cls._seq = getattr(cls, "_seq", 0) + 1
            k = "k%d" % cls._seq
            if k not in used:
                used.add(k)
                return k

    @classmethod
    def reserve_key(cls, key):
        """载入工程时把已有 key 登记进来，并把计数器推到它之后。

        注意：**不因为"这个 key 之前出现过"就换掉它** —— 工程里的 key 是数据的一部分
        （`it.group_key` 指着它），换掉就会把图挪错组。重复 key 的判重由载入方
        在本批数据里做（project.load_into），不是在这里做。
        """
        if not key:
            return True
        used = cls._used_keys()
        used.add(key)
        if key.startswith("k") and key[1:].isdigit():
            cls._seq = max(getattr(cls, "_seq", 0), int(key[1:]))
        else:                                    # 兼容任意形式的 key（别的机器写的工程）
            cls._seq = getattr(cls, "_seq", 0) + 1
        return True

    @property
    def count(self):
        return len(self.images)

    def umpp(self):
        vals = [im.umpp for im in self.images if im.umpp > 0]
        return vals[0] if vals else 0.0

    def box_for(self, item: ImageItem):
        if self.sync:
            return self.box
        return self.boxes.setdefault(item.path, dict(self.box))


@dataclass
class Settings:
    # 裁剪
    crop_w: float = 30.0
    crop_h: float = 30.0
    lock_1to1: bool = True
    too_small: str = "pad"            # pad / skip / shrink
    # 新标尺
    bar_enabled: bool = True
    bar_length: float = 0.0           # 0 = 自动取 1/2/5×10ⁿ
    bar_position: str = "br"          # br / bl / tr / tl
    bar_color: str = "auto"           # auto / white / black / #rrggbb
    bar_thickness: int = 0            # 0 = 自动
    bar_ticks: str = "ends6"          # none / ends / ends6
    bar_text: bool = True             # 是否显示文字
    bar_show_unit: bool = True        # 文字里是否带 µm
    bar_font: str = "Arial"
    bar_font_size: int = 0            # 0 = 自动
    bar_margin: int = 0               # 0 = 自动
    bar_text_offset: int = 0          # 0 = 自动
    bar_extra_png: bool = False       # 另存一张透明标尺 PNG（可放进 AI 保持高清）
    export_zoom: int = 1              # 导出放大倍数 1/2/4（标尺始终高清）
    bar_anchor: tuple = None          # 自定义位置：标尺线中心（裁剪后画面的 0~1 比例）
    bar_text_anchor: tuple = None     # 自定义位置：文字中心；None = 跟着线走
    # 导出
    out_format: str = "follow"        # follow / png / tiff / jpg
    # 多通道叠加方式（2026-09-26）：add = 完全叠加（默认，弱通道不会被吃掉）
    #                              max = 老行为（逐分量取最大，谁亮谁覆盖）
    merge_mode: str = "add"
    exp_merge: bool = True
    exp_ch: list = field(default_factory=lambda: [False, False, False])
    frames_mode: str = "current"      # current / all / pick
    frame_pick: str = ""              # 例如 "1,5,12"
    # P0-3：Z 维度单独选择（frames_mode / frame_pick 从此专指时间维度，老工程行为不变）
    z_mode: str = "current"           # current / all / pick
    z_pick: str = ""
    out_subdir: str = "by_group"      # by_group / flat
    out_suffix: str = "_crop"
    out_dir: str = ""                 # 空 = 用 E:\ImageCapture\output
    # 原始位深导出（P0-2）
    exp_raw_single: bool = True       # 单通道原始位深（不烘焙显示区间）
    exp_raw_stack: bool = False       # 多通道栈原始位深
    exp_raw_ome: bool = True          # 写 OME-XML 元数据
    exp_raw_embed: bool = True        # 处理链非空时内嵌可还原的链前数据
    exp_proj: bool = False            # 另出一张 Z 投影图（P1-5）
    group_sync: bool = True           # 组内裁剪框位置一致
    line_um: float = 0.0              # 画线标定：上次填的线长（µm）
    ui_left: bool = True              # 左侧栏是否展开
    ui_right: bool = True             # 右侧栏是否展开
    show_box: bool = True             # 原图显示里是否画裁剪框（False = 只看图）
    settings_version: int = 0         # 参数文件版本（迁移用）

    # ---------- 存盘 ----------
    def to_dict(self):
        return asdict(self)

    def save(self, path=None):
        path = path or paths.SETTINGS_FILE
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, ensure_ascii=False, indent=2)
        return path

    @classmethod
    def load(cls, path=None):
        path = path or paths.SETTINGS_FILE
        st = cls()
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            for k, v in data.items():
                if hasattr(st, k):
                    setattr(st, k, v)
        except Exception:                      # noqa: BLE001
            pass
        st.migrate()
        return st

    def migrate(self):
        """参数文件版本迁移。

        v1 → v2：粗细 / 边距 / 字号 原来是「固定像素」，现在改成「占成品宽的百分比」。
        按 320px 的参考成品宽换算（在 320px 的成品上，新旧看起来一样）。
        """
        if self.settings_version < 2:
            for name in ("bar_thickness", "bar_margin", "bar_font_size"):
                v = getattr(self, name, 0) or 0
                if v > 0:
                    setattr(self, name, int(round(float(v) * 100.0 / 320.0)))
            self.settings_version = 2
        return self


def nice_bar_length(target_um, umpp, min_frac=0.14, max_frac=0.34, width_px=1024):
    """取 1/2/5×10ⁿ 里最接近目标长度的整值（同时保证长度占图宽比例合适）。"""
    best = None
    for exp in range(-4, 6):
        for m in (1, 2, 5):
            v = m * 10 ** exp
            px = v / umpp if umpp else 0
            if px < width_px * min_frac or px > width_px * max_frac:
                continue
            d = abs(v - target_um) if target_um else -v
            if best is None or d < best[0]:
                best = (d, v)
    if best:
        return best[1]
    return target_um or 10.0


def format_um(value):
    """把 µm 数值写成好看的字符串：50、0.5、1000 → 1 mm。"""
    v = float(value)
    if v >= 1000:
        mm = v / 1000.0
        return ("%g" % mm), "mm"
    if v >= 1:
        return ("%g" % v), "µm"
    return ("%g" % v), "µm"
