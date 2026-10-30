r"""集中管理程序用到的路径：全部相对程序目录，整体搬走不用改代码。

目录约定：
  E:\ImageCapture\app\       代码
  E:\ImageCapture\runtime\   便携 Python 与依赖库
  E:\ImageCapture\config\    参数配置
  E:\ImageCapture\cache\     缩略图缓存（可随时删）
  E:\ImageCapture\output\    导出的成品图与报告
  E:\ImageCapture\logs\      运行日志
"""
import os

APP_NAME = "Image capture"

APP_DIR = os.path.dirname(os.path.abspath(__file__))     # …\ImageCapture\app
ROOT = os.path.dirname(APP_DIR)                          # …\ImageCapture
RUNTIME_DIR = os.path.join(ROOT, "runtime")
CONFIG_DIR = os.path.join(ROOT, "config")
CACHE_DIR = os.path.join(ROOT, "cache")
OUTPUT_DIR = os.path.join(ROOT, "output")
LOG_DIR = os.path.join(ROOT, "logs")
ASSETS_DIR = os.path.join(ROOT, "assets")

SETTINGS_FILE = os.path.join(CONFIG_DIR, "settings.json")
LOG_FILE = os.path.join(LOG_DIR, "app.log")
THUMB_DIR = os.path.join(CACHE_DIR, "thumbs")
# 工程文件相关（P0-1）
AUTOSAVE_FILE = os.path.join(CONFIG_DIR, "autosave.icproj")
RECENT_FILE = os.path.join(CONFIG_DIR, "recent.json")
LAST_EXIT_FILE = os.path.join(CONFIG_DIR, "last_exit.txt")


def ensure_dirs():
    for d in (CONFIG_DIR, CACHE_DIR, OUTPUT_DIR, LOG_DIR, ASSETS_DIR, THUMB_DIR):
        os.makedirs(d, exist_ok=True)
