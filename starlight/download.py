"""Download de pacotes (GitHub Releases, Google Drive, qualquer link direto)
com pausa, cancelamento e verificação SHA-256."""
from __future__ import annotations

import hashlib
import html
import re
import threading
import time
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import quote, urljoin

import requests

from . import app_config

ProgressCb = Callable[[int, int], None]  # baixado, total (-1 = desconhecido)


class DownloadError(Exception):
    pass


class DownloadCancelled(DownloadError):
    pass


def resolve_drive_interstitial(page: str, base_url: str) -> Optional[str]:
    """O Google Drive devolve uma página HTML de "arquivo grande, sem antivírus"
    em vez do arquivo. Esta função monta a URL real a partir do formulário dela."""
    form = re.search(r'<form[^>]*id="download-form"[^>]*action="([^"]+)"', page)
    action = html.unescape(form.group(1)) if form else "https://drive.usercontent.google.com/download"
    params = []
    for m in re.finditer(r'<input[^>]*type="hidden"[^>]*name="([^"]+)"[^>]*value="([^"]*)"', page):
        params.append(f"{quote(m.group(1), safe='')}={quote(html.unescape(m.group(2)), safe='')}")
    if params:
        return urljoin(base_url, action) + "?" + "&".join(params)
    token = re.search(r"confirm=([A-Za-z0-9_-]+)", page)
    if token:
        sep = "&" if "?" in base_url else "?"
        return f"{base_url}{sep}confirm={token.group(1)}"
    return None


class Downloader:
    def __init__(self) -> None:
        self._running = threading.Event()
        self._running.set()
        self._cancel = threading.Event()

    def pause(self) -> None:
        self._running.clear()

    def resume(self) -> None:
        self._running.set()

    @property
    def paused(self) -> bool:
        return not self._running.is_set()

    def cancel(self) -> None:
        self._cancel.set()
        self._running.set()

    def download(self, url: str, dest: Path, progress: Optional[ProgressCb] = None, sha256: str = "") -> Path:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        session = requests.Session()
        session.headers["User-Agent"] = app_config.USER_AGENT
        try:
            resp = self._open(session, url)
            total = int(resp.headers.get("Content-Length") or -1)
            h = hashlib.sha256()
            done = 0
            last = 0.0
            with resp, open(part, "wb") as out:
                for chunk in resp.iter_content(chunk_size=256 * 1024):
                    while not self._running.is_set():
                        if self._cancel.is_set():
                            break
                        time.sleep(0.15)
                    if self._cancel.is_set():
                        raise DownloadCancelled("Download cancelado.")
                    if not chunk:
                        continue
                    out.write(chunk)
                    h.update(chunk)
                    done += len(chunk)
                    now = time.monotonic()
                    if progress and now - last > 0.1:
                        progress(done, total)
                        last = now
            if progress:
                progress(done, total)
            if total > 0 and done != total:
                raise DownloadError("O download terminou incompleto. Tente novamente.")
            if sha256 and h.hexdigest().lower() != sha256.lower():
                raise DownloadError(
                    "O arquivo baixado não confere com o esperado (SHA-256 diferente). "
                    "Pode estar corrompido ou o catálogo está desatualizado."
                )
            part.replace(dest)
            return dest
        except requests.RequestException as e:
            raise DownloadError(f"Falha de rede ao baixar: {e}") from e
        finally:
            session.close()
            if part.exists():
                try:
                    part.unlink()
                except OSError:
                    pass

    def _open(self, session: requests.Session, url: str) -> requests.Response:
        for attempt in range(2):
            resp = session.get(url, stream=True, timeout=(10, 30), allow_redirects=True)
            resp.raise_for_status()
            if "text/html" not in resp.headers.get("Content-Type", ""):
                return resp
            page = resp.text
            resp.close()
            nxt = resolve_drive_interstitial(page, resp.url) if attempt == 0 else None
            if not nxt:
                raise DownloadError(
                    "O servidor devolveu uma página em vez do arquivo (link quebrado, ou o Google Drive "
                    "bloqueou por excesso de downloads). Tente novamente mais tarde."
                )
            url = nxt
        raise DownloadError("Não foi possível obter o arquivo.")


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()
