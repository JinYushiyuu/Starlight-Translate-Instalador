"""Diálogos: localizar a pasta do jogo e configurações."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QVBoxLayout,
)

from .. import __version__, app_config, installer, state, steam
from ..catalog import Game
from ..fsutil import requirement_met
from . import style
from .tasks import run_task


class FindGameDialog(QDialog):
    """Equivalente à antiga janela 'Gerenciar Instalação': acha a pasta do jogo
    (Steam → varredura de discos) ou deixa o usuário escolher, e mostra um
    checklist dos arquivos obrigatórios."""

    def __init__(self, game: Game, parent=None, start_folder: Optional[Path] = None):
        super().__init__(parent)
        self.game = game
        self.folder: Optional[Path] = None
        self._cancel = threading.Event()
        self._busy = False
        self.setWindowTitle(f"Localizar o jogo - {game.name}")
        self.setMinimumWidth(580)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(12)

        t = QLabel("Onde o jogo está instalado?")
        t.setStyleSheet("font-size: 18px; font-weight: 700;")
        root.addWidget(t)
        sub = QLabel(game.name)
        sub.setStyleSheet(f"color: {style.MUTED};")
        sub.setWordWrap(True)
        root.addWidget(sub)

        row = QHBoxLayout()
        self.btn_auto = QPushButton("🔍  Procurar automaticamente")
        self.btn_auto.clicked.connect(self._auto)
        self.btn_manual = QPushButton("📂  Selecionar manualmente")
        self.btn_manual.clicked.connect(self._manual)
        row.addWidget(self.btn_auto)
        row.addWidget(self.btn_manual)
        root.addLayout(row)

        cap = QLabel("Pasta do jogo:")
        cap.setStyleSheet(f"color: {style.MUTED}; font-size: 11px;")
        root.addWidget(cap)
        self.lbl_path = QLabel("Nenhuma pasta selecionada.")
        self.lbl_path.setStyleSheet(f"background: {style.SIDEBAR}; padding: 8px; font-size: 11px;")
        self.lbl_path.setWordWrap(True)
        root.addWidget(self.lbl_path)

        box = QFrame()
        box.setObjectName("chk")
        box.setStyleSheet(f"QFrame#chk {{ background: {style.SIDEBAR}; border-radius: 6px; }}")
        g = QGridLayout(box)
        g.setContentsMargins(14, 12, 14, 12)
        head = QLabel("Arquivos do jogo:")
        head.setStyleSheet("font-weight: 700;")
        g.addWidget(head, 0, 0, 1, 2)
        self._marks: dict[str, QLabel] = {}
        for i, req in enumerate(game.required_files, 1):
            name = QLabel(req.replace("/", "\\") if _is_windows() else req)
            name.setStyleSheet(f"color: {style.MUTED};")
            mark = QLabel("Aguardando...")
            mark.setStyleSheet("color: gray; font-weight: 700;")
            g.addWidget(name, i, 0)
            g.addWidget(mark, i, 1, alignment=Qt.AlignRight)
            self._marks[req] = mark
        root.addWidget(box)

        self.lbl_hint = QLabel("")
        self.lbl_hint.setWordWrap(True)
        self.lbl_hint.setStyleSheet(f"color: {style.MUTED}; font-size: 11px;")
        root.addWidget(self.lbl_hint)

        self.btn_ok = QPushButton("USAR ESTA PASTA")
        self.btn_ok.setMinimumHeight(42)
        self.btn_ok.setEnabled(False)
        self.btn_ok.clicked.connect(self.accept)
        root.addWidget(self.btn_ok)

        if start_folder and Path(start_folder).is_dir():
            self._set_folder(Path(start_folder))

    # -- ações -------------------------------------------------------------- #
    def _manual(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Selecione a pasta raiz do jogo", str(self.folder or Path.home()))
        if d:
            self._set_folder(Path(d))

    def _auto(self) -> None:
        if self._busy:
            self._cancel.set()
            return
        self._busy = True
        self._cancel.clear()
        self.btn_auto.setText("⏹  Parar busca")
        self.btn_manual.setEnabled(False)
        for m in self._marks.values():
            m.setText("Pesquisando...")
            m.setStyleSheet("color: #f1c40f; font-weight: 700;")
        self.lbl_path.setText("Procurando nas bibliotecas da Steam...")
        req = self.game.required_files

        def work(emit):
            found = steam.find_in_steam(req)
            if found:
                return found
            emit("Vasculhando os discos...")
            return steam.scan(req, progress=lambda p: emit(f"Vasculhando: {p}"), cancel=self._cancel)

        def done(found):
            self._busy = False
            self.btn_auto.setText("🔍  Procurar automaticamente")
            self.btn_manual.setEnabled(True)
            if found:
                self._set_folder(Path(found))
            else:
                self.lbl_path.setText("Pasta não encontrada automaticamente. Tente selecionar manualmente.")
                self._mark_all(False)

        run_task(work, on_done=done, on_fail=lambda e: done(None), on_progress=self.lbl_path.setText)

    def _mark_all(self, ok: bool) -> None:
        for m in self._marks.values():
            _set_mark(m, ok)

    def _set_folder(self, folder: Path) -> None:
        self.folder = folder
        self.lbl_path.setText(str(folder))
        all_ok = True
        for req, mark in self._marks.items():
            ok = requirement_met(folder, req)
            _set_mark(mark, ok)
            all_ok &= ok
        self.btn_ok.setEnabled(all_ok)
        style.style_button(self.btn_ok, "primary" if all_ok else "")
        if not all_ok:
            self.lbl_hint.setText("Essa pasta não parece ser a do jogo (faltam arquivos acima).")
        elif installer.has_translation(folder):
            self.lbl_hint.setText("⚠ Já existe uma tradução instalada nesta pasta; ela será removida antes de instalar a nova.")
        else:
            self.lbl_hint.setText("")

    def reject(self) -> None:
        self._cancel.set()
        super().reject()


def _is_windows() -> bool:
    import os
    return os.name == "nt"


def _set_mark(label: QLabel, ok: bool) -> None:
    label.setText("✅ Encontrado" if ok else "❌ Não encontrado")
    label.setStyleSheet(f"color: {style.GREEN if ok else style.RED}; font-weight: 700;")


class SettingsDialog(QDialog):
    def __init__(self, parent=None, catalog_info: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Configurações")
        self.setMinimumWidth(560)
        s = state.load_settings()

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(12)

        t = QLabel("Pasta de downloads")
        t.setStyleSheet("font-size: 15px; font-weight: 700;")
        root.addWidget(t)
        obs = QLabel("O .zip baixado é apagado depois que a tradução é instalada.")
        obs.setStyleSheet(f"color: {style.MUTED}; font-size: 11px;")
        root.addWidget(obs)

        row = QHBoxLayout()
        self.edit = QLineEdit(str(state.download_dir()))
        self.edit.setStyleSheet(f"background: {style.SIDEBAR}; border: none; padding: 8px; border-radius: 4px;")
        btn = QPushButton("📁")
        btn.clicked.connect(self._browse)
        row.addWidget(self.edit, 1)
        row.addWidget(btn)
        root.addLayout(row)

        self.chk_tr = QCheckBox("Avisar quando houver atualização das traduções instaladas")
        self.chk_tr.setChecked(bool(s.get("check_translation_updates", True)))
        self.chk_in = QCheckBox("Verificar atualizações do instalador ao abrir")
        self.chk_in.setChecked(bool(s.get("check_installer_updates", True)))
        root.addWidget(self.chk_tr)
        root.addWidget(self.chk_in)

        info = QLabel(f"Instalador v{__version__}   •   {catalog_info}")
        info.setStyleSheet(f"color: {style.MUTED}; font-size: 11px;")
        info.setWordWrap(True)
        root.addWidget(info)
        if not app_config.is_configured():
            warn = QLabel("⚠ Os endereços do GitHub ainda não foram configurados (starlight/app_config.py): "
                          "usando só o catálogo que vem dentro do instalador.")
            warn.setStyleSheet("color: #f1c40f; font-size: 11px;")
            warn.setWordWrap(True)
            root.addWidget(warn)

        ok = QPushButton("SALVAR")
        ok.setMinimumHeight(40)
        style.style_button(ok, "primary")
        ok.clicked.connect(self._save)
        root.addWidget(ok)

    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Selecione a pasta para downloads", self.edit.text())
        if d:
            self.edit.setText(d)

    def _save(self) -> None:
        s = state.load_settings()
        path = self.edit.text().strip()
        try:
            Path(path).mkdir(parents=True, exist_ok=True)
            s["download_dir"] = path
        except OSError:
            pass
        s["check_translation_updates"] = self.chk_tr.isChecked()
        s["check_installer_updates"] = self.chk_in.isChecked()
        state.save_settings(s)
        self.accept()
