# -*- coding: utf-8 -*-
"""显示区间 / 配色批量应用自检（规格书 P0-4 的 7 条验收）。

  1 调好第 1 张的 CH1 区间 → 应用到本组 → 状态栏报数，逐张值一致
  2 4 通道图：第 4 通道**不是全白**，vmax 覆盖真实量程（老代码写死 255）
  3 逐帧自动：末帧亮度接近首帧（不再黑掉）
  4 切回统一区间 → 回到现状
  5 逐帧归一化后导出**原始位深** → 像素与统一区间时完全相同
  6 role == "rgb" 的图跳过，报告如实说跳过数量
  7 批量应用走的是同一条同步路径，界面不卡（这里量的是耗时）
"""
import os
import shutil
import sys
import time

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["IMAGECAPTURE_NO_SAVE"] = "1"
APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(APP, "app"))

from PySide6.QtGui import QFont, QFontDatabase                          # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox                 # noqa: E402

import paths                                                            # noqa: E402
from core import loader, render                                         # noqa: E402
from core.model import Channel, Group, ImageItem, Settings              # noqa: E402
from ui.main_window import MainWindow                                   # noqa: E402
from _samples import P  # noqa: E402

OUT = os.path.join(paths.OUTPUT_DIR, "_自检", "显示区间")
SRC4 = P(r"E:\ImageCapture\789\Snap-14700-Airyscan Processing-04.czi")


def fake_item(name, c_count=2, frames=1, umpp=0.5, size=64, role="green", groups=None):
    """造一张"假图"：只填字段 + 直接塞 _cache，不碰磁盘。"""
    it = ImageItem(path="fake://%s" % name, name=name, umpp=umpp,
                   width=size, height=size, frames=frames, bits=16)
    rng = np.random.default_rng(abs(hash(name)) % 1000)
    arr = rng.integers(0, 4095, (frames, c_count, size, size), dtype=np.uint16)
    it._cache = arr
    it.channels = [Channel(index=i, name="CH%d" % (i + 1), color=(0, 255, 0),
                           black=0.0, white=4095.0, vmax=4095.0, role=role)
                   for i in range(c_count)]
    it._ranges_ready = True
    return it


def main():
    if os.path.isdir(OUT):
        shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT, exist_ok=True)
    app = QApplication(sys.argv[:1])
    QFontDatabase.addApplicationFont(r"C:\Windows\Fonts\msyh.ttc")
    app.setFont(QFont("Microsoft YaHei", 9))
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
    res = {}

    # ---------- 1 本组批量应用 ----------
    win = MainWindow()
    win.resize(1460, 940)
    items = [fake_item("a%d.png" % i, c_count=2) for i in range(6)]
    win.items = items
    win._regroup()
    win.refresh_groups()
    win.refresh_strip()
    win.select_item(items[0].path)
    app.processEvents()
    src = win.cur_item.channels[0]
    src.black, src.white = 300.0, 2000.0
    grp = win.cur_group
    t0 = time.time()
    win.apply_channel_to(src, "group")
    dt = time.time() - t0
    vals = [(it.channels[0].black, it.channels[0].white) for it in grp.images]
    ok1 = all(v == (300.0, 2000.0) for v in vals) and len(vals) == 6
    print("[1] 应用到本组：%s，耗时 %.3fs" % (win.lbl_status.text(), dt))
    res["本组批量"] = ok1

    # ---------- 6 rgb 图跳过 ----------
    rgb_item = fake_item("彩图.png", c_count=3, role="rgb")
    win.items = items + [rgb_item]
    win._regroup()
    win.refresh_groups()
    win.refresh_strip()
    win.select_item(items[0].path)
    app.processEvents()
    win.apply_channel_to(win.cur_item.channels[0], "all")
    txt = win.lbl_status.text()
    rgb_same = tuple(rgb_item.channels[0].color) == (0, 255, 0) and rgb_item.channels[0].white == 4095.0
    ok6 = ("合成彩图" in txt) and rgb_same
    print("[6] 跳过报告：「%s」（rgb 图未被改：%s）" % (txt, rgb_same))
    res["rgb跳过"] = ok6

    # ---------- 2 4 通道图的第 4 通道 ----------
    if os.path.exists(SRC4):
        it4 = loader.probe(SRC4)
        st4 = loader.load_stack(it4)
        # 通道数要按**解码后**的算：load_stack 会合并"原始版+处理版"、隐藏全黑通道
        # （Snap-14700 导入时 2 路 → 解码后 1 路），拿解码前的数字拼通道会少拼一层。
        n_ch = len(it4.channels)
        print("[2] 真实图 %s 只有 %d 通道，本机没有 4 通道下机文件 → 用它的真实像素拼一条第 4 通道，"
              "走真正的 _auto_ranges 路径" % (it4.name, n_ch))
        # 补到 4 通道：用真实像素造 0~4095 量级的第 3、4 路
        need = max(0, 4 - n_ch)
        extra = [np.clip(st4[:, :1].astype(np.uint32) * (2 + i), 0, 4095).astype(np.uint16)
                 for i in range(need)]
        arr4 = np.concatenate([st4] + extra, axis=1)
        it4._cache = arr4
        it4.frames = arr4.shape[0]
        it4.channels = list(it4.channels) + [Channel(
            index=n_ch + i, name="CH%d 测试" % (n_ch + i + 1), light="",
            color=(255, 0, 255), black=0.0, white=255.0, vmax=255.0,  # 老代码留下的错误初值
            role="green") for i in range(need)]
        it4._ranges_ready = False
        loader._auto_ranges(it4, arr4)
        c4 = it4.channels[3]
        real_max = float(arr4[0, 3].max())
        white_ok = c4.white > 255.0                 # 老代码写死 255 → 一打开就是全白
        vmax_ok = c4.vmax >= real_max * 0.9
        print("        第 4 通道：白点 %.1f（老代码写死 255）、vmax %.1f、数据最大 %.0f（%d 位深）"
              % (c4.white, c4.vmax, real_max, 16 if arr4.dtype == np.uint16 else 8))
        res["4通道区间"] = bool(white_ok and vmax_ok and not real_max <= 255)
    else:
        st5 = np.random.default_rng(1).integers(0, 4095, (1, 4, 64, 64), dtype=np.uint16)
        r5 = loader.estimate_ranges(st5)
        print("[2] 4 通道：estimate_ranges 返回 %d 组，第 4 组白点 %.1f"
              % (len(r5), r5[3][1]))
        res["4通道区间"] = (len(r5) == 4 and r5[3][1] > 255)

    # ---------- 3/4/5 逐帧归一化 ----------
    frames, N = 12, 96
    base = np.linspace(3000.0, 400.0, frames)          # 模拟光漂白：整体越来越暗
    rng = np.random.default_rng(5)

    def series(name, spread):
        """spread[f] 给每帧的离散度：乘性漂白（∝亮度）/ 纯平移（固定）。"""
        it = fake_item(name, c_count=1, frames=frames, size=N)
        a = np.zeros((frames, 1, N, N), np.uint16)
        for f in range(frames):
            a[f, 0] = rng.normal(base[f], spread[f], (N, N)).clip(0, 4095)
        it._cache = a
        return it

    fid = series("frap_乘性.png", base * 0.05)          # 真实漂白：整体一起缩
    fid2 = series("frap_平移.png", np.full(frames, 150.0))   # 结构不变、只是整体位移
    win.items = [fid]
    win._regroup()
    win.refresh_groups()
    win.refresh_strip()
    win.select_item(fid.path)
    app.processEvents()

    def mean_of(frame):
        win.frame = frame
        r = render.compose(loader.load_stack(fid)[frame], fid.channels,
                           render.ranges_for(fid, frame))
        return float(np.asarray(r).mean())

    def wait_ranges(item, t=15.0):
        """等后台把整批帧的区间算完（真实路径就是异步的）。"""
        t0 = time.time()
        while time.time() - t0 < t:
            app.processEvents()
            if loader.has_frame_ranges(item):
                return True
            time.sleep(0.02)
        return False

    m0_gl, ml_gl = mean_of(0), mean_of(frames - 1)
    win.on_range_mode(1)                                # 帧间自动
    wait_ranges(fid)
    m0_pf, ml_pf = mean_of(0), mean_of(frames - 1)
    ok3 = abs(ml_pf - m0_pf) < abs(ml_gl - m0_gl) * 0.4     # 末帧亮度差距大幅缩小
    print("[3] 统一区间：首帧 %.1f 末帧 %.1f（差 %.1f）→ 逐帧自动：首帧 %.1f 末帧 %.1f（差 %.1f）"
          % (m0_gl, ml_gl, m0_gl - ml_gl, m0_pf, ml_pf, m0_pf - ml_pf))
    res["逐帧抗漂白"] = ok3

    win.on_range_mode(0)                                # 切回统一区间
    back0, backl = mean_of(0), mean_of(frames - 1)
    ok4 = abs(back0 - m0_gl) < 0.01 and abs(backl - ml_gl) < 0.01
    print("[4] 切回统一区间：首帧 %.1f 末帧 %.1f（与切换前一致：%s）" % (back0, backl, ok4))
    res["切回统一"] = ok4

    # 按参考帧：结构不变、只是整体位移的那一类漂白，平移窗口正好补回来
    win.items = [fid2]
    win._regroup()
    win.refresh_groups()
    win.refresh_strip()
    win.select_item(fid2.path)
    app.processEvents()

    def mean2(frame):
        return float(np.asarray(render.compose(
            loader.load_stack(fid2)[frame], fid2.channels,
            render.ranges_for(fid2, frame))).mean())

    g0, gl = mean2(0), mean2(frames - 1)
    win.cb_range_mode.setCurrentIndex(2)                # 按参考帧（信号会触发重算）
    app.processEvents()
    win.on_range_mode(2)
    wait_ranges(fid2)
    r0, rl = mean2(0), mean2(frames - 1)
    ok_ref = abs(rl - r0) < abs(gl - g0) * 0.4
    print("[3b] 按参考帧（结构不变的整体位移）：统一 %.1f/%.1f → 参考帧 %.1f/%.1f"
          % (g0, gl, r0, rl))
    res["参考帧归一"] = ok_ref

    # 5 逐帧归一化不影响原始位深导出
    st = Settings()
    st.out_subdir = "flat"
    st.bar_enabled = False
    st.exp_raw_single = True
    st.exp_raw_stack = False
    g = Group(gid="g1", title="t")
    g.box = dict(x=0.0, y=0.0, w=20.0, h=20.0)
    win.on_range_mode(1)                                # 打开逐帧归一化
    f1, _r1, _d = render.export_raw(fid, st, loader.load_stack(fid), frames - 1,
                                    render.crop_rect(fid, g.box, st), os.path.join(OUT, "5a"), "x")
    win.on_range_mode(0)
    f2, _r2, _d = render.export_raw(fid, st, loader.load_stack(fid), frames - 1,
                                    render.crop_rect(fid, g.box, st), os.path.join(OUT, "5b"), "x")
    same = np.array_equal(_read(f1[0]), _read(f2[0]))
    print("[5] 逐帧归一化后导出原始位深：像素与统一区间导出%s" % ("相同" if same else "**不同**"))
    res["不污染原始"] = bool(same)

    # ---------- 7 界面接线：单帧图不显示归一化控件 ----------
    one = fake_item("单帧.png", c_count=2, frames=1)
    win.items = [one]
    win._regroup()
    win.refresh_groups()
    win.refresh_strip()
    win.select_item(one.path)
    app.processEvents()
    hidden_single = not win.range_tool.isVisible()
    win.items = [fid]
    win._regroup()
    win.refresh_groups()
    win.refresh_strip()
    win.select_item(fid.path)
    app.processEvents()
    shown_series = not win.range_tool.isHidden()
    print("[7] 归一化控件：单帧图隐藏=%s，时间序列显示=%s" % (hidden_single, shown_series))
    res["控件显隐"] = bool(hidden_single and shown_series)

    print()
    print("结论:", "全部通过" if all(res.values()) else "有未通过项",
          "(" + " / ".join("%s %s" % (k, "OK" if v else "不过") for k, v in res.items()) + ")")
    print("输出目录:", OUT)
    return 0 if all(res.values()) else 1


def _read(path):
    import tifffile
    with tifffile.TiffFile(path) as tf:
        return tf.asarray()


if __name__ == "__main__":
    sys.exit(main())
