"""Janela de atualização automática do instalador (aparece ao abrir).

Verifica se há Release novo; se houver, mostra a imagem da Rise com a barra de
download, troca o executável e reabre. Se não houver (ou estiver offline), só
avisa que pode continuar e a tela inicial abre normalmente.
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QProgressBar, QVBoxLayout, QWidget

from .. import app_config, paths, selfupdate
from ..download import DownloadCancelled, Downloader
from . import style
from .tasks import run_task

# A pasta no repositório está como "intalador-update"; aceita a grafia certa também.
IMAGE_DIRS = ("img/instalador-update", "img/intalador-update")
IMAGE_NAMES = ("rise.jpg", "Rise.jpg", "rise.png", "Rise.png")
SHOW_DELAY_MS = 400  # não pisca a janela quando não há update e a checagem é rápida


def find_image():
    for folder in IMAGE_DIRS:
        for name in IMAGE_NAMES:
            f = paths.resource(f"{folder}/{name}")
            if f.exists():
                return f
    return None


class UpdateWindow(QWidget):
    proceed = Signal()  # nada (mais) a atualizar: abra a interface normal

    def __init__(
        self,
        checker: Callable[[], Optional[selfupdate.UpdateInfo]] = selfupdate.check,
        downloader: Optional[Downloader] = None,
    ):
        super().__init__()
        self._checker = checker
        self._dl = downloader or Downloader()
        self._finished = False
        self._downloading = False
        self._bg: Optional[QPixmap] = None

        self.setWindowTitle(app_config.APP_TITLE)
        self.setFixedSize(720, 405)  # mesma proporção 16:9 da imagem
        img = find_image()
        if img:
            pm = QPixmap(str(img))
            if not pm.isNull():
                self._bg = pm.scaled(self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)

        self.title = QLabel("Verificando atualizações...")
        self.title.setStyleSheet("font-size: 22px; font-weight: 700;")
        self.status = QLabel("Aguarde um instante")
        self.status.setStyleSheet(f"font-size: 13px; color: {style.SOFT};")
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)  # indeterminada até saber o tamanho
        self.bar.setTextVisible(True)
        self.bar.setFixedHeight(20)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 24, 32, 28)
        lay.addStretch(1)
        lay.addWidget(self.title)
        lay.addWidget(self.status)
        lay.addSpacing(8)
        lay.addWidget(self.bar)

    # -- fluxo ----------------------------------------------------------------- #
    def start(self) -> None:
        QTimer.singleShot(SHOW_DELAY_MS, self._reveal)
        run_task(lambda _e: self._checker(), on_done=self._on_checked, on_fail=lambda _e: self._finish())

    def _reveal(self) -> None:
        if not self._finished:
            self.show()

    def _on_checked(self, info: Optional[selfupdate.UpdateInfo]) -> None:
        if info is None:
            self._finish()
            return
        self._downloading = True
        self.title.setText(f"Atualizando o instalador para a v{info.version}")
        self.status.setText("Baixando a nova versão...")
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.show()

        def work(emit):
            return selfupdate.download_update(info, lambda d, t: emit((d, t)), self._dl)

        run_task(work, on_done=self._on_downloaded, on_fail=self._on_failed, on_progress=self._on_progress)

    def _on_progress(self, data) -> None:
        done, total = data
        if total > 0:
            self.bar.setRange(0, 100)
            self.bar.setValue(min(100, int(done * 100 / total)))
            self.status.setText(f"Baixando a nova versão... {done / 1_048_576:.1f} / {total / 1_048_576:.1f} MB")
        else:
            self.bar.setRange(0, 0)

    def _on_downloaded(self, new_file) -> None:
        self.bar.setRange(0, 100)
        self.bar.setValue(100)
        self.title.setText("Instalando a atualização")
        self.status.setText("O instalador vai reiniciar sozinho.")
        QApplication.processEvents()
        try:
            selfupdate.apply_and_restart(new_file)  # não retorna quando dá certo
        except Exception as exc:  # noqa: BLE001
            self._downloading = False
            QMessageBox.warning(
                self,
                "Atualização do instalador",
                f"Não foi possível instalar a nova versão.\nO instalador será aberto na versão atual.\n\nDetalhes: {exc}",
            )
            self._finish()

    def _on_failed(self, exc: BaseException) -> None:
        self._downloading = False
        if not isinstance(exc, DownloadCancelled):
            QMessageBox.warning(
                self,
                "Atualização do instalador",
                f"Não foi possível baixar a atualização.\nO instalador será aberto na versão atual.\n\nDetalhes: {exc}",
            )
        self._finish()

    def _finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        self.proceed.emit()  # a interface principal abre ANTES de esta janela sumir
        self.hide()

    def closeEvent(self, event) -> None:
        # Fechar no meio do download cancela e abre o instalador na versão atual.
        if self._downloading:
            self._dl.cancel()
        self._finish()
        event.accept()

    # -- desenho --------------------------------------------------------------- #
    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(style.BG))
        if self._bg:
            p.drawPixmap((self.width() - self._bg.width()) // 2, (self.height() - self._bg.height()) // 2, self._bg)
        fade = QLinearGradient(0, self.height() * 0.35, 0, self.height())
        fade.setColorAt(0.0, QColor(0, 0, 0, 0))
        fade.setColorAt(1.0, QColor(0, 0, 0, 215))
        p.fillRect(self.rect(), fade)

