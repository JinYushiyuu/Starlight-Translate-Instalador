"""Auto-atualização do próprio instalador via GitHub Releases."""
from __future__ import annotations

import os
import re
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import requests

from . import __version__, app_config, paths
from .download import Downloader


@dataclass
class UpdateInfo:
    version: str
    url: str
    asset_name: str
    sha256: str = ""
    notes: str = ""


def parse_version(v: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", v.split("-")[0])
    return tuple(int(n) for n in nums) or (0,)


def is_newer(remote: str, local: str = __version__) -> bool:
    a, b = parse_version(remote), parse_version(local)
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def asset_name_for_platform() -> str:
    return app_config.ASSET_WINDOWS if os.name == "nt" else app_config.ASSET_LINUX


def check(timeout: float = 8.0, api_url: Optional[str] = None) -> Optional[UpdateInfo]:
    """Há Release mais novo do instalador? Devolve None se não, ou se offline."""
    if api_url is None:
        if "SEU-USUARIO" in app_config.INSTALLER_REPO:
            return None
        api_url = f"https://api.github.com/repos/{app_config.INSTALLER_REPO}/releases/latest"
    try:
        r = requests.get(api_url, timeout=timeout, headers={"User-Agent": app_config.USER_AGENT, "Accept": "application/vnd.github+json"})
        r.raise_for_status()
        rel = r.json()
        tag = str(rel.get("tag_name") or "")
        if not tag or not is_newer(tag):
            return None
        want = asset_name_for_platform()
        for a in rel.get("assets", []):
            if a.get("name") == want:
                digest = str(a.get("digest") or "")
                return UpdateInfo(
                    version=tag.lstrip("vV"),
                    url=a["browser_download_url"],
                    asset_name=want,
                    sha256=digest.split(":", 1)[1] if digest.startswith("sha256:") else "",
                    notes=str(rel.get("body") or ""),
                )
    except Exception:
        pass
    return None


def can_self_replace() -> bool:
    """Só dá para trocar o executável quando rodando empacotado (PyInstaller)."""
    return paths.is_frozen()


def download_update(info: UpdateInfo, progress: Optional[Callable[[int, int], None]] = None, downloader: Optional[Downloader] = None) -> Path:
    exe = paths.executable_path()
    dest = exe.with_name(exe.name + ".new")
    (downloader or Downloader()).download(info.url, dest, progress, info.sha256)
    return dest


def apply_and_restart(new_file: Path) -> None:
    """Troca o executável atual pelo novo e reabre. Não retorna."""
    exe = paths.executable_path()
    if os.name == "nt":
        old = exe.with_name(exe.name + ".old")
        if old.exists():
            old.unlink()
        os.replace(exe, old)  # o Windows permite renomear um .exe em uso
        os.replace(new_file, exe)
        subprocess.Popen([str(exe)], close_fds=True, creationflags=0x00000008)  # DETACHED_PROCESS
        os._exit(0)
    else:
        os.chmod(new_file, os.stat(new_file).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        os.replace(new_file, exe)  # no Linux pode sobrescrever um binário em execução
        os.execv(str(exe), [str(exe)] + sys.argv[1:])


def cleanup_leftovers() -> None:
    """Chame ao iniciar: remove o .old de uma atualização anterior (Windows)."""
    if not paths.is_frozen():
        return
    exe = paths.executable_path()
    for suffix in (".old", ".new"):
        p = exe.with_name(exe.name + suffix)
        try:
            if p.exists():
                p.unlink()
        except OSError:
            pass
