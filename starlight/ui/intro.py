"""Tela de abertura (imagem aleatória + INICIAR + engrenagem)."""
from __future__ import annotations

import random
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from .. import app_config, paths
from . import style

SLIDES = ["BR.jpg", "Estelle.jpg", "Rise.png", "Ryza.jpg", "Sophie.jpg"]


class IntroWindow(QWidget):
    start = Signal()
    settings = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle(app_config.APP_TITLE)
        self.setFixedSize(800, 550)
        self._bg: Optional[QPixmap] = None
        files = [paths.resource(f"img/Starlight-slider/{n}") for n in SLIDES]
        files = [f for f in files if f.exists()]
        if files:
            pm = QPixmap(str(random.choice(files)))
            self._bg = None if pm.isNull() else pm.scaled(self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)

        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignCenter)
        title = QLabel("Starlight Translate Instalador")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 32px; font-weight: 700;")
        sub = QLabel("Um instalador que une as traduções da Starlight Translate e Phantasie Translate")
        sub.setAlignment(Qt.AlignCenter)
        sub.setWordWrap(True)
        sub.setStyleSheet(f"font-size: 14px; color: {style.SOFT};")
        self.btn = QPushButton("INICIAR")
        self.btn.setFixedSize(200, 50)
        self.btn.setCursor(Qt.PointingHandCursor)
        style.style_button(self.btn, "primary")
        self.btn.clicked.connect(self.start.emit)
        lay.addStretch(1)
        lay.addWidget(title)
        lay.addSpacing(8)
        lay.addWidget(sub)
        lay.addSpacing(36)
        lay.addWidget(self.btn, alignment=Qt.AlignCenter)
        lay.addStretch(1)

        credit = QLabel(app_config.CREDITS_LINE, self)
        credit.setStyleSheet("font-size: 12px; font-weight: 700; color: #e2e8f0;")
        credit.adjustSize()
        credit.move(25, self.height() - credit.height() - 22)
        gear = QPushButton("⚙", self)
        gear.setFixedSize(40, 40)
        gear.setToolTip("Configurações (pasta de download)")
        gear.setStyleSheet(f"QPushButton {{ border-radius: 20px; font-size: 18px; padding: 0; background: {style.CARD}; }} QPushButton:hover {{ background: {style.CARD_HOVER}; }}")
        gear.move(self.width() - 65, self.height() - 60)
        gear.clicked.connect(self.settings.emit)

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(style.BG))
        if self._bg:
            p.drawPixmap((self.width() - self._bg.width()) // 2, (self.height() - self._bg.height()) // 2, self._bg)
        p.fillRect(self.rect(), QColor(0, 0, 0, 140))
