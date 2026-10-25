# -*- mode: python ; coding: utf-8 -*-
# Gera 1 arquivo único:  dist/Starlight-Translate-Instalador-<windows-x64|linux-x86_64>[.exe]
#   pyinstaller --noconfirm starlight.spec
import sys

IS_WIN = sys.platform.startswith("win")
NAME = "Starlight-Translate-Instalador-" + ("windows-x64" if IS_WIN else "linux-x86_64")

a = Analysis(
    ["main.py"],
    pathex=["."],
    datas=[("img", "img"), ("catalog", "catalog")],
    excludes=["tkinter", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtPdf", "PySide6.QtWebEngineCore", "PySide6.QtDesigner"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=NAME,
    console=False,
    icon="img/icon-app/Sophie.ico" if IS_WIN else None,
    upx=False,
)
