"""Janela de atualização automática (offscreen)."""
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from starlight import selfupdate
from starlight.download import DownloadError
from starlight.ui import style
from starlight.ui import updater as upd


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    a.setStyleSheet(style.QSS)
    return a


def pump(app, cond, timeout=5000):
    loop = QEventLoop()
    t = QTimer()
    t.setInterval(20)
    t.timeout.connect(lambda: (cond() or timeout <= 0) and loop.quit())
    QTimer.singleShot(timeout, loop.quit)
    t.start()
    loop.exec()
    t.stop()
    return cond()


INFO = selfupdate.UpdateInfo(version="9.9.9", url="http://x/y", asset_name="y")


def test_encontra_imagem_da_rise():
    img = upd.find_image()
    assert img is not None and img.name.lower() == "rise.jpg"


def test_sem_update_nao_mostra_janela_e_segue(app):
    w = upd.UpdateWindow(checker=lambda: None)
    got = []
    w.proceed.connect(lambda: got.append(1))
    w.start()
    assert pump(app, lambda: got)
    assert not w.isVisible()


def test_com_update_baixa_com_barra_e_reinicia(app, monkeypatch, tmp_path):
    new = tmp_path / "novo.exe"
    seen = {}

    def fake_download(info, progress=None, downloader=None):
        for d in (10, 50, 100):
            progress(d, 100)
        new.write_bytes(b"x")
        return new

    monkeypatch.setattr(selfupdate, "download_update", fake_download)
    monkeypatch.setattr(selfupdate, "apply_and_restart", lambda f: seen.setdefault("apply", f))
    w = upd.UpdateWindow(checker=lambda: INFO)
    w.start()
    assert pump(app, lambda: "apply" in seen)
    assert seen["apply"] == new
    assert w.isVisible() and w.bar.value() == 100
    assert "9.9.9" in w.title.text() or "Instalando" in w.title.text()


def test_falha_no_download_abre_versao_atual(app, monkeypatch):
    def boom(*a, **k):
        raise DownloadError("sem rede")

    monkeypatch.setattr(selfupdate, "download_update", boom)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    w = upd.UpdateWindow(checker=lambda: INFO)
    got = []
    w.proceed.connect(lambda: got.append(1))
    w.start()
    assert pump(app, lambda: got)
    assert not w.isVisible()
