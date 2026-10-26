"""Catálogo de jogos/traduções (manifest.json).

O instalador NÃO tem a lista de jogos fixa no código. Ele baixa o manifest.json
do GitHub ao abrir; se estiver sem internet usa a última cópia salva; e se
nunca baixou nada usa a cópia que vem dentro do próprio instalador.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import quote, unquote
from concurrent.futures import ThreadPoolExecutor, as_completed

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
    github: str = ""  # "dono/repositorio": a Release mais recente define version/url/sha256/size
    github_asset: str = ""  # padrão do nome do .zip da Release (ex.: "*PTBR*.zip"); vazio = o .zip da Release


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
    manifest_url: str = ""
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
    website_slug: str = ""

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
                    github=normalize_github_repo(v.get("github")),
                    github_asset=str(v.get("github_asset") or "").strip(),
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
                manifest_url=str(g.get("manifest_url") or "").strip(),
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
                website_slug=str(g.get("website_slug") or "").strip(),
            )
        )
    return Catalog(games=games, updated=str(data.get("updated") or ""), min_installer=str(data.get("min_installer") or ""), source=source)


def _cache_file() -> Path:
    return paths.cache_dir() / "manifest_cache.json"


def load_bundled() -> Catalog:
    data = json.loads(paths.resource("catalog/manifest.json").read_text(encoding="utf-8"))
    return parse(data, "bundled")


def _translation_manifest_cache(game_id: str) -> Path:
    safe_id = "".join(c if c.isalnum() or c in "-_." else "_" for c in game_id)
    return paths.cache_dir() / "translation_manifests" / f"{safe_id}.json"


def _apply_translation_manifest(game: Game, data: dict) -> bool:
    """Mescla versões publicadas no manifesto individual deste jogo.

    Formato preferido: {schema, id, name, default_version, versions:[...]},
    reaproveitando o formato de versões que o catálogo já usa. Também aceita
    o formato simples legado com version/download_url na raiz.
    """
    if not isinstance(data, dict) or int(data.get("schema", 1)) > SUPPORTED_SCHEMA:
        return False
    if str(data.get("id") or "") != game.id:
        return False

    raw_versions = data.get("versions")
    if not isinstance(raw_versions, list):
        # Compatibilidade com o exemplo inicial de manifesto de versão única.
        if data.get("version") and (data.get("download_url") or data.get("url")):
            raw_versions = [{
                "id": str(data.get("version_id") or game.default_version or "v1"),
                "label": str(data.get("label") or "V1"),
                "version": data.get("version"),
                "url": data.get("download_url") or data.get("url"),
                "sha256": data.get("sha256", ""),
                "size": data.get("size", 0),
                "notes": data.get("notes", ""),
                "options": data.get("options"),
            }]
        else:
            return False

    seen: set[str] = set()
    for raw in raw_versions:
        if not isinstance(raw, dict):
            continue
        vid = str(raw.get("id") or "v1").strip()
        version_text = str(raw.get("version") or "").strip()
        url = str(raw.get("url") or raw.get("download_url") or "").strip()
        if not vid or not version_text or not url.startswith(("https://", "http://")):
            continue
        seen.add(vid)
        version = game.version_by_id(vid)
        if version is None:
            version = Version(id=vid, label=str(raw.get("label") or vid), version=version_text)
            game.versions.append(version)
        version.label = str(raw.get("label") or version.label or vid)
        version.version = version_text
        version.url = url
        version.sha256 = str(raw.get("sha256") or "").strip().lower()
        try:
            version.size = max(0, int(raw.get("size") or 0))
        except (TypeError, ValueError):
            version.size = 0
        version.notes = str(raw.get("notes") or "")
        version.available = bool(raw.get("available", True))
        if "options" in raw:
            version.options = _parse_options(raw["options"])

    if not seen:
        return False
    default_id = str(data.get("default_version") or "").strip()
    if default_id and game.version_by_id(default_id):
        game.default_version = default_id
    elif game.default_version not in seen:
        game.default_version = next(iter(seen))
    return True

def _fetch_translation_manifest(game: Game, timeout: float) -> tuple[str, Optional[dict], str]:
    """Retorna (game_id, manifesto, fonte), usando cache se a rede falhar."""
    cache_path = _translation_manifest_cache(game.id)
    if game.manifest_url:
        try:
            response = requests.get(
                game.manifest_url, timeout=timeout,
                headers={"User-Agent": app_config.USER_AGENT, "Cache-Control": "no-cache"},
            )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict) or str(data.get("id") or "") != game.id:
                raise ValueError("O id do manifesto não corresponde ao jogo")
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            return game.id, data, "remote"
        except Exception:
            pass
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and str(data.get("id") or "") == game.id:
            return game.id, data, "cache"
    except (OSError, ValueError):
        pass
    return game.id, None, "bundled"


def refresh_translation_manifests(cat: Catalog, timeout: float = 5.0) -> Catalog:
    """Consulta os manifestos individuais configurados no catálogo embutido.

    Os pedidos são paralelos para que vários repositórios indisponíveis não
    deixem a abertura do programa lenta. Cada manifesto pode ser servido por
    https://raw.githubusercontent.com/USUARIO/REPO/main/manifest.json.
    """
    targets = [g for g in cat.games if g.manifest_url]
    if not targets:
        return cat
    sources: set[str] = set()
    with ThreadPoolExecutor(max_workers=min(8, len(targets))) as pool:
        futures = [pool.submit(_fetch_translation_manifest, g, timeout) for g in targets]
        by_id = {g.id: g for g in targets}
        for future in as_completed(futures):
            try:
                game_id, data, source = future.result()
                if data is not None and _apply_translation_manifest(by_id[game_id], data):
                    sources.add(source)
            except Exception:
                continue
    if "remote" in sources:
        cat.source = "individual-remote"
    elif "cache" in sources:
        cat.source = "individual-cache"
    return cat


# --- versão mais recente direto do GitHub (API de Releases) ------------------- #
GITHUB_API = "https://api.github.com"
_GITHUB_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def normalize_github_repo(value) -> str:
    """Aceita "dono/repo" ou o link do repositório e devolve "dono/repo" ("" se inválido)."""
    text = str(value or "").strip()
    text = re.sub(r"^https?://(www\.)?github\.com/", "", text, flags=re.I).strip("/")
    text = re.sub(r"\.git$", "", text, flags=re.I)
    text = "/".join(text.split("/")[:2])
    return text if _GITHUB_REPO_RE.match(text) else ""


def _github_cache(repo: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in repo)
    return paths.cache_dir() / "github_releases" / f"{safe}.json"


def _read_github_cache(repo: str) -> dict:
    try:
        data = json.loads(_github_cache(repo).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _slim_release(raw: dict) -> dict:
    return {
        "tag": str(raw.get("tag_name") or ""),
        "assets": [
            {
                "name": str(a.get("name") or ""),
                "size": int(a.get("size") or 0),
                "url": str(a.get("browser_download_url") or ""),
                "digest": str(a.get("digest") or ""),
            }
            for a in raw.get("assets") or []
            if isinstance(a, dict)
        ],
    }


def _is_exact_name(pattern: str) -> bool:
    return bool(pattern) and not any(c in pattern for c in "*?[")


def _release_via_web(repo: str, asset_name: str, timeout: float) -> Optional[dict]:
    """Plano B sem a API (que tem limite de 60 pedidos/hora por IP sem login).

    github.com/dono/repo/releases/latest redireciona para .../releases/tag/<tag>; com o
    NOME EXATO do .zip (campo github_asset) dá para montar o link de download. Não traz
    tamanho nem sha256.
    """
    try:
        r = requests.head(
            f"https://github.com/{repo}/releases/latest",
            timeout=timeout, allow_redirects=False, headers={"User-Agent": app_config.USER_AGENT},
        )
    except requests.RequestException:
        return None
    location = r.headers.get("Location", "")
    if r.status_code not in (301, 302, 303, 307, 308) or "/releases/tag/" not in location:
        return None
    tag = unquote(location.split("/releases/tag/", 1)[1].split("?")[0].strip("/"))
    if not tag:
        return None
    url = f"https://github.com/{repo}/releases/download/{quote(tag, safe='')}/{quote(asset_name)}"
    return {"tag": tag, "assets": [{"name": asset_name, "size": 0, "url": url, "digest": ""}]}


def _fetch_github_release(repo: str, timeout: float, asset_hint: str = "") -> tuple[str, Optional[dict], str]:
    """Última Release publicada de `repo`. Retorna (repo, release, fonte).

    Usa ETag: se nada mudou o GitHub responde 304, que não gasta o limite da API
    (60 pedidos/hora sem login). Sem rede ou com limite estourado, usa a cópia salva.
    """
    cached = _read_github_cache(repo)
    headers = {
        "User-Agent": app_config.USER_AGENT,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if cached.get("etag") and cached.get("release"):
        headers["If-None-Match"] = cached["etag"]
    try:
        r = requests.get(f"{GITHUB_API}/repos/{repo}/releases/latest", timeout=timeout, headers=headers)
        if r.status_code == 304 and cached.get("release"):
            return repo, cached["release"], "cache"
        if r.status_code == 200:
            release = _slim_release(r.json())
            cache = _github_cache(repo)
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps({"etag": r.headers.get("ETag", ""), "release": release}), encoding="utf-8")
            return repo, release, "remote"
        if r.status_code == 404:  # repositório ainda não tem nenhuma Release
            return repo, None, "none"
        if r.status_code in (403, 429) and _is_exact_name(asset_hint):  # limite da API estourado
            web = _release_via_web(repo, asset_hint, timeout)
            if web:
                return repo, web, "web"
    except (requests.RequestException, ValueError):
        pass
    if cached.get("release"):  # sem rede, limite da API, erro do GitHub...
        return repo, cached["release"], "cache"
    return repo, None, "none"


def _pick_release_asset(release: dict, pattern: str = "") -> Optional[dict]:
    zips = [a for a in release.get("assets", []) if a.get("name", "").lower().endswith(".zip") and a.get("url")]
    if pattern:
        zips = [a for a in zips if fnmatch.fnmatch(a["name"].lower(), pattern.lower())]
    return zips[0] if zips else None


def _apply_github_release(version: Version, release: dict) -> bool:
    asset = _pick_release_asset(release, version.github_asset)
    tag = str(release.get("tag") or "").strip()
    if not asset or not tag:
        return False
    version.version = re.sub(r"^[vV](?=\d)", "", tag)  # tag "v1.2" -> versão "1.2"
    version.url = asset["url"]
    version.size = int(asset.get("size") or 0)
    digest = str(asset.get("digest") or "").lower()
    version.sha256 = digest[len("sha256:"):] if digest.startswith("sha256:") else ""
    version.available = True
    return True


def refresh_github_releases(cat: Catalog, timeout: float = 5.0) -> Catalog:
    """Atualiza version/url/sha256/size das versões que têm `"github": "dono/repo"`.

    Pedidos em paralelo (um por repositório). Falha de um repositório não afeta os outros.
    """
    targets = [v for g in cat.games for v in g.versions if v.github]
    if not targets:
        return cat
    repos = sorted({v.github for v in targets})
    hints = {r: next((v.github_asset for v in targets if v.github == r and _is_exact_name(v.github_asset)), "") for r in repos}
    releases: dict[str, Optional[dict]] = {}
    sources: set[str] = set()
    with ThreadPoolExecutor(max_workers=min(8, len(repos))) as pool:
        for future in as_completed([pool.submit(_fetch_github_release, r, timeout, hints[r]) for r in repos]):
            try:
                repo, release, source = future.result()
            except Exception:
                continue
            releases[repo] = release
            sources.add(source)
    applied = False
    for v in targets:
        release = releases.get(v.github)
        if release and _apply_github_release(v, release):
            applied = True
    if applied and cat.source == "bundled":
        cat.source = "github" if sources & {"remote", "web"} else "github-cache"
    return cat


def load(url: Optional[str] = None, timeout: float = 8.0) -> Catalog:
    """
    Sem URL explícita: usa a lista embutida de jogos e consulta o manifesto
    individual de cada tradução. URL explícita mantém compatibilidade com o
    formato antigo de catálogo remoto e com os testes de fallback/cache.
    """
    if url is None:
        cat = load_bundled()
        for refresh in (refresh_translation_manifests, refresh_github_releases):
            try:
                cat = refresh(cat, timeout=min(timeout, 5.0))
            except Exception:
                continue  # uma fonte com problema não derruba as outras
        return cat

    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": app_config.USER_AGENT, "Cache-Control": "no-cache"})
        r.raise_for_status()
        data = r.json()
        cat = parse(data, "remote")
        _cache_file().parent.mkdir(parents=True, exist_ok=True)
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
