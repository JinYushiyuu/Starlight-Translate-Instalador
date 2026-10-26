"""Consulta os projetos e as imagens traduzidas da Starlight Translate."""

import ast
import json
import re
from urllib.parse import quote, urljoin

import requests


SITE_BASE = "https://starlight-translate.com.br/"
DATA_JS_URL = urljoin(SITE_BASE, "js/dados.js")
TIMEOUT = 10
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) Starlight-Translate-Instalador/2.0"
)
IMAGE_KEYS = ("imagens", "images", "screenshots", "capturas")

# Motivo da última falha de get_project(), para a interface mostrar ao usuário.
LAST_ERROR = ""


def _key_pattern(name: str) -> str:
    """Chave JS com ou sem aspas: slug: / "slug": / 'slug':"""
    return rf"""(?<![\w$])["']?{re.escape(name)}["']?\s*:\s*"""


def safe_url(url: str) -> str:
    """Escapa espaços/acentos sem duplicar o que já está escapado."""
    return quote(url, safe=":/?&=%#+@,;~!$'()*[]")


def _headers(accept: str) -> dict:
    return {"User-Agent": USER_AGENT, "Accept": accept}


def _download_data() -> str | None:
    """Baixa o arquivo dados.js publicado no site.

    Usa requests (com os certificados do certifi embutidos no executável); o
    urllib falha em HTTPS dentro do .exe/binário empacotado.
    """
    global LAST_ERROR
    try:
        response = requests.get(
            DATA_JS_URL,
            timeout=TIMEOUT,
            headers={**_headers("text/javascript, application/javascript, */*"), "Cache-Control": "no-cache"},
        )
        if response.status_code != 200:
            LAST_ERROR = f"o site respondeu HTTP {response.status_code} ao baixar dados.js"
            return None
        return response.content.decode("utf-8-sig")
    except requests.RequestException as exc:
        LAST_ERROR = f"não consegui baixar dados.js ({type(exc).__name__}: {exc})"
    except UnicodeError as exc:
        LAST_ERROR = f"dados.js com codificação inesperada ({exc})"
    return None


def download_image(url: str) -> bytes:
    """Baixa uma imagem do site; levanta exceção com o motivo se falhar."""
    response = requests.get(url, timeout=TIMEOUT, headers=_headers("image/*,*/*"))
    response.raise_for_status()
    ctype = response.headers.get("Content-Type", "")
    if "text/html" in ctype:
        raise ValueError("o site devolveu uma página HTML no lugar da imagem")
    return response.content


def _decode_js_string(value: str) -> str | None:
    """Converte uma string JavaScript simples em texto Python."""
    value = value.strip()
    try:
        if value.startswith('"'):
            return json.loads(value)
        if value.startswith("'"):
            result = ast.literal_eval(value)
            return result if isinstance(result, str) else None
    except (ValueError, SyntaxError):
        return None
    return None


def _find_matching(source: str, start: int, opening: str, closing: str) -> int:
    """Localiza o fechamento de [] ou {}, ignorando strings e comentários."""
    depth = 0
    quote = None
    escaped = False
    line_comment = False
    block_comment = False
    i = start
    while i < len(source):
        char = source[i]
        nxt = source[i + 1] if i + 1 < len(source) else ""
        if line_comment:
            if char == "\n":
                line_comment = False
            i += 1
            continue
        if block_comment:
            if char == "*" and nxt == "/":
                block_comment = False
                i += 2
            else:
                i += 1
            continue
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            i += 1
            continue
        if char == "/" and nxt == "/":
            line_comment = True
            i += 2
            continue
        if char == "/" and nxt == "*":
            block_comment = True
            i += 2
            continue
        if char in ("'", '"', "`"):
            quote = char
        elif char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _extract_string_property(source: str, name: str) -> str:
    """Lê uma propriedade textual simples, como title ou youtubeUrl."""
    match = re.search(_key_pattern(name), source)
    if not match:
        return ""
    start = match.end()
    while start < len(source) and source[start].isspace():
        start += 1
    if start >= len(source) or source[start] not in ("'", '"'):
        return ""
    quote = source[start]
    escaped = False
    for end in range(start + 1, len(source)):
        char = source[end]
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == quote:
            value = _decode_js_string(source[start:end + 1])
            return value or ""
    return ""


def _extract_images(source: str) -> list[str]:
    """Lê a lista de imagens da propriedade imagens."""
    match = None
    for key in IMAGE_KEYS:
        match = re.search(_key_pattern(key) + r"\[", source)
        if match:
            break
    if not match:
        return []
    start = source.find("[", match.start())
    end = _find_matching(source, start, "[", "]")
    if end < 0:
        return []
    array_source = source[start + 1:end]
    images = []
    i = 0
    while i < len(array_source):
        char = array_source[i]
        if char in ("'", '"'):
            quote = char
            start_string = i
            escaped = False
            i += 1
            while i < len(array_source):
                current = array_source[i]
                if escaped:
                    escaped = False
                elif current == "\\":
                    escaped = True
                elif current == quote:
                    value = _decode_js_string(array_source[start_string:i + 1])
                    if value:
                        images.append(value)
                    break
                i += 1
        i += 1
    return images


def get_project(slug: str) -> dict | None:
    """Retorna título, imagens e trailer de um projeto pelo slug.

    Em caso de falha devolve None e deixa o motivo em LAST_ERROR.
    """
    global LAST_ERROR
    LAST_ERROR = ""
    if not isinstance(slug, str) or not slug.strip():
        LAST_ERROR = "o jogo não tem website_slug"
        return None
    source = _download_data()
    if not source:
        LAST_ERROR = LAST_ERROR or "dados.js veio vazio"
        return None
    slug_pattern = re.compile(_key_pattern("slug") + r"(['\"])" + re.escape(slug) + r"\1")
    match = slug_pattern.search(source)
    if not match:
        LAST_ERROR = f"o slug '{slug}' não existe no dados.js do site"
        return None
    start = source.rfind("{", 0, match.start())
    if start < 0:
        LAST_ERROR = "não consegui isolar o projeto dentro do dados.js"
        return None
    end = _find_matching(source, start, "{", "}")
    if end < 0:
        LAST_ERROR = "não consegui isolar o projeto dentro do dados.js"
        return None
    project_source = source[start:end + 1]
    found_slug = _extract_string_property(project_source, "slug")
    if found_slug != slug:
        LAST_ERROR = "o projeto encontrado tem outro slug"
        return None
    images = _extract_images(project_source)
    if not images:
        LAST_ERROR = "o projeto existe no site, mas não tem imagens cadastradas"
    return {
        "slug": found_slug,
        "title": _extract_string_property(project_source, "title"),
        "images": [safe_url(urljoin(SITE_BASE, image)) for image in images if image.strip()],
        "youtube_url": _extract_string_property(project_source, "youtubeUrl"),
    }
