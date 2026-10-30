# -*- coding: utf-8 -*-
"""样本库根目录。

公开仓库里不含实验图片。跑自检前先准备一组样本，
用环境变量 IMAGECAPTURE_SAMPLES 指向样本根目录（默认 E:\\XY）。
"""
import os

ROOT = os.environ.get("IMAGECAPTURE_SAMPLES", r"E:\XY")


CZI_DIR = os.environ.get("IMAGECAPTURE_SAMPLES_CZI_DIR", r"E:\ImageCapture\789")


def P(path: str) -> str:
    """把写死的样本路径换成环境变量指定的根目录。"""
    if path.startswith(r"E:\XY"):
        return ROOT + path[len(r"E:\XY"):]
    if path.startswith(r"E:\ImageCapture\789"):
        return CZI_DIR + path[len(r"E:\ImageCapture\789"):]
    return path
