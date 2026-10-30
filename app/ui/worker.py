# -*- coding: utf-8 -*-
"""后台任务：探测元数据、自动标定、批量导出、缩略图。"""
from __future__ import annotations

import os

from PySide6.QtCore import QThread, Signal

from core import bar as bar_mod
from core import loader, render


class FnWorker(QThread):
    progress = Signal(int, int, str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, *args, parent=None):
        super().__init__(parent)
        self.fn = fn
        self.args = args

    def _report(self, i, total, msg=""):
        self.progress.emit(int(i), int(total), str(msg))

    def run(self):
        try:
            self.done.emit(self.fn(*self.args, report=self._report))
        except Exception as exc:                 # noqa: BLE001
            import traceback
            traceback.print_exc()
            self.failed.emit(str(exc))


def job_probe(paths_list, report=None):
    items = []
    total = max(1, len(paths_list))
    for i, p in enumerate(paths_list):
        if report:
            report(i, total, os.path.basename(p))
        items.extend(loader.probe_all(p))        # 一个徕卡文件可能出好几个序列
    return items


def job_calibrate(items, report=None):
    """对没有标定的图跑一遍：标尺识别 + OCR。"""
    todo = [it for it in items if it.umpp <= 0]
    total = max(1, len(todo))
    for i, it in enumerate(todo):
        if report:
            report(i, total, it.name)
        try:
            rgb, factor = render.quick_rgb(it)
            res = bar_mod.detect_umpp(rgb)
            it.detect = res              # 留给界面画"识别到哪根线了"（规格书 5.4.6）
            if res.get("ok"):
                it.umpp = res["umpp"] / factor
                # 置信度分级文案（规格书 5.4.4）：mid 提醒用户核一眼
                if res.get("confidence") == "mid":
                    it.calib = "标尺识别（读到 %s，建议核对）" % res.get("text", "")
                else:
                    it.calib = "标尺识别 + OCR（读到 %s）" % res.get("text", "")
            else:
                it.umpp = 0.0
                it.calib = "待人工确认：" + res.get("why", "识别失败")
        except Exception as exc:                 # noqa: BLE001
            it.umpp = 0.0
            it.detect = None
            it.calib = "识别失败：%s" % exc
    if report:
        report(total, total, "完成")
    return items


def job_export(jobs, st, out_root, report=None):
    """jobs: [(item, group, [帧号…]), …]"""
    rows = []
    total = max(1, sum(len(frames) for _i, _g, frames in jobs))
    done = 0
    for item, group, frames in jobs:
        for fr in frames:
            if report:
                report(done, total, "%s 第 %d 帧" % (item.name, fr + 1))
            try:
                _files, row = render.export_item(item, group, st, frame=fr, out_root=out_root)
            except Exception as exc:             # noqa: BLE001
                row = dict(group=group.title, name=item.name, frame=fr + 1,
                           note="失败：%s" % exc, files=0)
            rows.append(row)
            done += 1
            if report:
                report(done, total, item.name)
        loader.release(item)
    return rows


class ThumbWorker(QThread):
    ready = Signal(str, str)

    def __init__(self, items, parent=None, planes=None, mode="add"):
        super().__init__(parent)
        self.items = list(items)
        self.planes = planes
        self.mode = mode                      # 多通道叠加方式（跟主界面的设置一致）
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        for it in self.items:
            if self._stop:
                return
            try:
                small = self.planes if (self.planes is not None and len(self.items) == 1) else None
                path = render.make_thumb(it, 256, planes=small, mode=self.mode)
            except Exception:                    # noqa: BLE001
                continue
            self.ready.emit(it.path, path)
        self.ready.emit("", "")
