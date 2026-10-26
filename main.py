"""Ponto de entrada do Starlight Translate Instalador (Windows e Linux)."""
from __future__ import annotations

import sys

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog

from starlight import app_config, catalog, paths, selfupdate, state
from starlight.ui import style
from starlight.ui.dialogs import SettingsDialog
from starlight.ui.intro import IntroWindow
from starlight.ui.main_window import MainWindow
from starlight.ui.tasks import run_task


def _check_and_apply_startup_update(app: QApplication) -> None:
    """Atualiza o próprio executável antes de abrir a interface principal.

    Só roda em builds empacotados; ao executar pelo Python, não substitui o
    código-fonte do desenvolvedor. Se estiver offline ou o download falhar,
    continua abrindo a versão atual.
    """
    if not paths.is_frozen():
        return
    if not state.load_settings().get("check_installer_updates", True):
        return

    progress = QProgressDialog("Verificando atualizações do instalador...", "", 0, 0)
    progress.setWindowTitle(app_config.APP_TITLE)
    progress.setWindowModality(Qt.ApplicationModal)
    progress.setCancelButton(None)
    progress.setMinimumDuration(0)
    progress.show()
    app.processEvents()

    info = selfupdate.check()
    if info is None:
        progress.close()
        return

    progress.setLabelText(f"Baixando a versão {info.version} do instalador...")
    progress.setRange(0, 100)
    progress.setValue(0)
    app.processEvents()

    def on_progress(downloaded: int, total: int) -> None:
        if total > 0:
            progress.setRange(0, 100)
            progress.setValue(min(100, int(downloaded * 100 / total)))
        else:
            progress.setRange(0, 0)
        app.processEvents()

    try:
        new_file = selfupdate.download_update(info, on_progress)
        progress.setLabelText("Instalando atualização e reiniciando...")
        app.processEvents()
        selfupdate.apply_and_restart(new_file)
    except Exception as exc:
        progress.close()
        QMessageBox.warning(
            None,
            "Atualização do instalador",
            f"Não foi possível instalar a versão {info.version}.\n"
            f"O instalador será aberto na versão atual.\n\nDetalhes: {exc}",
        )
    finally:
        progress.close()


def main() -> int:
    selfupdate.cleanup_leftovers()
    app = QApplication(sys.argv)
    app.setApplicationName(app_config.APP_TITLE)
    app.setStyleSheet(style.QSS)
    icon = paths.resource("img/icon-app/Sophie.png")
    if not icon.exists():
        icon = paths.resource("img/icon-app/Sophie.ico")
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))

    # Verifica e aplica atualizações do próprio instalador antes da interface.
    _check_and_apply_startup_update(app)

    holder: dict = {"catalog": None, "main": None}
    intro = IntroWindow()

    def on_catalog(cat):
        holder["catalog"] = cat
        if holder["main"] is not None:
            holder["main"].set_catalog(cat)
            holder["main"]._prompt_translation_updates()

    run_task(lambda _e: catalog.load(), on_done=on_catalog)

    def open_main():
        cat = holder["catalog"] or catalog.load_bundled()
        win = MainWindow(cat)
        holder["main"] = win
        win.show()
        intro.close()
        QTimer.singleShot(400, win.offer_shortcut)
        win.start_background_checks() if holder["catalog"] else QTimer.singleShot(0, win.start_background_checks)

    def open_settings():
        info = f"catálogo: {holder['catalog'].source}" if holder["catalog"] else "catálogo: carregando..."
        SettingsDialog(intro, info).exec()

    intro.start.connect(open_main)
    intro.settings.connect(open_settings)
    intro.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
