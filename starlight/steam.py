"""Localiza a pasta de um jogo no Windows e no Linux.

1) Bibliotecas da Steam (registro no Windows; ~/.steam, ~/.local/share/Steam e
   Flatpak/Snap no Linux, mais todas as bibliotecas do libraryfolders.vdf).
2) Se não achar, varredura em largura nos discos/pastas do usuário.
"""
from __future__ import annotations

import os
import re
import sys
import threading
from collections import deque
from pathlib import Path
from typing import Callable, Iterable, Optional

from .fsutil import all_requirements_met

IGNORED_DIRS = {
    # Windows
    "windows", "$recycle.bin", "system volume information", "programdata", "appdata",
    "recovery", "perflogs", "config.msi", "msocache",
    # Linux
    "proc", "sys", "dev", "run", "boot", "lost+found", "node_modules", "__pycache__",
}


def steam_roots() -> list[Path]:
    roots: list[Path] = []
    if os.name == "nt":
        try:
            import winreg

            for hive, sub in (
                (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam"),
            ):
                try:
                    with winreg.OpenKey(hive, sub) as k:
                        for name in ("SteamPath", "InstallPath"):
                            try:
                                roots.append(Path(winreg.QueryValueEx(k, name)[0]))
                            except OSError:
                                pass
                except OSError:
                    pass
        except ImportError:
            pass
        for env in ("ProgramFiles(x86)", "ProgramFiles"):
            if os.environ.get(env):
                roots.append(Path(os.environ[env]) / "Steam")
    else:
        home = Path.home()
        roots += [
            home / ".steam" / "steam",
            home / ".steam" / "root",
            home / ".local" / "share" / "Steam",
            home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam",
            home / "snap" / "steam" / "common" / ".local" / "share" / "Steam",
        ]
    seen, out = set(), []
    for r in roots:
        try:
            key = r.resolve()
        except OSError:
            key = r
        if key not in seen and r.is_dir():
            seen.add(key)
            out.append(r)
    return out


def library_common_dirs(roots: Optional[Iterable[Path]] = None) -> list[Path]:
    """Todas as pastas steamapps/common (biblioteca principal + extras)."""
    result: list[Path] = []

    def add(p: Path) -> None:
        if p.is_dir() and p not in result:
            result.append(p)

    for root in roots if roots is not None else steam_roots():
        add(root / "steamapps" / "common")
        vdf = root / "steamapps" / "libraryfolders.vdf"
        try:
            text = vdf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in re.finditer(r'"path"\s*"([^"]+)"', text):
            lib = Path(m.group(1).replace("\\\\", "\\"))
            add(lib / "steamapps" / "common")
    return result


def find_in_steam(required: list[str], roots: Optional[Iterable[Path]] = None) -> Optional[Path]:
    for common in library_common_dirs(roots):
        try:
            for entry in os.scandir(common):
                if entry.is_dir() and all_requirements_met(Path(entry.path), required):
                    return Path(entry.path)
        except OSError:
            continue
    return None


def scan_roots() -> list[Path]:
    roots: list[Path] = []
    if os.name == "nt":
        import ctypes
        import string

        for letter in string.ascii_uppercase:
            drv = f"{letter}:\\"
            if not os.path.exists(drv):
                continue
            try:
                kind = ctypes.windll.kernel32.GetDriveTypeW(drv)  # 2=removível 3=fixo
            except Exception:
                kind = 3
            if kind in (2, 3):
                roots.append(Path(drv))
    else:
        roots.append(Path.home())
        for base in ("/mnt", "/media", "/run/media", "/games", "/Games"):
            b = Path(base)
            if not b.is_dir():
                continue
            try:
                for child in b.iterdir():
                    if child.is_dir():
                        roots.append(child)
                        if base in ("/media", "/run/media"):  # /media/<usuario>/<disco>
                            roots.extend(c for c in child.iterdir() if c.is_dir())
            except OSError:
                pass
    return roots


def scan(
    required: list[str],
    roots: Optional[Iterable[Path]] = None,
    progress: Optional[Callable[[str], None]] = None,
    cancel: Optional[threading.Event] = None,
    max_depth: int = 6,
) -> Optional[Path]:
    required = [r for r in required if r]
    if not required:
        return None
    for root in roots if roots is not None else scan_roots():
        queue: deque[tuple[Path, int]] = deque([(Path(root), 0)])
        while queue:
            if cancel is not None and cancel.is_set():
                return None
            cur, depth = queue.popleft()
            if progress:
                progress(str(cur))
            try:
                with os.scandir(cur) as it:
                    entries = list(it)
            except OSError:
                continue
            names = [e.name for e in entries]
            if all_requirements_met(cur, required, names):
                return cur
            if depth >= max_depth:
                continue
            for e in entries:
                try:
                    if not e.is_dir(follow_symlinks=False):
                        continue
                except OSError:
                    continue
                low = e.name.lower()
                if low in IGNORED_DIRS or e.name.startswith("."):
                    continue
                queue.append((Path(e.path), depth + 1))
    return None


def find_game(
    required: list[str],
    progress: Optional[Callable[[str], None]] = None,
    cancel: Optional[threading.Event] = None,
) -> Optional[Path]:
    return find_in_steam(required) or scan(required, progress=progress, cancel=cancel)
