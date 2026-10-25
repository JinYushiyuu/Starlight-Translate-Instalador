"""Ponto de entrada do Starlight Translate Instalador (Windows e Linux)."""
from __future__ import annotations

import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from starlight import app_config, catalog, paths, selfupdate, state
from starlight.ui import style
from starlight.ui.dialogs import SettingsDialog
from starlight.ui.intro import IntroWindow
from starlight.ui.main_window import MainWindow
from starlight.ui.tasks import run_task


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
