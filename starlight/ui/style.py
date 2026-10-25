"""Tema escuro (mesmas cores do instalador antigo) + utilitários de imagem."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPixmap

BG = "#1e1e24"
SIDEBAR = "#161920"
PANEL = "#141820"
CARD = "#2a2e38"
CARD_HOVER = "#3d4450"
TEXT = "#ffffff"
MUTED = "#aeb4bd"
SOFT = "#d2d6dc"
GREEN = "#47b900"
BLUE = "#2e86de"
RED = "#a83232"
ORANGE = "#e67e22"
CYAN = "#00bbf9"

QSS = f"""
QWidget {{ background: transparent; color: {TEXT}; font-family: "Segoe UI", "Noto Sans", "Ubuntu", "DejaVu Sans", sans-serif; font-size: 13px; }}
QDialog, QMessageBox {{ background: {BG}; }}
QLabel {{ background: transparent; }}
QToolTip {{ background: {CARD}; color: {TEXT}; border: 1px solid {CARD_HOVER}; padding: 4px; }}
QPushButton {{ background: {CARD}; color: {TEXT}; border: none; border-radius: 4px; padding: 8px 14px; font-weight: 600; }}
QPushButton:hover {{ background: {CARD_HOVER}; }}
QPushButton:disabled {{ background: {CARD}; color: #767f8e; }}
QPushButton[role="primary"] {{ background: {GREEN}; font-size: 14px; font-weight: 700; }}
QPushButton[role="primary"]:hover {{ background: #56d400; }}
QPushButton[role="blue"] {{ background: {BLUE}; font-size: 14px; font-weight: 700; }}
QPushButton[role="blue"]:hover {{ background: #4a9bea; }}
QPushButton[role="orange"] {{ background: {ORANGE}; font-size: 14px; font-weight: 700; }}
QPushButton[role="orange"]:hover {{ background: #f39c46; }}
QPushButton[role="danger"] {{ background: {RED}; }}
QPushButton[role="danger"]:hover {{ background: #c13c3c; }}
QPushButton[role="primary"]:disabled, QPushButton[role="blue"]:disabled, QPushButton[role="orange"]:disabled, QPushButton[role="danger"]:disabled {{ background: {CARD}; color: #767f8e; }}
QProgressBar {{ background: #1c212b; border: none; border-radius: 4px; height: 18px; text-align: center; color: white; font-size: 11px; }}
QProgressBar::chunk {{ background: {GREEN}; border-radius: 4px; }}
QListWidget {{ background: {SIDEBAR}; border: none; outline: none; }}
QScrollArea {{ border: none; background: #1b2838; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #3d4450; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 3px; background: {SIDEBAR}; border: 1px solid {CARD_HOVER}; }}
QCheckBox::indicator:checked {{ background: {GREEN}; border: 1px solid {GREEN}; }}
"""


def style_button(btn, role: str = "") -> None:
    btn.setProperty("role", role)
    btn.style().unpolish(btn)
    btn.style().polish(btn)


def load_pixmap(path: Optional[Path]) -> Optional[QPixmap]:
    if not path:
        return None
    pm = QPixmap(str(path))
    return None if pm.isNull() else pm


def rounded_icon(pm: Optional[QPixmap], size: int = 32, radius: int = 5) -> QPixmap:
    out = QPixmap(size, size)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size, size), radius, radius)
    p.setClipPath(path)
    if pm is None:
        p.fillRect(0, 0, size, size, QColor("#3d4450"))
        p.setPen(QColor("#aeb4bd"))
        p.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, "?")
    else:
        scaled = pm.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        p.drawPixmap((size - scaled.width()) // 2, (size - scaled.height()) // 2, scaled)
    p.end()
    return out

QSS += f"""
QComboBox {{ background: {SIDEBAR}; border: 1px solid {CARD_HOVER}; border-radius: 4px; padding: 6px 10px; }}
QComboBox:hover {{ border-color: {CYAN}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {SIDEBAR}; color: {TEXT}; selection-background-color: {CARD_HOVER}; border: 1px solid {CARD_HOVER}; outline: none; }}
"""
