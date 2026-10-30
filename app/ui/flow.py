# -*- coding: utf-8 -*-
"""自动换行的横向布局：标签一排排排下去，永远不会顶出边框。"""
from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QSizePolicy


class FlowLayout(QLayout):
    def __init__(self, parent=None, margin=0, spacing=6):
        super().__init__(parent)
        self._items = []
        self._last_w = -1
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test=True)

    def setGeometry(self, rect):
        if rect.width() != self._last_w:      # 宽度变了 → 真实行数变了，重新报一次
            self._last_w = rect.width()
            self.invalidate()
        super().setGeometry(rect)
        self._do_layout(rect, test=False)

    def sizeHint(self):
        # 用控件当前实际宽度来算真实行数。不然父布局会拿"最宽的那个元素"当宽度，
        # 把一行能放下的几个按钮算成好几行，卡片里就会空出一大块。
        w = self.geometry().width()
        if w <= 0 and self.parentWidget() is not None:
            w = self.parentWidget().width()
        if w <= 0:
            return self.minimumSize()
        return QSize(w, self.heightForWidth(max(1, w)))

    def minimumSize(self):
        size = QSize()
        for it in self._items:
            size = size.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do_layout(self, rect, test):
        m = self.contentsMargins()
        x = rect.x() + m.left()
        y = rect.y() + m.top()
        line_h = 0
        for it in self._items:
            w = it.sizeHint().width()
            h = it.sizeHint().height()
            if x + w > rect.right() - m.right() and line_h > 0:
                x = rect.x() + m.left()
                y += line_h + self.spacing()
                line_h = 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), it.sizeHint()))
            x += w + self.spacing()
            line_h = max(line_h, h)
        return y + line_h - rect.y() + m.bottom()
