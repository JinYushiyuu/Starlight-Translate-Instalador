"""Pastas do sistema de forma portátil (Windows / Linux)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "StarlightTranslate"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_dir() -> Path:
    """Pasta onde estão img/ e catalog/ (dentro do exe quando empacotado)."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def resource(rel: str) -> Path:
    return resource_dir() / rel.replace("\\", "/")


def _mk(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def config_dir() -> Path:
    override = os.environ.get("STARLIGHT_CONFIG_DIR")
    if override:
        return _mk(Path(override))
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return _mk(base / APP_DIR_NAME)


def cache_dir() -> Path:
    override = os.environ.get("STARLIGHT_CACHE_DIR")
    if override:
        return _mk(Path(override))
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return _mk(base / APP_DIR_NAME)


def default_download_dir() -> Path:
    docs = Path.home() / "Documents"
    base = docs if docs.is_dir() else Path.home()
    return base / "Starlight_Downloads"


def executable_path() -> Path:
    return Path(sys.executable if is_frozen() else sys.argv[0]).resolve()
