"""Consulta os projetos e as imagens traduzidas da Starlight Translate."""

import ast
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


SITE_BASE = "https://starlight-translate.com.br/"
DATA_JS_URL = urljoin(SITE_BASE, "js/dados.js")
TIMEOUT = 10


def _download_data() -> str | None:
    """Baixa o arquivo dados.js publicado no site."""
    request = Request(
        DATA_JS_URL,
        headers={
            "User-Agent": "Starlight-Translate-Instalador/2.0",
            "Accept": "text/javascript, application/javascript, */*",
        },
    )
    try:
        with urlopen(request, timeout=TIMEOUT) as response:
            return response.read().decode("utf-8-sig")
    except (HTTPError, URLError, TimeoutError, OSError, UnicodeError):
        return None


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
    match = re.search(rf"\b{re.escape(name)}\s*:\s*", source)
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
    match = re.search(r"\bimagens\s*:\s*\[", source)
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
    """Retorna título, imagens e trailer de um projeto pelo slug."""
    if not isinstance(slug, str) or not slug.strip():
        return None
    source = _download_data()
    if not source:
        return None
    slug_pattern = re.compile(r"\bslug\s*:\s*(['\"])" + re.escape(slug) + r"\1")
    match = slug_pattern.search(source)
    if not match:
        return None
    start = source.rfind("{", 0, match.start())
    if start < 0:
        return None
    end = _find_matching(source, start, "{", "}")
    if end < 0:
        return None
    project_source = source[start:end + 1]
    found_slug = _extract_string_property(project_source, "slug")
    if found_slug != slug:
        return None
    images = _extract_images(project_source)
    return {
        "slug": found_slug,
        "title": _extract_string_property(project_source, "title"),
        "images": [urljoin(SITE_BASE, image) for image in images if image.strip()],
        "youtube_url": _extract_string_property(project_source, "youtubeUrl"),
    }
