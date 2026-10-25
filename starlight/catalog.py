"""Catálogo de jogos/traduções (manifest.json).

O instalador NÃO tem a lista de jogos fixa no código. Ele baixa o manifest.json
do GitHub ao abrir; se estiver sem internet usa a última cópia salva; e se
nunca baixou nada usa a cópia que vem dentro do próprio instalador.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import requests

from . import app_config, paths

SUPPORTED_SCHEMA = 1


@dataclass
class Version:
    id: str
    label: str
    version: str
    url: str = ""
    sha256: str = ""
    size: int = 0
    notes: str = ""
    available: bool = False
    options: Optional[list[Option]] = None  # None = usa as opções do jogo


@dataclass
class Choice:
    """Uma escolha de uma opção. Se `has_pkg`, ela traz um .zip extra que é
    aplicado em cima da tradução base."""
    id: str
    label: str
    has_pkg: bool = False
    url: str = ""
    sha256: str = ""
    size: int = 0
    version: str = "1"

    @property
    def available(self) -> bool:
        return (not self.has_pkg) or bool(self.url)


@dataclass
class Option:
    id: str
    type: str  # "choice" (menu suspenso) | "checkbox"
    label: str
    note: str = ""
    default: str = ""
    choices: list[Choice] = field(default_factory=list)

    def choice(self, cid: str) -> Optional[Choice]:
        return next((c for c in self.choices if c.id == cid), None)


@dataclass
class Game:
    id: str
    name: str
    description: str = ""
    icon: str = ""
    banner: str = ""
    logo: str = ""
    banner_offset: tuple[int, int] = (0, 0)
    status_label: str = "Em andamento"
    status_color: str = "#e74c3c"
    pct_translated: float = 0.0
    pct_reviewed: float = 0.0
    credits_translation: list[str] = field(default_factory=list)
    credits_design: list[str] = field(default_factory=list)
    credits_tools: list[str] = field(default_factory=list)
    credits_thanks: list[str] = field(default_factory=list)
    required_files: list[str] = field(default_factory=list)
    versions: list[Version] = field(default_factory=list)
    default_version: str = ""
    options: list[Option] = field(default_factory=list)

    @property
    def has_credits(self) -> bool:
        return any([self.credits_translation, self.credits_design, self.credits_tools, self.credits_thanks])

    @property
    def available(self) -> bool:
        return any(v.available for v in self.versions)

    def options_for(self, v: Optional[Version]) -> list[Option]:
        return v.options if (v is not None and v.options is not None) else self.options

    def version_by_id(self, vid: str) -> Optional[Version]:
        return next((v for v in self.versions if v.id == vid), None)

    def default(self) -> Optional[Version]:
        return self.version_by_id(self.default_version) or (self.versions[-1] if self.versions else None)


@dataclass
class Catalog:
    games: list[Game]
    updated: str = ""
    min_installer: str = ""
    source: str = "bundled"  # remote | cache | bundled

    def game(self, gid: str) -> Optional[Game]:
        return next((g for g in self.games if g.id == gid), None)


def _f(x, default=0.0) -> float:
    try:
        return max(0.0, min(1.0, float(x)))
    except (TypeError, ValueError):
        return default


def _parse_options(raw) -> list[Option]:
    out: list[Option] = []
    for o in raw or []:
        if not o.get("id"):
            continue
        typ = "checkbox" if o.get("type") == "checkbox" else "choice"
        if typ == "checkbox":
            on = Choice(
                id="on", label="Ativado", has_pkg="url" in o, url=(o.get("url") or "").strip(),
                sha256=(o.get("sha256") or "").strip().lower(), size=int(o.get("size") or 0),
                version=str(o.get("version") or "1"),
            )
            choices = [Choice(id="off", label="Desativado"), on]
            default = "on" if o.get("default") else "off"
        else:
            choices = [
                Choice(
                    id=str(c["id"]), label=str(c.get("label") or c["id"]), has_pkg="url" in c,
                    url=(c.get("url") or "").strip(), sha256=(c.get("sha256") or "").strip().lower(),
                    size=int(c.get("size") or 0), version=str(c.get("version") or "1"),
                )
                for c in o.get("choices", []) if c.get("id")
            ]
            if not choices:
                continue
            default = str(o.get("default") or choices[0].id)
            if not any(c.id == default for c in choices):
                default = choices[0].id
        out.append(Option(id=str(o["id"]), type=typ, label=str(o.get("label") or o["id"]), note=str(o.get("note") or ""), default=default, choices=choices))
    return out


def default_options(opts: list[Option]) -> dict[str, str]:
    return {o.id: o.default for o in opts}


def normalize_options(opts: list[Option], chosen: Optional[dict]) -> dict[str, str]:
    """Completa com os padrões e descarta valores que não existem mais no catálogo."""
    out = default_options(opts)
    for o in opts:
        v = (chosen or {}).get(o.id)
        if v is not None and o.choice(str(v)):
            out[o.id] = str(v)
    return out


def selected_choices(opts: list[Option], chosen: dict[str, str]) -> list[tuple[Option, Choice]]:
    out = []
    for o in opts:
        c = o.choice(chosen.get(o.id, o.default))
        if c:
            out.append((o, c))
    return out


def signature(version: "Version", opts: list[Option], chosen: dict[str, str]) -> str:
    """Identifica exatamente o que está instalado (versão + opções + versão de cada pacote extra)."""
    parts = [version.version]
    for o, c in selected_choices(opts, chosen):
        parts.append(f"{o.id}={c.id}" + (f"@{c.version}" if c.has_pkg else ""))
    return "|".join(parts)


def parse(data: dict, source: str = "bundled") -> Catalog:
    if not isinstance(data, dict) or int(data.get("schema", 0)) > SUPPORTED_SCHEMA:
        raise ValueError("manifest com formato mais novo do que este instalador entende")
    games: list[Game] = []
    for g in data.get("games", []):
        if not g.get("id") or not g.get("name"):
            continue
        st = g.get("status") or {}
        pr = g.get("progress") or {}
        cr = g.get("credits") or {}
        vers: list[Version] = []
        for v in g.get("versions", []):
            url = (v.get("url") or "").strip()
            vers.append(
                Version(
                    id=str(v.get("id") or "v1"),
                    label=str(v.get("label") or v.get("id") or "V1"),
                    version=str(v.get("version") or "1"),
                    url=url,
                    sha256=(v.get("sha256") or "").strip().lower(),
                    size=int(v.get("size") or 0),
                    notes=str(v.get("notes") or ""),
                    available=bool(url) and bool(v.get("available", True)),
                    options=_parse_options(v["options"]) if "options" in v else None,
                )
            )
        off = g.get("banner_offset") or [0, 0]
        games.append(
            Game(
                id=str(g["id"]),
                name=str(g["name"]),
                description=str(g.get("description") or ""),
                icon=str(g.get("icon") or ""),
                banner=str(g.get("banner") or ""),
                logo=str(g.get("logo") or ""),
                banner_offset=(int(off[0]), int(off[1])) if len(off) == 2 else (0, 0),
                status_label=str(st.get("label") or "Em andamento"),
                status_color=str(st.get("color") or "#e74c3c"),
                pct_translated=_f(pr.get("translated")),
                pct_reviewed=_f(pr.get("reviewed")),
                credits_translation=list(cr.get("translation") or []),
                credits_design=list(cr.get("design") or []),
                credits_tools=list(cr.get("tools") or []),
                credits_thanks=list(cr.get("thanks") or []),
                required_files=list(g.get("required_files") or []),
                versions=vers,
                default_version=str(g.get("default_version") or ""),
                options=_parse_options(g.get("options")),
            )
        )
    return Catalog(games=games, updated=str(data.get("updated") or ""), min_installer=str(data.get("min_installer") or ""), source=source)


def _cache_file() -> Path:
    return paths.cache_dir() / "manifest_cache.json"


def load_bundled() -> Catalog:
    data = json.loads(paths.resource("catalog/manifest.json").read_text(encoding="utf-8"))
    return parse(data, "bundled")


def load(url: Optional[str] = None, timeout: float = 8.0) -> Catalog:
    """remote -> cache -> bundled. Nunca levanta exceção por falta de internet."""
    url = url or app_config.CATALOG_URL
    if app_config.is_configured() or url != app_config.CATALOG_URL:
        try:
            r = requests.get(url, timeout=timeout, headers={"User-Agent": app_config.USER_AGENT, "Cache-Control": "no-cache"})
            r.raise_for_status()
            data = r.json()
            cat = parse(data, "remote")
            _cache_file().write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            return cat
        except Exception:
            pass
    try:
        return parse(json.loads(_cache_file().read_text(encoding="utf-8")), "cache")
    except Exception:
        return load_bundled()


# --- imagens remotas (ícone/banner/logo podem ser URLs) ----------------------- #
def image_cache_path(url: str) -> Path:
    ext = Path(url.split("?")[0]).suffix or ".img"
    return paths.cache_dir() / "images" / (hashlib.sha1(url.encode()).hexdigest() + ext)


def local_image(ref: str) -> Optional[Path]:
    """Caminho local de uma imagem do catálogo, ou None se ainda não está disponível."""
    if not ref:
        return None
    if ref.startswith(("http://", "https://")):
        p = image_cache_path(ref)
        return p if p.exists() else None
    p = paths.resource(ref)
    return p if p.exists() else None


def fetch_image(ref: str, timeout: float = 15.0) -> Optional[Path]:
    if not ref.startswith(("http://", "https://")):
        return local_image(ref)
    p = image_cache_path(ref)
    if p.exists():
        return p
    try:
        r = requests.get(ref, timeout=timeout, headers={"User-Agent": app_config.USER_AGENT})
        r.raise_for_status()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(r.content)
        return p
    except Exception:
        return None
