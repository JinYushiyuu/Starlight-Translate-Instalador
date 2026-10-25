"""Cria atalho no menu iniciar/área de trabalho (Windows) ou no menu de aplicativos
(Linux) para o usuário não precisar procurar o arquivo baixado."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from . import paths

NAME = "Starlight Translate"


def can_offer() -> bool:
    return paths.is_frozen()


def create() -> list[str]:
    """Devolve a lista de atalhos criados (vazia se falhou)."""
    exe = paths.executable_path()
    made: list[str] = []
    try:
        if os.name == "nt":
            made += _windows(exe)
        else:
            made += _linux(exe)
    except Exception:
        pass
    return made


def _linux(exe: Path) -> list[str]:
    try:
        exe.chmod(exe.stat().st_mode | 0o111)
    except OSError:
        pass
    data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    icon_dst = data / "icons" / "starlight-translate.png"
    icon_dst.parent.mkdir(parents=True, exist_ok=True)
    src = paths.resource("img/icon-app/Sophie.png")
    if src.exists():
        shutil.copyfile(src, icon_dst)
    content = (
        "[Desktop Entry]\nType=Application\n"
        f"Name={NAME}\nComment=Instalador de traduções\n"
        f'Exec="{exe}"\nIcon={icon_dst}\nTerminal=false\nCategories=Game;Utility;\n'
    )
    out: list[str] = []
    targets = [data / "applications" / "starlight-translate.desktop"]
    desktop = Path.home() / "Desktop"
    if desktop.is_dir():
        targets.append(desktop / "starlight-translate.desktop")
    for t in targets:
        t.parent.mkdir(parents=True, exist_ok=True)
        t.write_text(content, encoding="utf-8")
        t.chmod(0o755)
        out.append(str(t))
    return out


def _windows(exe: Path) -> list[str]:
    appdata = Path(os.environ.get("APPDATA", ""))
    targets = [appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / f"{NAME}.lnk"]
    desktop = Path(os.environ.get("USERPROFILE", "")) / "Desktop"
    if desktop.is_dir():
        targets.append(desktop / f"{NAME}.lnk")
    out: list[str] = []
    for lnk in targets:
        lnk.parent.mkdir(parents=True, exist_ok=True)
        ps = (
            "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%s');"
            "$s.TargetPath='%s';$s.WorkingDirectory='%s';$s.IconLocation='%s,0';$s.Save()"
        ) % (str(lnk).replace("'", "''"), str(exe).replace("'", "''"), str(exe.parent).replace("'", "''"), str(exe).replace("'", "''"))
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, creationflags=0x08000000, timeout=20,  # CREATE_NO_WINDOW
        )
        if r.returncode == 0 and lnk.exists():
            out.append(str(lnk))
    return out
