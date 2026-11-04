# -*- coding: utf-8 -*-
"""界面主题：暖砂底 + 石墨琥珀强调（2026-11-02 第三版配色），扁平、无卡片边框。

设计规则（与 ui-ux-pro-max 的 Minimalism & Swiss 结果一致）：
  · 整个窗口一个底色，层次只靠「明度差 + 1px 细线 + 留白」，不用卡片描边和阴影
  · 只有 ACCENT 一个有彩色，其余全是灰阶
  · 圆角只留在控件上（6/8px），面板容器一律直角
"""

# —— 底色（明度从外到内递增）——
BG = "#F0EEE9"            # 窗口底
STAGE = "#F7F5F0"         # 画布台面
CARD = "#FFFFFF"          # 纸面 / 输入框
SOFT = "transparent"      # 卡片面：扁平化后不再铺底色
FIELD = "#E8E5DE"         # 输入框、分段控件、次级按钮的底
FIELD_HOVER = "#DFDBD2"

# —— 文字 ——
TEXT = "#000000"
INK2 = "#000000"
MUTED = "#000000"

# —— 线 ——
LINE = "rgba(33,30,24,0.10)"
LINE_SOFT = "rgba(33,30,24,0.06)"
BORDER_MOD = "rgba(33,30,24,0.10)"

# —— 唯一强调色 ——
PRIMARY = "#A8642A"
PRIMARY_DARK = "#8E5322"
PRIMARY_WEAK = "rgba(168,100,42,0.10)"
PRIMARY_WEAK_2 = "rgba(168,100,42,0.16)"
ON_PRIMARY = "#FFFFFF"
CORAL = "#C4442A"         # 只用于危险/错误
MINT = "#2B7649"          # 只用于成功/进度

# —— 兼容旧名字（有些模块还在 import）——
RAIL = BG
RAIL_2 = FIELD
BG_DEEP = STAGE
GRAD_A = FIELD
GRAD_B = FIELD
HEAD_TEXT = TEXT
HEAD_HINT = MUTED
RING_ON = PRIMARY
RING_OFF = MUTED

R_WIN = 0
R_CARD = 8
R_CTRL = 6

# 中文用微软雅黑（图一那种黑体），英文与数字用 Times New Roman
FONT_LATIN = "Times New Roman"
FONT_CJK = "Microsoft YaHei"
FONT = "'Times New Roman','Microsoft YaHei','Segoe UI',sans-serif"


def ui_font(px=12.5, weight=None, bold=False):
    """统一字体入口：西文走 Times New Roman，中文由 Qt 自动回退到微软雅黑。"""
    from PySide6.QtGui import QFont
    f = QFont()
    f.setFamilies([FONT_LATIN, FONT_CJK, "Segoe UI"])   # 逐字符回退
    f.setPixelSize(int(round(px)))
    if bold:
        f.setBold(True)
    if weight is not None:
        f.setWeight(weight)
    return f


# 字号只留三档，彼此相差 ≤2.5px
SIZE_CAP = 11
SIZE_BODY = 12.5
SIZE_TITLE = 13.5


def qss():
    return f"""
    QWidget {{ background: {BG}; color: {TEXT};
              font-family: {FONT}; font-size: 12.5px; }}
    QMainWindow, QDialog {{ background: {BG}; }}
    QLabel {{ background: transparent; }}
    QLabel#appTitle {{ font-size: 13.5px; font-weight: 600; color: {TEXT}; }}
    QLabel#titleGroup {{ font-size: 12.5px; font-weight: 700; color: {TEXT}; }}
    QLabel#muted {{ color: {TEXT}; font-size: 11px; }}

    /* ── 窗口外壳 ─────────────────────────────────────────── */
    QFrame#titlebar {{ background: {BG}; border: none; }}
    QFrame#titlebar QLabel {{ color: {TEXT}; }}
    QPushButton#winBtn {{ background: transparent; border: none; border-radius: 6px;
        padding: 0; }}
    QPushButton#winBtn:hover {{ background: {FIELD}; }}
    QPushButton#winClose:hover {{ background: {CORAL}; color: #FFFFFF; }}

    QFrame#bottombar {{ background: transparent; border: none;
                       border-top: 1px solid {LINE}; }}
    QFrame#railBrand {{ background: transparent; border: none; }}


    /* ── 二级界面：菜单 / 对话框 / 弹层 / 树表 ───────────────── */
    QMenu {{ background: {STAGE}; border: 1px solid {LINE}; padding: 6px; }}
    QMenu::item {{ padding: 7px 26px 7px 12px; border-radius: 5px; color: {TEXT}; }}
    QMenu::item:selected {{ background: {FIELD}; }}
    QMenu::item:disabled {{ color: #A39A8C; }}
    QMenu::separator {{ height: 1px; background: {LINE}; margin: 6px 10px; }}
    QMenu::right-arrow {{ width: 10px; height: 10px; }}

    QDialog, QMessageBox {{ background: {BG}; }}
    QDialog QLabel, QMessageBox QLabel {{ color: {TEXT}; background: transparent; }}
    QDialog QScrollArea, QDialog QWidget#qt_scrollarea_viewport {{ background: transparent; }}
    QMessageBox QPushButton, QDialog QPushButton {{
        background: {FIELD}; border: 1px solid {LINE}; border-radius: 6px;
        padding: 5px 16px; color: {TEXT}; min-width: 64px; }}
    QMessageBox QPushButton:hover, QDialog QPushButton:hover {{ background: {FIELD_HOVER}; }}

    QComboBox QAbstractItemView {{
        background: {STAGE}; border: 1px solid {LINE}; padding: 4px;
        selection-background-color: {FIELD}; selection-color: {TEXT};
        outline: none; }}

    QTreeWidget, QTreeView, QListView {{
        background: {STAGE}; border: 1px solid {LINE}; border-radius: 6px;
        outline: none; alternate-background-color: {STAGE}; }}
    QTreeWidget::item, QTreeView::item {{ padding: 4px 2px; border-radius: 4px; }}
    QTreeWidget::item:selected, QTreeView::item:selected {{
        background: {FIELD}; color: {TEXT}; }}
    QHeaderView::section {{
        background: {FIELD}; border: none; border-bottom: 1px solid {LINE};
        padding: 6px 8px; color: {TEXT}; }}

    /* ── 左栏：和主区同底色，只用一条细线分隔 ───────────────── */
    QFrame#rail {{ background: {BG}; border: none;
                   border-right: 1px solid {LINE}; border-radius: 0; }}
    QFrame#rail QLabel {{ color: {TEXT}; }}
    QFrame#rail QLabel#muted {{ color: {TEXT}; }}
    QLabel#railCap {{ color: {TEXT}; font-size: 11px; letter-spacing: 1px; }}
    QLabel#railSub {{ color: {TEXT}; font-size: 11px; }}

    QFrame#railCard {{ background: {FIELD}; border: none; border-radius: 8px; }}
    QFrame#railCard QLabel {{ color: {TEXT}; }}
    QFrame#railCard QPushButton {{ background: transparent; color: {TEXT};
        border: 1px solid {LINE}; border-radius: 6px; font-weight: 400; }}
    QFrame#railCard QPushButton:hover {{ background: {CARD}; border-color: {LINE}; }}

    QWidget#leftWrap {{ background: {BG}; }}
    QWidget#groupPanel {{ background: transparent; border: none; }}
    /* 右侧工具栏与画布共用一块白底；只在左边画一条分界线 */
    QFrame#rightWrap {{ background: transparent; border: none;
                        border-left: 1px solid {LINE}; }}

    QPushButton#fileRow {{ background: transparent; border: 1px solid transparent;
        border-radius: 4px; padding: 3px 5px; color: {TEXT}; font-size: 12px;
        text-align: left; }}
    QPushButton#fileRow:hover {{ background: {FIELD}; }}
    QPushButton#fileRow[active="true"] {{ background: {PRIMARY_WEAK}; color: {TEXT};
        font-weight: 600; }}

    QFrame#segWrap {{ background: {FIELD}; border-radius: 16px; }}
    QWidget#segThumb {{ background: {CARD}; border-radius: 13px;
                        border: 1px solid rgba(33,30,24,0.06); }}
    QPushButton#segTab {{ background: transparent; border: none; border-radius: 13px;
        padding: 4px 9px; color: {TEXT}; font-size: 12.5px; }}
    QPushButton#segTab:hover {{ color: {TEXT}; }}
    QPushButton#segTab[on="true"] {{ color: {TEXT}; font-weight: 600; }}

    QPushButton#collapseBtn {{ background: transparent; border: none; border-radius: 6px;
        padding: 0; color: {TEXT}; font-size: 14px; font-weight: 600; }}
    QPushButton#collapseBtn:hover {{ background: {FIELD}; color: {TEXT}; }}
    QPushButton#rightStrip {{ background: {FIELD}; border: none;
        border-left: 1px solid {LINE}; border-radius: 0;
        color: {TEXT}; font-size: 12.5px; padding: 8px 0; }}
    QPushButton#rightStrip:hover {{ background: {FIELD_HOVER}; color: {TEXT}; }}

    /* ── 右栏标签条 ────────────────────────────────────────── */
    QFrame#tabbar {{ background: transparent; border: none;
                     border-bottom: 1px solid {LINE}; }}
    QPushButton#inspTab {{ background: transparent; border: none; border-radius: 5px;
        padding: 5px 9px; color: {TEXT}; font-size: 12.5px; }}
    QPushButton#inspTab:hover {{ background: {FIELD}; color: {TEXT}; }}
    QPushButton#inspTab:checked {{ background: {CARD}; color: {TEXT}; font-weight: 600;
        border: 1px solid {LINE}; }}

    /* ── 分组卡：扁平，选中才用强调色弱底 ──────────────────── */
    QFrame#groupCard {{ background: transparent; border: none; border-radius: 8px; }}
    QFrame#groupCard:hover {{ background: {FIELD}; }}
    QFrame#groupCard QLabel {{ color: {TEXT}; }}
    QFrame#groupCard QLabel#muted {{ color: {TEXT}; }}
    QFrame#groupCard[active="true"] {{ background: {PRIMARY_WEAK}; }}
    QFrame#groupCard[active="true"] QLabel {{ color: {TEXT}; font-weight: 600; }}
    QFrame#groupCard[active="true"] QLabel#muted {{ color: {TEXT}; }}

    /* ── 画布台面 ─────────────────────────────────────────── */
    /* 画布 + 右栏共用的大底板 */
    QFrame#workspace {{ background: {STAGE}; border: none; border-radius: 10px; }}
    QFrame#stage {{ background: transparent; border: none; }}
    /* 白底板上的一切容器都透明，别用全局 QWidget 的底色盖住它 */
    QWidget#centerCol, QWidget#rightBody, QFrame#tabbar,
    QFrame#rightWrap QScrollArea, QFrame#rightWrap QScrollArea > QWidget,
    QFrame#rightWrap QScrollArea > QWidget#qt_scrollarea_viewport,
    QWidget#rightWrap QWidget#rightBody {{ background: transparent; }}

    /* ── 通用面：扁平化后不留边框和底色 ───────────────────── */
    QFrame#card {{ background: transparent; border: none; border-radius: 0; }}
    /* 白板底部这一带：里面所有普通容器一律透明，免得全局 QWidget 的底色切出灰带 */
    QFrame#chipCard, QFrame#chipCard QWidget {{ background: transparent; }}
    /* 真正的输入控件要给回底色（同特异性、写在后面，所以它赢） */
    QFrame#chipCard QComboBox, QFrame#chipCard QLineEdit,
    QFrame#chipCard QSpinBox, QFrame#chipCard QDoubleSpinBox {{
        background: {FIELD}; border: 1px solid {LINE}; border-radius: 6px; }}
    /* 画布下方那两行：跟上方同为白底，只在两者之间画一条分界线 */
    QFrame#chipCard {{ background: transparent; border: none;
                       border-top: 1px solid {LINE}; border-radius: 0; }}
    QFrame#module {{ background: transparent; border: none; border-radius: 0; }}
    QFrame#module[expanded="true"] {{ background: transparent; border: none; }}
    QFrame#module[expanded="true"][hover="true"] {{ border: none; }}
    QFrame#modHead {{ background: transparent; border-bottom: 1px solid {LINE_SOFT}; }}
    QFrame#module[expanded="true"] QFrame#modHead {{ background: transparent;
        border-top-left-radius: 0; border-top-right-radius: 0;
        border-bottom-left-radius: 0; border-bottom-right-radius: 0;
        border-bottom: 1px solid {LINE_SOFT}; }}
    QFrame#module[expanded="true"] QLabel#cardTitle {{ color: {TEXT}; }}
    QFrame#module[expanded="true"] QLabel#cardHint {{ color: {TEXT}; }}
    QLabel#cardHint {{ color: {TEXT}; font-size: 11px; }}
    QLabel#cardTitle {{ font-weight: 600; color: {TEXT}; font-size: 12.5px; }}

    /* ── 缩略图 ───────────────────────────────────────────── */
    QFrame#thumb {{ background: transparent; border: 1px solid transparent;
                    border-radius: 8px; }}
    QFrame#thumb:hover {{ background: {FIELD}; }}
    QFrame#thumb[active="true"] {{ background: {PRIMARY_WEAK};
        border: 1px solid {PRIMARY_WEAK_2}; }}
    QLabel#thumbPic {{ background: {FIELD}; border-radius: 6px; }}
    QLabel#thumbName {{ font-size: 11px; font-weight: 600; }}

    /* ── 按钮：扁平，只有悬停时给一层浅底 ──────────────────── */
    QPushButton {{ background: transparent; border: 1px solid {LINE};
                  border-radius: {R_CTRL}px; padding: 6px 12px; color: {TEXT}; }}
    QPushButton:hover {{ background: {FIELD}; }}
    QPushButton:pressed {{ background: {FIELD_HOVER}; }}
    QPushButton:disabled {{ color: #A39A8C; border-color: {LINE_SOFT}; }}
    QPushButton#primary {{ background: {PRIMARY}; border: none; color: {ON_PRIMARY};
                          font-weight: 600; padding: 8px 18px; }}
    QPushButton#primary:hover {{ background: {PRIMARY_DARK}; }}
    QPushButton#seg {{ background: transparent; color: {TEXT}; border: none; }}
    QPushButton#seg:checked {{ background: {CARD}; color: {TEXT};
                              border: 1px solid {LINE}; font-weight: 600; }}
    QPushButton#mini {{ padding: 3px 8px; font-size: 11px; border-radius: 5px; }}
    QPushButton#pill {{ background: {FIELD}; border: none; border-radius: 6px;
                        padding: 6px 11px; color: {TEXT}; font-size: 12.5px; }}
    QPushButton#pill:hover {{ background: {FIELD_HOVER}; }}
    QPushButton#pill:checked {{ background: {PRIMARY}; color: {ON_PRIMARY}; font-weight: 600; }}
    QPushButton#softField {{ background: {FIELD}; border: 1px solid transparent;
                            border-radius: {R_CTRL}px; padding: 7px 11px; color: {TEXT};
                            font-size: 12.5px; font-weight: 400; text-align: left; }}
    QPushButton#softField:hover {{ border-color: {LINE}; }}

    /* ── 输入 ─────────────────────────────────────────────── */
    QLineEdit#field, QComboBox#field, QSpinBox#field, QDoubleSpinBox#field {{
        background: {FIELD}; border: 1px solid transparent; border-radius: {R_CTRL}px;
        padding: 5px 9px; color: {TEXT}; font-size: 12.5px; font-weight: 500; }}
    QLineEdit#field:hover, QComboBox#field:hover, QSpinBox#field:hover,
    QDoubleSpinBox#field:hover {{ border-color: {LINE}; }}
    QLineEdit#field:focus, QComboBox#field:focus, QSpinBox#field:focus,
    QDoubleSpinBox#field:focus {{ border-color: {TEXT}; }}
    QLineEdit#field {{ selection-background-color: {TEXT}; selection-color: #FFFFFF; }}
    QSpinBox#field::up-button, QSpinBox#field::down-button,
    QDoubleSpinBox#field::up-button, QDoubleSpinBox#field::down-button {{
        width: 0; height: 0; border: none; }}

    QFrame#chan {{ background: transparent; border: none;
                   border-bottom: 1px solid {LINE_SOFT}; border-radius: 0; }}
    QLabel#dot {{ border-radius: 3px; min-width: 12px; max-width: 12px;
                  min-height: 12px; max-height: 12px; }}
    QSpinBox#soft, QDoubleSpinBox#soft, QComboBox#soft {{
        background: {FIELD}; border: 1px solid transparent; border-radius: {R_CTRL}px;
        padding: 7px 10px; }}
    QSpinBox#soft:hover, QDoubleSpinBox#soft:hover, QComboBox#soft:hover {{
        border-color: {LINE}; }}
    QSpinBox#soft::up-button, QSpinBox#soft::down-button,
    QDoubleSpinBox#soft::up-button, QDoubleSpinBox#soft::down-button {{
        width: 0; height: 0; border: none; }}
    QSpinBox#val, QDoubleSpinBox#val {{
        background: transparent; border: none; padding: 0; color: {TEXT};
        font-size: 11px; }}
    QSpinBox#val::up-button, QSpinBox#val::down-button,
    QDoubleSpinBox#val::up-button, QDoubleSpinBox#val::down-button {{
        width: 0; height: 0; border: none; }}

    QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {{
        background: {FIELD}; border: 1px solid transparent; border-radius: {R_CTRL}px;
        padding: 6px 9px; selection-background-color: {TEXT}; selection-color: #FFFFFF; }}
    QComboBox:hover, QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover {{
        border-color: {LINE}; }}
    QComboBox:focus, QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
        border-color: {TEXT}; }}
    QComboBox::drop-down {{ border: none; width: 20px; }}
    QComboBox QAbstractItemView {{ background: {CARD}; border: 1px solid {LINE};
        border-radius: {R_CTRL}px; padding: 4px; selection-background-color: {TEXT};
        selection-color: #FFFFFF; outline: none; }}
    QSpinBox::up-button, QSpinBox::down-button,
    QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 15px; border: none; }}

    QCheckBox {{ spacing: 7px; color: {TEXT}; font-size: 12.5px; }}
    QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px;
        border: 1px solid rgba(33,30,24,0.22); background: {CARD}; }}
    QCheckBox::indicator:checked {{ background: {PRIMARY}; border-color: {TEXT}; }}
    QCheckBox::indicator:hover {{ border-color: {TEXT}; }}

    QSlider::groove:horizontal {{ height: 4px; background: rgba(33,30,24,0.12);
                                 border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {PRIMARY}; border-radius: 2px; }}
    QSlider::handle:horizontal {{ width: 13px; height: 13px; margin: -5px 0; background: {CARD};
        border: 2px solid {PRIMARY}; border-radius: 7px; }}

    QProgressBar {{ background: rgba(33,30,24,0.10); border: none; border-radius: 4px;
                   height: 7px; }}
    QProgressBar::chunk {{ background: {PRIMARY}; border-radius: 4px; }}

    QScrollArea {{ background: transparent; border: none; }}
    QScrollBar:vertical {{ background: transparent; width: 9px; margin: 2px; }}
    /* 左栏文件列表：滚动条再细一点，别吃文件名宽度 */
    QScrollArea#fileScroll QScrollBar:vertical {{ width: 4px; margin: 0; }}
    QScrollArea#fileScroll QScrollBar::handle:vertical {{ border-radius: 2px; }}
    QScrollBar::handle:vertical {{ background: rgba(33,30,24,0.16); border-radius: 4px;
                                   min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: rgba(33,30,24,0.28); }}
    QScrollBar::handle:vertical:disabled {{ background: transparent; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    QScrollBar:horizontal {{ background: transparent; height: 9px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: rgba(33,30,24,0.16); border-radius: 4px;
                                     min-width: 30px; }}

    /* 信息条不带框：只留文字（2026-11-03 用户要求） */
    QLabel#chip {{ background: transparent; color: {TEXT};
                  border: none; border-radius: 0;
                  padding: 3px 8px; font-size: 11px; }}
    QLabel#chipStrong {{ background: {FIELD}; color: {TEXT}; border: none;
                        border-radius: 5px; padding: 4px 9px; font-size: 12.5px; }}

    QMenu {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 8px;
            padding: 5px; }}
    QMenu::item {{ padding: 6px 20px 6px 12px; border-radius: 5px; color: {TEXT}; }}
    QMenu::item:selected {{ background: {PRIMARY_WEAK}; color: {TEXT}; }}
    QMenu::separator {{ height: 1px; background: {LINE}; margin: 5px 8px; }}

    QMessageBox, QInputDialog {{ background: {CARD}; }}
    QToolTip {{ background: {TEXT}; color: #FFFFFF; border: none; padding: 5px 8px;
               border-radius: 5px; }}
    """
