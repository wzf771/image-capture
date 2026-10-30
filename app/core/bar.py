# -*- coding: utf-8 -*-
"""标尺：识别图里已有的标尺（用来算 µm/px），以及画新的标尺。

粗细 / 边距 / 字号这三个参数存的是「占成品宽度的百分比」，
每张图按自己的成品像素单独算，保证不同尺寸的成品图标尺比例一致。
"""
from __future__ import annotations

import os
import re
import unicodedata

# 留空（0）时用的默认比例，按成品宽度的百分比
BAR_THICK_PCT = 5.0        # 标尺线粗细
BAR_MARGIN_PCT = 15.0      # 距图边
BAR_FONT_PCT = 15.5        # 文字大小

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from core.model import FONTS, FONT_DIR, nice_bar_length

UNIT_UM = {"nm": 0.001, "um": 1.0, "µm": 1.0, "μm": 1.0, "mm": 1000.0,
           "cm": 10000.0, "m": 1e6, "pm": 1e-6}
# 数字里可能带千分位（1,000）或欧式小数点（1,5），单位可能是全角（NFKC 归一化后统一）
_NUM = r"\d[\d.,]*\d|\d"
TOKEN = re.compile(r"(%s)\s*(nm|µm|μm|um|mm|cm|pm|m)(?![a-z])" % _NUM, re.I)

_OCR = None


def clean_number(raw: str) -> float:
    """把 OCR 读到的数字文本转成 float，处理千分位与欧式小数点。

    历史坑：老写法 `float(t.replace(",", "."))` 会把标尺上的 **1,000 µm**
    读成 1.0 µm —— 误差 1000 倍，而且是静默的错。规则（规格书 5.4.3）：

      · 同时有 . 和 , → 最后出现的那个当小数点，另一个当千分位
      · 只有 , 且后面恰好 3 位、前面 1~3 位 → 千分位（1,000 → 1000）
      · 只有 , 其它情况 → 小数点（欧式写法 1,5 → 1.5）
      · 只有 . 且后面恰好 3 位 → 仍按小数点（标尺数值不会写成 "1.000"）
    """
    t = (raw or "").strip()
    if not t:
        raise ValueError("空数字")
    has_dot, has_comma = "." in t, "," in t
    if has_dot and has_comma:
        if t.rfind(",") > t.rfind("."):          # 1.234,5 → 欧式
            t = t.replace(".", "").replace(",", ".")
        else:                                    # 1,234.5 → 美式
            t = t.replace(",", "")
    elif has_comma:
        head, _, tail = t.partition(",")
        if len(tail) == 3 and 1 <= len(head) <= 3 and head.isdigit():
            t = t.replace(",", "")               # 1,000 → 1000
        else:
            t = t.replace(",", ".")              # 1,5 → 1.5
    return float(t)


def parse_um_text(text: str):
    """从一段 OCR 文本里抽出 [(数值 µm, 原文)]；全角数字/单位先归一化。"""
    norm = unicodedata.normalize("NFKC", text or "")
    out = []
    for m in TOKEN.finditer(norm.replace(" ", "")):
        try:
            num = clean_number(m.group(1))
        except ValueError:
            continue
        out.append((num * UNIT_UM[m.group(2).lower()], m.group(0)))
    return out


def get_ocr():
    """RapidOCR 本地离线引擎（第一次用的时候才加载）。"""
    global _OCR
    if _OCR is None:
        from rapidocr_onnxruntime import RapidOCR
        _OCR = RapidOCR()
    return _OCR


def ocr_tokens(rgb: np.ndarray, upscale=1):
    """整图 OCR，返回 [(value_um, 原文, (x0,y0,x1,y1), score)]。"""
    img = rgb
    if upscale > 1:
        img = np.asarray(Image.fromarray(rgb).resize(
            (rgb.shape[1] * upscale, rgb.shape[0] * upscale), Image.LANCZOS))
    try:
        res, _elapse = get_ocr()(img)
    except Exception:                            # noqa: BLE001
        return []
    out = []
    for box, text, score in (res or []):
        for value_um, _raw in parse_um_text(text):
            xs = [p[0] / upscale for p in box]
            ys = [p[1] / upscale for p in box]
            out.append((value_um, text, (min(xs), min(ys), max(xs), max(ys)),
                        float(score)))
    return out


def _line_candidates(prof, back=None):
    """在一行里找最长的亮段和暗段（标尺是细线，抗锯齿会断开，所以先竖着取最大）。

    `back` 是背景亮度参考值：默认取这一行的中位数。但标尺**长到占满整行**时
    （比如 1,000 µm 的线占图宽 90%），行中位数就变成"线"的亮度，阈值随之失效，
    表现是"读到数字却量不出线长"。这种情况由 _find_line 传整片背景进来兜底。
    """
    out = {}
    med = float(np.median(prof)) if back is None else float(back)
    hi = float(np.percentile(prof, 99.5))
    lo = float(np.percentile(prof, 0.5))
    for pol, thr in ((1, med + 0.45 * (hi - med)), (-1, med - 0.45 * (med - lo))):
        idx = np.where((prof - thr) * pol > 0)[0]
        if idx.size < 8:
            continue
        runs = np.split(idx, np.where(np.diff(idx) > 3)[0] + 1)
        lg = max(runs, key=len)
        if lg.size < 8:
            continue
        seg = prof[lg]
        out[pol] = dict(x0=int(lg[0]), x1=int(lg[-1]), length=int(lg[-1] - lg[0] + 1),
                        level=float(np.median(seg)), back=med, polarity=pol)
    return out


def _find_line(gray, y0, y1, min_len, xc=None, max_dist=None):
    """在 y0..y1 这几行里找最长的一条横线。

    两轮：先按每行自己的中位数（老口径，绝大多数图走这轮就够），
    一轮都没找到才用「整片背景」再试一次——只补漏，不改老结果。
    """
    h = gray.shape[0]
    yi0, yi1 = max(0, int(y0)), min(h, int(y1))
    gback = (float(np.median(gray[yi0:yi1]))
             if yi1 - yi0 >= 2 else None)
    best = None
    for back in (None, gback):
        if back is None and gback is None:
            break
        got = False
        for y in range(yi0, yi1):
            prof = gray[max(0, y - 2):y + 3].max(axis=0)
            for cand in _line_candidates(prof, back).values():
                if cand["length"] < min_len:
                    continue
                if xc is not None and max_dist is not None:
                    center = (cand["x0"] + cand["x1"]) / 2.0
                    if abs(center - xc) > max_dist:
                        continue
                got = True
                if best is None or cand["length"] > best["length"]:
                    best = dict(cand, y=y)
        if got:
            break
    return best


def _refine(gray, cand):
    """用 50% 阈值把两端点精修到亚像素。"""
    h, w = gray.shape
    x0, x1, y = cand["x0"], cand["x1"], cand["y"]
    rows = gray[max(0, y - 2):min(h, y + 3)]
    prof = rows.max(axis=0) if cand["polarity"] > 0 else rows.min(axis=0)
    thr = (cand["level"] + cand["back"]) / 2.0

    def walk(start, step):
        x = start
        while 0 < x < w - 1:
            a, b = prof[x], prof[x + step]
            if (a - thr) * (b - thr) <= 0 and a != b:
                return x + (thr - a) / (b - a) * step
            x += step
        return float(start)

    xl, xr = walk(x0, -1), walk(x1, 1)
    if xr - xl < 6:
        xl, xr = float(x0), float(x1)
    return dict(x0=float(xl), x1=float(xr), y=int(y), length=float(xr - xl),
                polarity=cand["polarity"], height=1,
                # level/back 原样带出来：_bar_contrast 要用它们算反差分，
                # 少了这两个键，打分里的反差项会恒等于 0（候选排序会失真）。
                level=float(cand["level"]), back=float(cand["back"]),
                contrast=float(abs(cand["level"] - cand["back"])))


def find_bar_under(gray, box, min_len=14):
    """在文字下方那一片里找标尺（人眼也是这么找的）。"""
    h, w = gray.shape
    x0t, y0t, x1t, y1t = box
    th = max(8.0, y1t - y0t)
    tw = max(8.0, x1t - x0t)
    xc = (x0t + x1t) / 2.0
    max_dist = max(2.4 * tw, 0.22 * w)
    # 标尺一般在文字正下方；找不到再往上找一点
    bands = [(int(max(0, y1t + 1)), int(min(h, y1t + max(120.0, 4.5 * th)))),
             (int(max(0, y0t - max(120.0, 4.5 * th))), int(max(0, y0t - 1)))]
    for by0, by1 in bands:
        if by1 - by0 < 2:
            continue
        best = _find_line(gray, by0, by1, min_len, xc=xc, max_dist=max_dist)
        if best is not None:
            return _refine(gray, best)
    return None


def find_bar(gray: np.ndarray, min_len_ratio=0.05):
    """整图找最像标尺的细长条（没有文字可参考时的兜底）。"""
    h, w = gray.shape
    min_len = max(18, int(w * min_len_ratio))
    best = _find_line(gray, 0, h, min_len)
    return _refine(gray, best) if best else None


def _bar_contrast(bar):
    """标尺线与背景的反差（0~1，按数值量级归一，跟位深无关）。"""
    back = float(bar.get("back") or 0.0)
    level = float(bar.get("level") or 0.0)
    scale = max(1.0, abs(back), abs(level))
    return min(1.0, abs(level - back) / scale)


def _cand_score(c):
    """候选打分（规格书 5.4.4）：OCR 置信度 0.55 + 线长占比 0.30 + 反差 0.15。"""
    return (0.55 * min(1.0, float(c.get("ocr") or 0.0))
            + 0.30 * min(1.0, float(c.get("length_ratio") or 0.0) / 0.15)
            + 0.15 * min(1.0, float(c.get("contrast") or 0.0) / 0.5))


def _grade(score):
    return "high" if score >= 0.75 else ("mid" if score >= 0.5 else "low")


def ambiguous(res, tol=0.05):
    """多候选之间差得太多（>tol）→ 需要用户挑一个（规格书 5.4.5）。

    只有一个候选、或候选算出来的 µm/px 几乎一样时返回 False，不打扰用户。
    """
    cs = [c for c in ((res or {}).get("candidates") or []) if c.get("umpp")]
    if len(cs) < 2:
        return False
    lo = min(float(c["umpp"]) for c in cs)
    hi = max(float(c["umpp"]) for c in cs)
    return (hi - lo) / max(1e-12, lo) > tol


def _mk_cand(value_um, text, box, score, bar, w):
    return dict(umpp=float(value_um) / bar["length"], value_um=float(value_um),
                text=text, bar=bar, box=box, ocr=float(score),
                length_ratio=bar["length"] / float(max(1, w)),
                contrast=_bar_contrast(bar))


def _ok_result(top, cands, orientation):
    """成功结果：老字段（ok/umpp/text/bar/box/why）保持不变，另加新字段。"""
    extra = ""
    if orientation == "v":
        extra = "竖标尺："
    elif len(cands) > 1:
        extra = "%d 个候选取最高分：" % len(cands)
    return dict(ok=True, umpp=top["umpp"], value_um=top["value_um"], text=top["text"],
                bar=top["bar"], box=top["box"],
                why=extra + "OCR 读数 + 标尺长度",
                orientation=orientation, confidence=_grade(top["score"]),
                score=top["score"], candidates=cands[:3])


def _swap_box(b):
    """(x0,y0,x1,y1) ↔ (y0,x0,y1,x1)：转置坐标系下的文字框。"""
    return (b[1], b[0], b[3], b[2])


def _detect_oriented(toks, gray, orientation="h"):
    """给定「OCR 结果 + 灰度图」，量标尺并给出候选。

    OCR 只在原图上做一次（文字是横着的、必须原样读），
    要在竖标尺上找线时，调用方传进来的是**转置后的灰度图 + 转置过的文字框**。
    """
    h, w = gray.shape
    cands = []
    for value_um, text, box, score in toks:
        bar = find_bar_under(gray, box)
        if bar is None:
            continue
        umpp = value_um / bar["length"]
        if not (0.002 <= umpp <= 60):
            continue
        cands.append(_mk_cand(value_um, text, box, score, bar, w))
    if cands:
        for c in cands:
            c["score"] = round(_cand_score(c), 3)
        cands.sort(key=lambda c: -c["score"])
        return _ok_result(cands[0], cands, orientation)

    # 兜底 1：整图找条，再看附近有没有刚读到的数字
    bar = find_bar(gray)
    if bar and toks:
        bx = (bar["x0"] + bar["x1"]) / 2.0
        for value_um, text, box, score in toks:
            tx = (box[0] + box[2]) / 2.0
            if abs(tx - bx) < max(0.3 * w, 1.5 * bar["length"]) and box[3] < bar["y"]:
                umpp = value_um / bar["length"]
                if 0.002 <= umpp <= 60:
                    c = _mk_cand(value_um, text, box, score, bar, w)
                    c["score"] = round(_cand_score(c), 3)
                    return dict(ok=True, umpp=c["umpp"], value_um=c["value_um"], text=text,
                                bar=bar, box=box, why="OCR 读数 + 全图标尺",
                                orientation=orientation,
                                confidence=_grade(c["score"]), score=c["score"],
                                candidates=[c])
    if bar:
        return dict(ok=False, umpp=0.0, value_um=0.0, text="", bar=bar, box=None,
                    why="找到标尺 %.0f px，但没读到数字，请手动填写它代表多少 µm"
                        % bar["length"],
                    orientation=orientation, confidence="low", score=0.0, candidates=[])
    if toks:
        value_um, text, box, _score = max(toks, key=lambda t: t[3])
        return dict(ok=False, umpp=0.0, value_um=value_um, text=text, bar=None, box=box,
                    why="读到「%s」，但没量到标尺长度，请手动框一下标尺" % text,
                    orientation=orientation, confidence="low", score=0.0, candidates=[])
    return dict(ok=False, umpp=0.0, value_um=0.0, text="", bar=None, box=None,
                why="没找到标尺也没有数字，请手动框选并填写长度",
                orientation=orientation, confidence="low", score=0.0, candidates=[])


def _untranspose(res, shape):
    """把"转置图上"的结果换算回原图坐标（竖标尺用）。"""
    def flip_box(b):
        return (b[1], b[0], b[3], b[2]) if b else b

    def flip_bar(bar):
        if not bar:
            return bar
        d = dict(bar)
        d["x0"], d["x1"], d["y"] = bar["y"], bar["y"], bar["x0"]   # 横线→竖线
        return d

    out = dict(res)
    out["bar"] = flip_bar(res.get("bar"))
    out["box"] = flip_box(res.get("box"))
    out["candidates"] = [dict(c, bar=flip_bar(c.get("bar")), box=flip_box(c.get("box")))
                         for c in (res.get("candidates") or [])]
    out["orientation"] = "v"
    out["why"] = "竖标尺：" + str(res.get("why") or "")
    return out


def detect_umpp(rgb: np.ndarray, try_both=True):
    """先认字、再在字附近量标尺；横向找不到就把图转置过来再试一次（竖标尺）。

    成本控制：**横向成功就返回，不跑第二轮**——90% 的图是横标尺，
    批量识别的平均耗时基本不变（规格书 5.4.1）。

    关键：**OCR 只在原图上做一次**。早先设想的"整图转置再跑一遍"行不通——
    转置会把文字也转成竖排，OCR 直接读不出来（实测：竖标尺那轮永远失败）。
    正确做法是只转置灰度图与文字框，文字本身仍来自原图 OCR。
    """
    gray = np.asarray(rgb, np.float32)
    if gray.ndim == 3:
        gray = gray.mean(axis=2)
    # 纯色图（黑场/空帧）直接快速失败：OCR 在这种图上很慢，还什么都读不到（规格书 5.5）
    if gray.size and float(gray.std()) < 1.5 and \
            float(np.percentile(gray, 99.5) - np.percentile(gray, 0.5)) < 6.0:
        return dict(ok=False, umpp=0.0, value_um=0.0, text="", bar=None, box=None,
                    why="这张图几乎是纯色，没有标尺可找",
                    orientation="h", confidence="low", score=0.0, candidates=[])
    toks = ocr_tokens(rgb)
    res = _detect_oriented(toks, gray, "h")
    if res.get("ok") or not try_both:
        return res
    toks_t = [(val, txt, _swap_box(box), sc) for val, txt, box, sc in toks]
    v = _detect_oriented(toks_t, gray.T, "v")
    if v.get("ok"):
        return _untranspose(v, gray.shape)
    return res


# ---------------------------------------------------------------- 画新标尺

def _font(name, size):
    path = os.path.join(FONT_DIR, FONTS.get(name, FONTS["Arial"]))
    try:
        return ImageFont.truetype(path, size)
    except Exception:                            # noqa: BLE001
        try:
            return ImageFont.truetype(os.path.join(FONT_DIR, "arial.ttf"), size)
        except Exception:                        # noqa: BLE001
            return ImageFont.load_default(size=size)


def _measure(label, font):
    tmp = ImageDraw.Draw(Image.new("L", (2, 2)))
    b = tmp.textbbox((0, 0), label, font=font)
    return b[2] - b[0], b[3] - b[1], b[0], b[1]


def _layout(W, H, bar_um, umpp, st):
    """按最终图像的像素算标尺几何。"""
    bar_px = max(4.0, float(bar_um) / umpp)
    # 粗细 / 边距 / 字号都是「占成品宽度的百分比」，留空用默认比例。
    # 这样每张图按自己的成品尺寸单独算，成品多大标尺在图里占的比例都一样。
    thick = max(2, int(round(W * float(st.bar_thickness or BAR_THICK_PCT) / 100.0)))
    tick = int(round(max(3, thick * 3)))
    margin = max(3, int(round(W * float(st.bar_margin or BAR_MARGIN_PCT) / 100.0)))
    font_size = max(7, int(round(W * float(st.bar_font_size or BAR_FONT_PCT) / 100.0)))
    font = _font(st.bar_font, max(6, font_size))
    label, tw, th = "", 0, 0
    if st.bar_text:
        label = ("%g" % bar_um) + (" µm" if st.bar_show_unit else "")
        tw, th, _tx, _ty = _measure(label, font)
        while font_size > 6 and tw > W * 0.92:
            font_size -= 1
            font = _font(st.bar_font, font_size)
            tw, th, _tx, _ty = _measure(label, font)
    top = st.bar_position in ("tl", "tr")
    anchor = getattr(st, "bar_anchor", None)
    if st.bar_position == "custom" and anchor:
        cx = float(anchor[0]) * W
        cy = float(anchor[1]) * H
        x0 = cx - bar_px / 2.0
        x1 = x0 + bar_px
        x0 = min(max(x0, 1.0), max(1.0, W - 1 - bar_px))
        x1 = x0 + bar_px
        y = min(max(cy, tick + 1.0), H - 1.0)
        top = y < H / 2.0                      # 在上半部时文字放线下方
    else:
        # 选了"自定义"但这一组还没拖过 → 按右下角默认位置画
        right = st.bar_position in ("br", "tr", "custom")
        top = st.bar_position in ("tl", "tr")
        x1 = float(W - margin) if right else float(margin + bar_px)
        x0 = x1 - bar_px
        if x0 < 1.0:
            x0, x1 = 1.0, 1.0 + bar_px
        if x1 > W - 1:
            x1 = float(W - 1)
            x0 = max(1.0, x1 - bar_px)
        y = float(margin) if top else float(H - margin)
    return dict(x0=x0, x1=x1, y=y, thick=thick, tick=tick, margin=margin, font=font,
                font_size=font_size, label=label, tw=tw, th=th, top=top, bar_px=bar_px)


def _bar_layer(W, H, st, lay, rgb_for_color, ss=4):
    """把标尺单独画在透明图层上：4 倍超采样再缩小，所以不管图片多糊标尺都是锐利的。"""
    x0, x1, y = lay["x0"], lay["x1"], lay["y"]
    thick, tick = lay["thick"], lay["tick"]
    # 文字紧贴标尺：间距只跟字号有关，跟刻度线长度无关（刻度在线下方，不影响上方）
    gap = int(st.bar_text_offset or max(2, round(lay["font_size"] * 0.25)))
    t_anchor = getattr(st, "bar_text_anchor", None)
    if st.bar_position == "custom" and t_anchor:
        tx = float(t_anchor[0]) * W - lay["tw"] / 2.0
        ty = float(t_anchor[1]) * H - lay["th"] / 2.0
    else:
        # 默认：文字在标尺横条的正上方、居中；上方没地方才放到下面
        tx = x0 + (x1 - x0) / 2.0 - lay["tw"] / 2.0
        ty = y - gap - lay["th"] - 1
        if ty < 1:
            ty = y + tick + gap
    # 别让文字跑出画面
    tx = min(max(tx, 1.0), max(1.0, W - lay["tw"] - 1.0))
    ty = min(max(ty, 1.0), max(1.0, H - lay["th"] - 1.0))
    pad = 6
    xs = [x0 - thick, x1 + thick]
    ys = [y - thick, y + tick + 1]
    if lay["label"]:
        xs += [tx, tx + lay["tw"]]
        ys += [ty, ty + lay["th"]]
    rx0 = max(0, int(min(xs) - pad))
    rx1 = min(W, int(max(xs) + pad) + 1)
    ry0 = max(0, int(min(ys) - pad))
    ry1 = min(H, int(max(ys) + pad) + 1)
    if rx1 - rx0 < 2 or ry1 - ry0 < 2:
        return None, (0, 0)
    color = choose_color(rgb_for_color, rx0, ry0, rx1, ry1, st.bar_color)
    rgba = tuple(color) + (255,)
    layer = Image.new("RGBA", ((rx1 - rx0) * ss, (ry1 - ry0) * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    def PX(v):
        return (v - rx0) * ss

    def PY(v):
        return (v - ry0) * ss

    d.rectangle([PX(x0), PY(y - thick / 2.0), PX(x1), PY(y + thick / 2.0)], fill=rgba)
    if st.bar_ticks in ("ends", "ends6"):
        d.rectangle([PX(x0 - thick / 2.0), PY(y - thick / 2.0),
                     PX(x0 + thick / 2.0), PY(y + tick)], fill=rgba)
        d.rectangle([PX(x1 - thick / 2.0), PY(y - thick / 2.0),
                     PX(x1 + thick / 2.0), PY(y + tick)], fill=rgba)
        if st.bar_ticks == "ends6":
            for i in range(1, 6):
                xm = x0 + (x1 - x0) * i / 6.0
                d.rectangle([PX(xm - thick / 2.0), PY(y - thick / 2.0),
                             PX(xm + thick / 2.0), PY(y + tick * 0.55)], fill=rgba)
    if lay["label"]:
        big = _font(st.bar_font, max(6, int(round(lay["font_size"] * ss))))
        b = d.textbbox((0, 0), lay["label"], font=big)
        d.text((PX(tx) - b[0], PY(ty) - b[1]), lay["label"], font=big, fill=rgba)
    return layer.resize((rx1 - rx0, ry1 - ry0), Image.LANCZOS), (rx0, ry0)


def choose_color(img: np.ndarray, x0, y0, x1, y1, mode="auto"):
    if mode == "white":
        return (255, 255, 255)
    if mode == "black":
        return (0, 0, 0)
    if mode and mode.startswith("#") and len(mode) == 7:
        try:
            return tuple(int(mode[i:i + 2], 16) for i in (1, 3, 5))
        except ValueError:
            pass
    box = img[max(0, y0):max(1, y1), max(0, x0):max(1, x1)]
    lum = float(box.mean()) if box.size else 128.0
    return (255, 255, 255) if lum < 128 else (0, 0, 0)


def bar_length_for(W, umpp, st, bar_um=None):
    """这次到底画多长的标尺（µm）。"""
    if bar_um:
        return float(bar_um)
    if st.bar_length:
        return float(st.bar_length)
    return nice_bar_length(0.14 * W * umpp, umpp, width_px=W)


def bar_layer_only(W, H, umpp, st, bar_um=None, color=(255, 255, 255), probe=None):
    """只出标尺本身（透明背景），可以丢进 AI 里当高清标尺用，放大也不糊。"""
    length_um = bar_length_for(W, umpp, st, bar_um)
    lay = _layout(W, H, length_um, umpp, st)
    if probe is None:
        probe = np.zeros((H, W, 3), np.uint8)
    layer, (rx0, ry0) = _bar_layer(W, H, st, lay, probe, ss=4)
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if layer is not None:
        arr = np.array(layer)
        if color is not None:
            arr[..., 0], arr[..., 1], arr[..., 2] = color
        out.alpha_composite(Image.fromarray(arr), (rx0, ry0))
    return out, length_um, lay


def draw_bar(rgb: np.ndarray, umpp: float, st, bar_um=None) -> np.ndarray:
    """在图上画新标尺：几何按最终像素算，绘制用 4 倍超采样，所以图片糊标尺也锐利。"""
    if not st.bar_enabled or umpp <= 0:
        return rgb
    H, W = rgb.shape[:2]
    length_um = bar_length_for(W, umpp, st, bar_um)
    lay = _layout(W, H, length_um, umpp, st)
    layer, (rx0, ry0) = _bar_layer(W, H, st, lay, rgb, ss=4)
    if layer is None:
        return rgb
    img = Image.fromarray(rgb).convert("RGBA")
    img.alpha_composite(layer, (rx0, ry0))
    return np.asarray(img.convert("RGB"))
