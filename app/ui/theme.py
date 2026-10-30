# -*- coding: utf-8 -*-
"""界面主题：柔和深灰左栏 + 淡灰底 + 浅灰卡片 + 靛蓝主色（紫只留在点缀上）。"""

RAIL = "#2B2B31"          # 左栏深底（柔和深灰，不再是纯黑）
RAIL_2 = "#37373E"        # 左栏里的卡片
BG = "#EAEAEC"            # 窗口底色：淡灰
BG_DEEP = "#E0E0E3"       # 中间主图那块「台面」
SOFT = "#F5F5F7"          # 卡片面（收起的模块行 / 展开的内容 / 底栏）
CARD = "#FFFFFF"          # 小面：输入框、药丸、缩略图
PRIMARY = "#5B5BD6"       # 主色：选中态、裁剪框、滑条、主按钮
PRIMARY_DARK = "#4A4AC2"
CORAL = "#FF6B6B"         # 强调（小面积）
MINT = "#2FD3C4"          # 次强调（进度、状态点）
TEXT = "#24242B"
MUTED = "#85858F"
LINE = "#DCDCE0"
LINE_SOFT = "#EDEDEF"

# 展开后标题行的淡紫渐变 + 圆环
GRAD_A = "#DCCBF6"
GRAD_B = "#BFA3EF"
BORDER_MOD = "#CDCDD3"
HEAD_TEXT = "#4A3B6B"
HEAD_HINT = "#6E5F92"
RING_ON = "#5B3FA8"
RING_OFF = "#A98BE8"

R_WIN = 24
R_CARD = 18
R_CTRL = 11

FONT = '"Microsoft YaHei","Segoe UI",sans-serif'


def qss():
    return f"""
    QWidget {{ background: {BG}; color: {TEXT};
              font-family: {FONT}; font-size: 12.5px; }}
    QMainWindow, QDialog {{ background: {BG}; }}
    QLabel {{ background: transparent; }}
    QLabel#appTitle {{ font-size: 17px; font-weight: 700; color: {TEXT}; }}
    QLabel#muted {{ color: {MUTED}; font-size: 11px; }}

    QFrame#rail {{ background: {RAIL}; border-radius: {R_WIN}px; }}
    QFrame#rail QLabel {{ color: #FFFFFF; }}
    QFrame#rail QLabel#muted {{ color: rgba(255,255,255,0.60); }}
    QLabel#railCap {{ color: rgba(255,255,255,0.42); font-size: 10.5px; letter-spacing: 1px; }}
    QLabel#railSub {{ color: rgba(255,255,255,0.52); font-size: 10.5px; }}
    QFrame#railCard {{ background: {RAIL_2}; border-radius: 14px; }}
    QFrame#railCard QPushButton {{ background: rgba(255,255,255,0.10); color: #FFFFFF;
        border: 1px solid rgba(255,255,255,0.14); }}
    QFrame#railCard QPushButton:hover {{ background: {PRIMARY}; border-color: {PRIMARY}; }}
    QFrame#rail QPushButton#railPrimary {{ background: {PRIMARY}; color: #FFFFFF;
        border: none; font-weight: 600; }}
    QFrame#rail QPushButton#railPrimary:hover {{ background: {PRIMARY_DARK}; }}
    QFrame#rail QPushButton {{ background: rgba(255,255,255,0.10); color: #FFFFFF;
        border: 1px solid rgba(255,255,255,0.14); }}
    QFrame#rail QPushButton:hover {{ background: rgba(255,255,255,0.18); }}

    QFrame#card {{ background: {SOFT}; border: 1px solid {LINE_SOFT};
                  border-radius: {R_CARD}px; }}
    /* 中间主图那块：淡紫「台面」，不再是刺眼的白 */
    QFrame#stage {{ background: {BG_DEEP}; border: none; border-radius: 20px; }}
    /* 功能模块：收起 = 白色单选行（带柔光）；展开 = 浅灰卡片 + 灰边 */
    QFrame#module {{ background: {SOFT}; border: none; border-radius: 10px; }}
    QFrame#module[expanded="true"] {{ background: {SOFT}; border: 2px solid {BORDER_MOD};
                                     border-radius: 20px; }}
    QFrame#module[expanded="true"][hover="true"] {{ border-color: #008BF8; }}
    QFrame#modHead {{ background: transparent; }}
    QFrame#module[expanded="true"] QFrame#modHead {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                    stop:0 {GRAD_A}, stop:1 {GRAD_B});
        border-top-left-radius: 18px; border-top-right-radius: 18px;
        border-bottom-left-radius: 0px; border-bottom-right-radius: 0px; }}
    QFrame#module[expanded="true"] QLabel#cardTitle {{ color: {HEAD_TEXT}; }}
    QFrame#module[expanded="true"] QLabel#cardHint {{ color: {HEAD_HINT}; }}
    QLabel#cardHint {{ color: {MUTED}; font-size: 11px; }}
    QLabel#cardTitle {{ font-weight: 700; color: {TEXT}; font-size: 12.5px; }}

    QFrame#groupCard {{ background: rgba(255,255,255,0.06); border-radius: 13px; }}
    QFrame#groupCard QLabel {{ color: #FFFFFF; }}
    QFrame#groupCard QLabel#muted {{ color: rgba(255,255,255,0.58); }}
    QFrame#groupCard[active="true"] {{ background: {PRIMARY}; }}
    QFrame#groupCard[active="true"] QLabel {{ color: #FFFFFF; font-weight: 600; }}
    QFrame#groupCard[active="true"] QLabel#muted {{ color: rgba(255,255,255,0.85); }}

    QFrame#thumb {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 13px; }}
    QFrame#thumb[active="true"] {{ border: 2px solid {PRIMARY}; }}
    QLabel#thumbPic {{ background: {RAIL}; border-radius: 9px; }}
    QLabel#thumbName {{ font-size: 10.5px; font-weight: 600; }}

    QPushButton {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 999px;
                  padding: 7px 14px; color: {TEXT}; }}
    QPushButton:hover {{ border-color: {PRIMARY}; color: {PRIMARY}; }}
    QPushButton:pressed {{ background: #F6F6FE; }}
    QPushButton:disabled {{ color: #B6BECC; border-color: {LINE_SOFT}; }}
    QPushButton#primary {{ background: {PRIMARY}; border: none; color: #FFFFFF;
                          font-weight: 700; padding: 9px 20px; }}
    QPushButton#primary:hover {{ background: {PRIMARY_DARK}; }}
    QPushButton#seg {{ background: {CARD}; color: {MUTED}; }}
    QPushButton#seg:checked {{ background: {PRIMARY}; color: #FFFFFF;
                              border-color: {PRIMARY}; font-weight: 600; }}
    QPushButton#mini {{ padding: 4px 9px; font-size: 11px; border-radius: 999px; }}
    QPushButton#pill {{ background: {CARD}; border: none; border-radius: 999px;
                        padding: 7px 13px; color: {TEXT}; font-size: 11.5px; }}
    QPushButton#pill:hover {{ background: #EDEEF5; }}
    QPushButton#pill:checked {{ background: {PRIMARY}; color: #FFFFFF; font-weight: 600; }}
    QPushButton#softField {{ background: #F5F6FB; border: 1px solid transparent;
                            border-radius: 12px; padding: 8px 12px; color: {TEXT};
                            font-size: 12px; font-weight: 400; text-align: left; }}
    QPushButton#softField:hover {{ background: #ECEDF7; }}

    /* 输入框：浅灰圆角底 + 鼠标移上去/输入时深色描边（照 formField 那个样式） */
    QLineEdit#field, QComboBox#field, QSpinBox#field, QDoubleSpinBox#field {{
        background: {CARD}; border: 2px solid transparent; border-radius: 5px;
        padding: 5px 10px; color: #333333; font-size: 12.5px; font-weight: 500; }}
    QLineEdit#field:hover, QComboBox#field:hover, QSpinBox#field:hover,
    QDoubleSpinBox#field:hover, QLineEdit#field:focus, QComboBox#field:focus,
    QSpinBox#field:focus, QDoubleSpinBox#field:focus {{
        border-color: #333333; }}
    QLineEdit#field {{ selection-background-color: {PRIMARY}; selection-color: #FFFFFF; }}
    QSpinBox#field::up-button, QSpinBox#field::down-button,
    QDoubleSpinBox#field::up-button, QDoubleSpinBox#field::down-button {{
        width: 0; height: 0; border: none; }}

    QFrame#chan {{ background: {CARD}; border: 1px solid {LINE_SOFT};
                   border-radius: 14px; }}
    QLabel#dot {{ border-radius: 6px; min-width: 12px; max-width: 12px;
                  min-height: 12px; max-height: 12px; }}
    QSpinBox#soft, QDoubleSpinBox#soft, QComboBox#soft {{
        background: #F5F6FB; border: 1px solid transparent; border-radius: 12px;
        padding: 8px 12px; }}
    QSpinBox#soft:hover, QDoubleSpinBox#soft:hover, QComboBox#soft:hover {{
        border-color: {LINE}; }}
    QSpinBox#soft::up-button, QSpinBox#soft::down-button,
    QDoubleSpinBox#soft::up-button, QDoubleSpinBox#soft::down-button {{
        width: 0; height: 0; border: none; }}
    QSpinBox#val, QDoubleSpinBox#val {{
        background: transparent; border: none; padding: 0; color: {MUTED};
        font-size: 11px; }}
    QSpinBox#val::up-button, QSpinBox#val::down-button,
    QDoubleSpinBox#val::up-button, QDoubleSpinBox#val::down-button {{
        width: 0; height: 0; border: none; }}

    QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {{
        background: {CARD}; border: 1px solid {LINE}; border-radius: {R_CTRL}px;
        padding: 6px 9px; selection-background-color: {PRIMARY}; selection-color: #FFFFFF; }}
    QComboBox:hover, QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover {{
        border-color: #C9D8E6; }}
    QComboBox:focus, QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
        border-color: {PRIMARY}; }}
    QComboBox::drop-down {{ border: none; width: 20px; }}
    QComboBox QAbstractItemView {{ background: {CARD}; border: 1px solid {LINE};
        border-radius: {R_CTRL}px; padding: 4px; selection-background-color: {PRIMARY};
        selection-color: #FFFFFF; outline: none; }}
    QSpinBox::up-button, QSpinBox::down-button,
    QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 15px; border: none; }}

    QCheckBox {{ spacing: 7px; color: {TEXT}; font-size: 12px; }}
    QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 6px;
        border: 1px solid #D7DCE8; background: {CARD}; }}
    QCheckBox::indicator:checked {{ background: {PRIMARY}; border-color: {PRIMARY}; }}
    QCheckBox::indicator:hover {{ border-color: {PRIMARY}; }}

    QSlider::groove:horizontal {{ height: 6px; background: {LINE}; border-radius: 3px; }}
    QSlider::sub-page:horizontal {{ background: {PRIMARY}; border-radius: 3px; }}
    QSlider::handle:horizontal {{ width: 15px; margin: -5px 0; background: {CARD};
        border: 2px solid {PRIMARY}; border-radius: 8px; }}

    QProgressBar {{ background: {LINE}; border: none; border-radius: 6px; height: 9px; }}
    QProgressBar::chunk {{ background: {PRIMARY}; border-radius: 6px; }}

    QScrollArea {{ background: transparent; border: none; }}
    QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: #D3DAE6; border-radius: 4px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: #B9C4D6; }}
    QScrollBar::handle:vertical:disabled {{ background: transparent; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: #D3DAE6; border-radius: 4px; min-width: 30px; }}

    QLabel#chip {{ background: {BG}; color: {MUTED}; border: 1px solid {LINE};
                  border-radius: 999px; padding: 4px 10px; font-size: 11px; }}
    QLabel#chipStrong {{ background: {CARD}; color: {TEXT}; border: 1px solid {LINE};
                        border-radius: 999px; padding: 5px 11px; font-size: 11.5px; }}

    QMenu {{ background: {CARD}; border: 1px solid {LINE}; border-radius: {R_CTRL}px;
            padding: 6px; }}
    QMenu::item {{ padding: 7px 22px 7px 14px; border-radius: 8px; color: {TEXT}; }}
    QMenu::item:selected {{ background: {PRIMARY}; color: #FFFFFF; }}
    QMenu::separator {{ height: 1px; background: {LINE}; margin: 5px 8px; }}

    QMessageBox, QInputDialog {{ background: {CARD}; }}
    QToolTip {{ background: {RAIL}; color: #FFFFFF; border: none; padding: 5px 8px;
               border-radius: 8px; }}
    """

