"""Instala, desinstala e atualiza traduções dentro da pasta de um jogo.

Como funciona (diferente do instalador antigo):

* Para cada arquivo que o .zip da tradução vai escrever, o arquivo ORIGINAL
  do jogo (se existir) é MOVIDO para ``Starlight_Backup/files/`` (instantâneo,
  não duplica gigabytes em disco) e o arquivo traduzido é gravado no lugar.
* Arquivos que o zip ADICIONA (e que não existiam) são anotados em
  ``Starlight_Backup/install.json`` para serem apagados na desinstalação.
  O instalador antigo só restaurava os "arquivos obrigatórios" e deixava lixo.
* Se algo falhar no meio (disco cheio, jogo aberto, cancelamento), tudo é
  desfeito automaticamente (rollback).
* Na desinstalação, um arquivo que foi trocado por fora depois da instalação
  (ex.: a Steam atualizou o jogo) NÃO é sobrescrito pelo backup antigo.
"""
from __future__ import annotations

import contextlib
import json
import os
import shutil
import threading
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .fsutil import is_inside, norm_rel, remove_empty_dirs, resolve_ci, rmtree_force

BACKUP_DIR = "Starlight_Backup"
RECORD_NAME = "install.json"
FILES_SUBDIR = "files"

ProgressCb = Callable[[int, int, str], None]


class InstallError(Exception):
    """Erro com mensagem já pronta para mostrar ao usuário."""


class Cancelled(InstallError):
    pass


@dataclass
class UninstallResult:
    restored: int = 0
    removed: int = 0
    skipped_changed: list[str] = field(default_factory=list)
    legacy: bool = False


# --------------------------------------------------------------------------- #
# Consultas
# --------------------------------------------------------------------------- #
def backup_root(game_dir: Path) -> Path:
    return Path(game_dir) / BACKUP_DIR


def has_translation(game_dir: Path) -> bool:
    """Existe uma tradução (nossa ou do instalador antigo) nesta pasta?"""
    return backup_root(game_dir).is_dir()


def read_record(game_dir: Path) -> Optional[dict]:
    p = backup_root(game_dir) / RECORD_NAME
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def is_legacy(game_dir: Path) -> bool:
    """Instalação feita pelo instalador antigo (sem install.json)."""
    return has_translation(game_dir) and read_record(game_dir) is None


# --------------------------------------------------------------------------- #
# Instalação
# --------------------------------------------------------------------------- #
def _check_cancel(cancel: Optional[threading.Event]) -> None:
    if cancel is not None and cancel.is_set():
        raise Cancelled("Operação cancelada.")


def _new_dirs_for(dest: Path, game_dir: Path) -> list[Path]:
    """Pastas que ainda não existem entre game_dir e o arquivo (serão criadas)."""
    out, cur = [], dest.parent
    while not cur.exists() and is_inside(game_dir, cur) and cur != game_dir:
        out.append(cur)
        cur = cur.parent
    return out


def install(
    game_dir: Path,
    zip_path,
    game_id: str,
    version_id: str,
    version: str,
    progress: Optional[ProgressCb] = None,
    cancel: Optional[threading.Event] = None,
    options: Optional[dict] = None,
    signature: str = "",
) -> dict:
    """`zip_path` pode ser um .zip ou uma lista [base, extra1, extra2...].
    Se dois pacotes têm o mesmo arquivo, vale o do último; o ORIGINAL do jogo
    é sempre o que vai para o backup."""
    zip_paths = [Path(p) for p in (zip_path if isinstance(zip_path, (list, tuple)) else [zip_path])]
    game_dir = Path(game_dir)
    if not game_dir.is_dir():
        raise InstallError("A pasta do jogo não existe mais.")
    if has_translation(game_dir):
        raise InstallError("Já existe uma tradução instalada nesta pasta. Desinstale primeiro.")
    for zp in zip_paths:
        if not zipfile.is_zipfile(zp):
            raise InstallError(f"O arquivo baixado ({zp.name}) não é um .zip válido (download corrompido?).")

    root = backup_root(game_dir)
    files_dir = root / FILES_SUBDIR
    modified: dict[str, int] = {}
    added: dict[str, int] = {}
    created_dirs: list[Path] = []

    with contextlib.ExitStack() as stack:
        zfs = [stack.enter_context(zipfile.ZipFile(zp)) for zp in zip_paths]
        merged: dict[str, tuple[zipfile.ZipFile, zipfile.ZipInfo, Path, str]] = {}
        for zf in zfs:
            for m in zf.infolist():
                if m.is_dir():
                    continue
                dest = resolve_ci(game_dir, norm_rel(m.filename))
                if not is_inside(game_dir, dest):
                    raise InstallError(f"Pacote inseguro (caminho fora da pasta do jogo): {m.filename}")
                rel = dest.relative_to(game_dir).as_posix()
                if rel.split("/")[0].lower() == BACKUP_DIR.lower():
                    raise InstallError("O pacote tenta escrever na pasta de backup do instalador.")
                merged[rel.lower()] = (zf, m, dest, rel)  # o pacote seguinte sobrescreve o anterior
        if not merged:
            raise InstallError("O pacote da tradução está vazio.")
        plan = list(merged.values())

        total_bytes = sum(m.file_size for _, m, _, _ in plan)
        free = shutil.disk_usage(game_dir).free
        if free < total_bytes + 50 * 1024 * 1024:
            need = (total_bytes + 50 * 1024 * 1024) / 1024 / 1024
            raise InstallError(
                f"Espaço insuficiente na unidade do jogo (precisa de ~{need:.0f} MB livres)."
            )

        try:
            files_dir.mkdir(parents=True)
            total = len(plan)
            for i, (zf, m, dest, rel) in enumerate(plan, 1):
                _check_cancel(cancel)
                if dest.is_dir():
                    raise InstallError(f"'{rel}' é uma pasta no jogo, mas o pacote tem um arquivo com esse nome.")

                if dest.exists():
                    saved = files_dir / rel
                    saved.parent.mkdir(parents=True, exist_ok=True)
                    modified[rel] = -1  # registrado antes de mexer, para o rollback
                    shutil.move(str(dest), str(saved))
                else:
                    created_dirs.extend(_new_dirs_for(dest, game_dir))
                    added[rel] = -1
                dest.parent.mkdir(parents=True, exist_ok=True)

                with zf.open(m) as src, open(dest, "wb") as out:
                    shutil.copyfileobj(src, out, 1024 * 1024)
                size = dest.stat().st_size
                if rel in modified:
                    modified[rel] = size
                else:
                    added[rel] = size
                if progress:
                    progress(i, total, rel)

            record = {
                "schema": 1,
                "game_id": game_id,
                "version_id": version_id,
                "version": version,
                "options": dict(options or {}),
                "signature": signature or version,
                "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "modified": modified,
                "added": added,
                "created_dirs": sorted({d.relative_to(game_dir).as_posix() for d in created_dirs}),
            }
            (root / RECORD_NAME).write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
            return record
        except BaseException:
            _rollback(game_dir, modified, added, created_dirs)
            raise


def _rollback(game_dir: Path, modified: dict, added: dict, created_dirs: list[Path]) -> None:
    root = backup_root(game_dir)
    for rel in added:
        try:
            p = resolve_ci(game_dir, rel)
            if p.is_file():
                p.unlink()
        except OSError:
            pass
    for rel in modified:
        saved = root / FILES_SUBDIR / rel
        if saved.exists():
            try:
                dest = resolve_ci(game_dir, rel)
                if dest.is_file():
                    dest.unlink()
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(saved), str(dest))
            except OSError:
                pass
    remove_empty_dirs(created_dirs)
    if root.exists():
        rmtree_force(root)


# --------------------------------------------------------------------------- #
# Desinstalação
# --------------------------------------------------------------------------- #
def uninstall(game_dir: Path, progress: Optional[ProgressCb] = None) -> UninstallResult:
    game_dir = Path(game_dir)
    root = backup_root(game_dir)
    if not root.is_dir():
        raise InstallError("Não há tradução instalada nesta pasta.")

    record = read_record(game_dir)
    result = UninstallResult()
    if record is None:
        _uninstall_legacy(game_dir, root, result, progress)
        return result

    added: dict = record.get("added", {})
    modified: dict = record.get("modified", {})
    total = len(added) + len(modified)
    done = 0

    for rel in added:
        p = resolve_ci(game_dir, rel)
        try:
            if p.is_file():
                p.unlink()
                result.removed += 1
        except OSError as e:
            raise _friendly(e, p) from e
        done += 1
        if progress:
            progress(done, total, rel)

    for rel, installed_size in modified.items():
        dest = resolve_ci(game_dir, rel)
        saved = root / FILES_SUBDIR / rel
        try:
            if saved.exists():
                if dest.is_file() and installed_size >= 0 and dest.stat().st_size != installed_size:
                    # Alguém (ex.: Steam atualizando o jogo) trocou o arquivo depois
                    # da instalação: o backup está velho, não restaure por cima.
                    result.skipped_changed.append(rel)
                else:
                    if dest.exists():
                        dest.unlink()
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(saved), str(dest))
                    result.restored += 1
        except OSError as e:
            raise _friendly(e, dest) from e
        done += 1
        if progress:
            progress(done, total, rel)

    remove_empty_dirs(game_dir / d for d in record.get("created_dirs", []))
    rmtree_force(root)
    return result


def _uninstall_legacy(game_dir: Path, root: Path, result: UninstallResult, progress: Optional[ProgressCb]) -> None:
    """Backups do instalador antigo ficam direto em Starlight_Backup/<arquivo>."""
    result.legacy = True
    files = [p for p in root.rglob("*") if p.is_file()]
    for i, p in enumerate(files, 1):
        rel = p.relative_to(root).as_posix()
        dest = resolve_ci(game_dir, rel)
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dest)
            result.restored += 1
        except OSError as e:
            raise _friendly(e, dest) from e
        if progress:
            progress(i, len(files), rel)
    rmtree_force(root)


def _friendly(e: OSError, path: Path) -> InstallError:
    if isinstance(e, PermissionError):
        if os.name == "nt":
            hint = (
                "Feche o jogo (e a Steam, se estiver atualizando) e tente de novo. "
                "Se o jogo está em 'Program Files', abra o instalador com botão direito → "
                "'Executar como administrador'."
            )
        else:
            hint = (
                "Feche o jogo e confira se você tem permissão de escrita nessa pasta "
                "(discos NTFS/exFAT montados como somente leitura são comuns no Linux)."
            )
        return InstallError(f"Sem permissão para alterar '{path.name}'.\n\n{hint}")
    return InstallError(f"Erro ao mexer em '{path.name}': {e}")


def friendly_exception(e: BaseException) -> str:
    """Converte qualquer erro em texto para o usuário."""
    if isinstance(e, InstallError):
        return str(e)
    if isinstance(e, PermissionError):
        return str(_friendly(e, Path(e.filename or "arquivo")))
    if isinstance(e, OSError) and getattr(e, "errno", None) == 28:
        return "O disco ficou sem espaço durante a instalação. Nada foi alterado."
    return f"Erro inesperado: {e}"
