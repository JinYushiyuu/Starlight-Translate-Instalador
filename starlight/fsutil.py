"""Utilidades de arquivo que se comportam igual no Windows e no Linux.

No Windows "Data\\PACK01.PAK" e "data\\pack01.pak" são o mesmo arquivo. No
Linux não são. Como as traduções são feitas em cima da versão Windows dos
jogos (rodando via Proton), todo acesso a arquivos do jogo passa por aqui
para ignorar maiúsculas/minúsculas e não criar pastas duplicadas.
"""
from __future__ import annotations

import fnmatch
import os
import stat
from pathlib import Path
from typing import Iterable, Optional


def norm_rel(rel: str) -> str:
    """Normaliza 'Data\\PACK01.PAK' -> 'Data/PACK01.PAK'."""
    rel = rel.replace("\\", "/")
    while rel.startswith("./"):
        rel = rel[2:]
    return rel.lstrip("/")


def _find_ci(directory: Path, name: str) -> Optional[str]:
    try:
        low = name.lower()
        with os.scandir(directory) as it:
            for entry in it:
                if entry.name.lower() == low:
                    return entry.name
    except OSError:
        pass
    return None


def resolve_ci(base: Path, rel: str) -> Path:
    """Resolve `rel` dentro de `base` casando cada pedaço sem diferenciar
    maiúsculas. Pedaços que não existem são mantidos como foram escritos."""
    cur = Path(base)
    for part in norm_rel(rel).split("/"):
        if not part or part == ".":
            continue
        cand = cur / part
        if cand.exists() or not cur.is_dir():
            cur = cand
            continue
        cur = cur / (_find_ci(cur, part) or part)
    return cur


def is_inside(base: Path, target: Path) -> bool:
    b = os.path.abspath(base)
    t = os.path.abspath(target)
    try:
        return os.path.commonpath([b, t]) == b
    except ValueError:  # discos diferentes no Windows
        return False


def _listdir(path: Path) -> list[str]:
    try:
        return os.listdir(path)
    except OSError:
        return []


def requirement_met(base: Path, pattern: str, listing: Optional[Iterable[str]] = None) -> bool:
    """Um item de `required_files` existe em `base`?

    Aceita caminhos ('Data\\PACK01.PAK') e curingas ('*.exe')."""
    pattern = norm_rel(pattern)
    if "*" in pattern or "?" in pattern:
        if "/" in pattern:
            folder, _, pat = pattern.rpartition("/")
            names = _listdir(resolve_ci(base, folder))
        else:
            pat = pattern
            names = list(listing) if listing is not None else _listdir(Path(base))
        pat = pat.lower()
        return any(fnmatch.fnmatch(n.lower(), pat) for n in names)
    if "/" not in pattern and listing is not None:
        low = pattern.lower()
        return any(n.lower() == low for n in listing)
    return resolve_ci(base, pattern).is_file()


def all_requirements_met(base: Path, patterns: Iterable[str], listing: Optional[Iterable[str]] = None) -> bool:
    patterns = list(patterns)
    if not patterns:
        return False
    listing = list(listing) if listing is not None else None
    return all(requirement_met(base, p, listing) for p in patterns)


def rmtree_force(path: Path) -> None:
    """Apaga uma pasta mesmo com arquivos somente-leitura (comum no Windows)."""
    import shutil

    def _onerror(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE | stat.S_IREAD)
            func(p)
        except OSError:
            pass

    shutil.rmtree(path, onerror=_onerror)


def remove_empty_dirs(dirs: Iterable[Path]) -> None:
    for d in sorted(set(dirs), key=lambda p: len(p.parts), reverse=True):
        try:
            d.rmdir()
        except OSError:
            pass
