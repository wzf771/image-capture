# -*- coding: utf-8 -*-
"""打包后瘦身：删掉这台机器上用不到的运行库（PyInstaller 会把它们一起收进来）。"""
import os
import shutil
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "dist", "ImageCapture")
INT = os.path.join(ROOT, "_internal")

DROP_DIRS = ["onnxruntime", "shapely", "Shapely", "Shapely.libs", "cv2/data"]
DROP_FILES = [
    "opengl32sw.dll",
    "Qt6Quick.dll", "Qt6QuickControls2.dll", "Qt6QuickLayouts.dll",
    "Qt6QuickTemplates2.dll", "Qt6QuickWidgets.dll", "Qt6Qml.dll",
    "Qt6QmlModels.dll", "Qt6QmlWorkerScript.dll", "Qt6Pdf.dll",
    "Qt6PdfWidgets.dll", "Qt6Network.dll", "Qt6DBus.dll",
]
DROP_PLUGIN_DIRS = ["sqldrivers", "multimedia", "qmltooling", "tls"]


def _size(path):
    if os.path.isfile(path):
        return os.path.getsize(path)
    total = 0
    for base, _dirs, files in os.walk(path):
        for f in files:
            total += os.path.getsize(os.path.join(base, f))
    return total


def main():
    freed = 0
    for name in DROP_DIRS:
        p = os.path.join(INT, name)
        if os.path.exists(p):
            freed += _size(p)
            shutil.rmtree(p, ignore_errors=True)
            print("删目录", name)
    for name in DROP_FILES:
        for base in (INT, os.path.join(INT, "PySide6")):
            p = os.path.join(base, name)
            if os.path.exists(p):
                freed += _size(p)
                os.remove(p)
                print("删文件", os.path.relpath(p, ROOT))
    plug = os.path.join(INT, "PySide6", "plugins")
    for name in DROP_PLUGIN_DIRS:
        p = os.path.join(plug, name)
        if os.path.exists(p):
            freed += _size(p)
            shutil.rmtree(p, ignore_errors=True)
            print("删插件", name)
    total = _size(ROOT)
    print("释放 %.1f MB，剩余 %.1f MB" % (freed / 1048576.0, total / 1048576.0))


if __name__ == "__main__":
    sys.exit(main())
