# -*- coding: utf-8 -*-
"""虚拟导出检查（临时）：三种导出模式 + 2/3/4 通道的变体数量是否正确。

跑完自动删掉输出目录。
"""
import os
import shutil
import sys

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(APP, "app"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"

import paths
from core import loader, render
from core.model import Channel, Group, ImageItem, Settings
from ui.worker import job_export

LIF = r"C:\Users\王卓\Documents\WeChat Files\wxid_9zfozaq4ukdo21\FileStorage\File\2026-11\LYX-123.lif"
OUT = os.path.join(paths.OUTPUT_DIR, "_虚拟导出检查")
FAIL = []


def check(cond, msg):
    print(("  OK   " if cond else "  FAIL ") + msg, flush=True)
    if not cond:
        FAIL.append(msg)


def fake_item(n_ch):
    """只用来测 channel_variants / variant_count 的计数逻辑。"""
    it = ImageItem(path="x", name="fake")
    it.channels = [Channel(index=i, name="C%d" % (i + 1), role="gray")
                   for i in range(n_ch)]
    return it


def modes():
    return [
        ("merge", dict(exp_merge=True, exp_ch=[False] * 4)),
        ("channels", dict(exp_merge=False, exp_ch=[True] * 4)),
        ("both", dict(exp_merge=True, exp_ch=[True] * 4)),
    ]


def main():
    if os.path.isdir(OUT):
        shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT, exist_ok=True)

    # ---------- 1) 计数逻辑：2 / 3 / 4 通道
    print("[1] 变体计数（假 item）")
    for n in (2, 3, 4):
        it = fake_item(n)
        for mode, kw in modes():
            st = Settings()
            for k, v in kw.items():
                setattr(st, k, v)
            got = len(render.channel_variants(it, st))
            want = render.variant_count(it, st)
            expect = (1 if st.exp_merge else 0) + (n if st.exp_ch[0] else 0)
            check(got == expect and want == expect,
                  "%d 通道 / %s → %d 个文件（channel_variants=%d, variant_count=%d）"
                  % (n, mode, expect, got, want))

    # ---------- 2) 真导出：4 通道 LIF，三种模式各导一帧
    print("\n[2] 真导出（LYX-123.lif 第 1 组第 1 张，1 帧，4 通道）")
    if not os.path.exists(LIF):
        print("  跳过：找不到测试文件")
    else:
        from ui import worker
        items = worker.job_probe([LIF])
        it = items[0]
        n_ch = len(it.channels)
        print("  这张图实际通道数 = %d，名称 = %s"
              % (n_ch, [c.name for c in it.channels]))
        g = Group(gid="g1", title="虚拟组")
        g.images = [it]
        f = it.field_um() or 100.0
        g.box = dict(x=max(0.0, (f - 20) / 2), y=max(0.0, (f - 20) / 2), w=20.0, h=20.0)

        for mode, kw in modes():
            n_ch = len(it.channels)         # 全黑通道会被 compose 隐藏掉，按导出时的实际数量算
            sub = os.path.join(OUT, mode)
            os.makedirs(sub, exist_ok=True)
            st = Settings()
            for k, v in kw.items():
                setattr(st, k, v)
            st.out_format = "png"
            st.exp_raw_single = False      # 这里只验彩图变体，原始位深另算
            st.exp_raw_stack = False
            st.out_suffix = "_crop"
            st.frames_mode = "current"
            st.z_mode = "current"
            rows = job_export([(it, g, [0])], st, sub, report=lambda *_a: None)
            files = []
            for root, _d, fs in os.walk(sub):
                for fn in fs:
                    files.append(os.path.relpath(os.path.join(root, fn), sub))
            print("  %-9s 出 %d 个文件：%s" % (mode, len(files), sorted(files)))
            want = (1 if st.exp_merge else 0) + (n_ch if st.exp_ch[0] else 0)
            check(len(files) == want, "%s 模式文件数 %d == 期望 %d" % (mode, len(files), want))
            check(all(os.path.getsize(os.path.join(sub, fn)) > 0 for fn in files),
                  "%s 模式文件都非空" % mode)
            if mode == "channels":
                check(len(files) == n_ch, "逐通道模式恰好 %d 个（不再写死 3）" % n_ch)

    print("\n结论：", "全部通过" if not FAIL else ("失败 %d 项" % len(FAIL)))
    for f in FAIL:
        print("  -", f)
    shutil.rmtree(OUT, ignore_errors=True)
    print("已删除临时输出:", OUT, "存在=", os.path.exists(OUT))
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
