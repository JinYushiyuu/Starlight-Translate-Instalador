"""Configurações do usuário e registro de traduções instaladas.

Tudo fica na pasta de configuração do usuário (nunca ao lado do .exe, que
pode estar numa pasta sem permissão de escrita)."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Optional

from . import installer, paths

_lock = threading.Lock()


def _read(name: str, default):
    try:
        return json.loads((paths.config_dir() / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(name: str, data) -> None:
    p = paths.config_dir() / name
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


DEFAULT_SETTINGS = {
    "download_dir": "",
    "check_installer_updates": True,
    "check_translation_updates": True,
}


def load_settings() -> dict:
    with _lock:
        d = dict(DEFAULT_SETTINGS)
        d.update(_read("settings.json", {}))
        return d


def save_settings(s: dict) -> None:
    with _lock:
        _write("settings.json", s)


def download_dir() -> Path:
    raw = load_settings().get("download_dir") or ""
    p = Path(raw) if raw else paths.default_download_dir()
    p.mkdir(parents=True, exist_ok=True)
    return p


# --- traduções instaladas: game_id -> {"path", "version_id", "version"} ------ #
def load_installs() -> dict:
    with _lock:
        return _read("installs.json", {})


def get_install(game_id: str) -> Optional[dict]:
    """Instalação registrada, confirmada no disco (pasta e backup ainda existem)."""
    rec = load_installs().get(game_id)
    if not rec:
        return None
    folder = Path(rec.get("path", ""))
    if folder.is_dir() and installer.has_translation(folder):
        return rec
    forget_install(game_id)
    return None


def set_install(game_id: str, path: Path, version_id: str, version: str, options: Optional[dict] = None, signature: str = "") -> None:
    with _lock:
        data = _read("installs.json", {})
        data[game_id] = {
            "path": str(path), "version_id": version_id, "version": version,
            "options": dict(options or {}), "signature": signature or version,
        }
        _write("installs.json", data)


def forget_install(game_id: str) -> None:
    with _lock:
        data = _read("installs.json", {})
        if data.pop(game_id, None) is not None:
            _write("installs.json", data)
