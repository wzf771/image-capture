# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（onedir）。

用法（在 E:\\ImageCapture 下）：
    runtime\\python\\python.exe -m PyInstaller build\\ImageCapture.spec --noconfirm --clean

产物：dist\\ImageCapture\\ImageCapture.exe
      dist\\ImageCapture\\assets\\  （图标等随包资源）
"""

import glob
import os
import sys

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
APP = os.path.join(ROOT, "app")

# imagecodecs 的编解码器是 68 个 .pyd，PyInstaller 只会捡到 _shared.pyd，
# 结果就是别的电脑上 .oib / .czi / .lif 解不开（用户实测）。这里全部显式收进来。
_IC_DIR = os.path.join(os.path.dirname(sys.executable), "Lib", "site-packages", "imagecodecs")
if not os.path.isdir(_IC_DIR):
    for _base in sys.path:
        _cand = os.path.join(_base, "imagecodecs")
        if os.path.isdir(_cand):
            _IC_DIR = _cand
            break
_IC_BINARIES = [(f, "imagecodecs") for f in glob.glob(os.path.join(_IC_DIR, "*.pyd"))]

block_cipher = None

a = Analysis(
    [os.path.join(APP, "main.py")],
    pathex=[APP],
    binaries=_IC_BINARIES,
    datas=[],
    hiddenimports=[
        "PySide6.QtSvg",
        "PySide6.QtSvgWidgets",
        "ui.theme", "ui.widgets", "ui.main_window", "ui.canvas",
        "ui.magnifying_dock", "ui.liquid_switch", "ui.wake_slider",
        "ui.level_slider", "ui.appstyle", "ui.ortho", "ui.export_dialog",
        "tifffile", "czifile", "oiffile", "liffile", "imagecodecs",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter", "matplotlib", "scipy", "pandas", "pytest",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
        "PySide6.Qt3DCore", "PySide6.QtCharts", "PySide6.QtQuick",
        "PySide6.QtMultimedia", "PySide6.QtBluetooth", "PySide6.QtDesigner",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ImageCapture",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ROOT, "assets", "icon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ImageCapture",
)
