# -*- coding: utf-8 -*-
"""用主题色重画标准对话框图标（问号/感叹号/信息），替掉系统那套蓝色徽章。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QProxyStyle, QStyle

from ui import theme

_GLYPH = {
    QStyle.SP_MessageBoxQuestion: "?",
    QStyle.SP_MessageBoxInformation: "i",
    QStyle.SP_MessageBoxWarning: "!",
    QStyle.SP_MessageBoxCritical: "!",
}
_COLOR = {
    QStyle.SP_MessageBoxCritical: "#B4533F",
    QStyle.SP_MessageBoxWarning: "#B07A3C",
}


def _pixmap(standard, size=32):
    text = _GLYPH.get(standard)
    if not text:
        return None
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(_COLOR.get(standard, theme.PRIMARY)))
    p.drawEllipse(1, 1, size * 2 - 2, size * 2 - 2)
    f = QFont(theme.FONT_CJK)
    f.setPixelSize(int(size * 1.15))
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor("#FFFFFF"))
    p.drawText(pm.rect(), Qt.AlignCenter, text)
    p.end()
    pm.setDevicePixelRatio(2.0)
    return pm


class ThemedStyle(QProxyStyle):
    """只改标准图标，其他一律沿用系统样式。"""

    def standardIcon(self, standardIcon, option=None, widget=None):  # noqa: N802
        pm = _pixmap(standardIcon)
        if pm is not None:
            return QIcon(pm)
        return super().standardIcon(standardIcon, option, widget)
