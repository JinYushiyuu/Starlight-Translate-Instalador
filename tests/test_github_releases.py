"""Versão mais recente da tradução direto da API de Releases do GitHub."""

import pytest
import requests

from starlight import catalog

SHA = "ab" * 32


def release(tag="v1.2", assets=None):
    return {
        "tag_name": tag,
        "assets": assets
        if assets is not None
        else [
            {"name": "LEIAME.txt", "size": 10, "browser_download_url": "https://gh/x/LEIAME.txt"},
            {"name": "Traducao-PTBR.zip", "size": 4321, "digest": f"sha256:{SHA}",
             "browser_download_url": f"https://github.com/o/r/releases/download/{tag}/Traducao-PTBR.zip"},
        ],
    }


class Resp:
    def __init__(self, status=200, body=None, etag='W/"1"'):
        self.status_code, self._body, self.headers = status, body, {"ETag": etag}

    def json(self):
        return self._body


@pytest.fixture(autouse=True)
def limpa_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(catalog.paths, "cache_dir", lambda: tmp_path)


def game_com_github(repo="o/r", asset=""):
    cat = catalog.load_bundled()
    g = cat.game("atelier-ryza-1")
    v = g.default()
    v.github, v.github_asset = repo, asset
    return cat, g, v


def test_normaliza_repositorio():
    n = catalog.normalize_github_repo
    assert n("JinYushiyuu/Ryza-PTBR") == "JinYushiyuu/Ryza-PTBR"
    assert n("https://github.com/JinYushiyuu/Ryza-PTBR.git") == "JinYushiyuu/Ryza-PTBR"
    assert n("https://github.com/JinYushiyuu/Ryza-PTBR/releases/latest") == "JinYushiyuu/Ryza-PTBR"
    assert n("") == "" and n("so-um-nome") == "" and n(None) == ""


def test_parse_le_campo_github():
    data = {"schema": 1, "games": [{"id": "x", "name": "X", "versions": [
        {"id": "v1", "version": "1", "github": "https://github.com/o/r", "github_asset": "*.zip"}]}]}
    v = catalog.parse(data).game("x").versions[0]
    assert v.github == "o/r" and v.github_asset == "*.zip" and not v.available


def test_release_nova_define_versao_url_sha_e_tamanho(monkeypatch):
    chamadas = []
    monkeypatch.setattr(catalog.requests, "get",
                        lambda url, **k: chamadas.append((url, k["headers"])) or Resp(200, release("v1.2")))
    cat, g, v = game_com_github()
    catalog.refresh_github_releases(cat)
    assert v.version == "1.2"  # o "v" da tag some
    assert v.url.endswith("/v1.2/Traducao-PTBR.zip")
    assert v.sha256 == SHA and v.size == 4321 and v.available
    assert chamadas[0][0] == "https://api.github.com/repos/o/r/releases/latest"
    assert cat.source == "github"


def test_etag_304_usa_a_copia_salva(monkeypatch):
    monkeypatch.setattr(catalog.requests, "get", lambda *a, **k: Resp(200, release("v2.0")))
    cat, _, _ = game_com_github()
    catalog.refresh_github_releases(cat)

    vistos = {}

    def segunda(url, **k):
        vistos.update(k["headers"])
        return Resp(304)

    monkeypatch.setattr(catalog.requests, "get", segunda)
    cat2, _, v2 = game_com_github()
    catalog.refresh_github_releases(cat2)
    assert vistos.get("If-None-Match") == 'W/"1"'
    assert v2.version == "2.0" and cat2.source == "github-cache"


def test_sem_rede_ou_limite_estourado_usa_cache_e_sem_cache_mantem_o_catalogo(monkeypatch):
    cat, _, v = game_com_github()
    url_antiga, versao_antiga = v.url, v.version

    def sem_rede(*a, **k):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(catalog.requests, "get", sem_rede)
    catalog.refresh_github_releases(cat)  # nunca baixou nada: não quebra
    assert (v.url, v.version) == (url_antiga, versao_antiga)

    monkeypatch.setattr(catalog.requests, "get", lambda *a, **k: Resp(200, release("v3")))
    catalog.refresh_github_releases(game_com_github()[0])
    monkeypatch.setattr(catalog.requests, "get", lambda *a, **k: Resp(403))  # limite da API
    cat3, _, v3 = game_com_github()
    catalog.refresh_github_releases(cat3)
    assert v3.version == "3"


def test_limite_da_api_estourado_usa_o_redirecionamento_do_github(monkeypatch):
    monkeypatch.setattr(catalog.requests, "get", lambda *a, **k: Resp(403))
    vistos = []

    def head(url, **k):
        vistos.append(url)
        r = Resp(302)
        r.headers = {"Location": "https://github.com/o/r/releases/tag/31%2F05%2F2026"}
        return r

    monkeypatch.setattr(catalog.requests, "head", head)
    cat, _, v = game_com_github(asset="Traducao-PTBR.zip")
    catalog.refresh_github_releases(cat)
    assert vistos == ["https://github.com/o/r/releases/latest"]
    assert v.version == "31/05/2026"
    assert v.url == "https://github.com/o/r/releases/download/31%2F05%2F2026/Traducao-PTBR.zip"
    assert v.available and cat.source == "github"


def test_limite_estourado_sem_nome_exato_do_zip_mantem_o_catalogo(monkeypatch):
    monkeypatch.setattr(catalog.requests, "get", lambda *a, **k: Resp(403))
    monkeypatch.setattr(catalog.requests, "head", lambda *a, **k: 1 / 0)  # nem deve ser chamado
    cat, _, v = game_com_github(asset="*PTBR*.zip")
    antes = (v.version, v.url)
    catalog.refresh_github_releases(cat)
    assert (v.version, v.url) == antes


def test_repositorio_sem_release_404_mantem_o_que_ja_existia(monkeypatch):
    monkeypatch.setattr(catalog.requests, "get", lambda *a, **k: Resp(404))
    cat, _, v = game_com_github()
    antes = (v.version, v.url)
    catalog.refresh_github_releases(cat)
    assert (v.version, v.url) == antes


def test_release_sem_zip_e_ignorada(monkeypatch):
    monkeypatch.setattr(catalog.requests, "get", lambda *a, **k: Resp(200, release("v9", assets=[
        {"name": "fonte.tar.gz", "size": 1, "browser_download_url": "https://gh/f.tar.gz"}])))
    cat, _, v = game_com_github()
    antes = (v.version, v.url)
    catalog.refresh_github_releases(cat)
    assert (v.version, v.url) == antes


def test_github_asset_escolhe_o_zip_certo(monkeypatch):
    dois = release("v1.0", assets=[
        {"name": "Ryza-Instalador.zip", "size": 1, "browser_download_url": "https://gh/a.zip"},
        {"name": "Ryza-PTBR-Textura.zip", "size": 2, "browser_download_url": "https://gh/b.zip"},
    ])
    monkeypatch.setattr(catalog.requests, "get", lambda *a, **k: Resp(200, dois))
    cat, _, v = game_com_github(asset="*textura*.zip")
    catalog.refresh_github_releases(cat)
    assert v.url == "https://gh/b.zip" and v.size == 2


def test_load_completo_mescla_github_e_falha_de_uma_fonte_nao_derruba(monkeypatch):
    bundled = catalog.load_bundled()
    bundled.game("atelier-ryza-1").default().github = "o/r"
    monkeypatch.setattr(catalog, "load_bundled", lambda: bundled)
    monkeypatch.setattr(catalog, "refresh_translation_manifests", lambda *a, **k: 1 / 0)
    monkeypatch.setattr(catalog.requests, "get", lambda *a, **k: Resp(200, release("v5")))
    cat = catalog.load()
    assert cat.game("atelier-ryza-1").default().version == "5"


def test_release_nova_vira_botao_atualizar(monkeypatch):
    """Instalada a 1.0; o repositório publica a v1.1 -> o app oferece ATUALIZAR."""
    from starlight.ui.main_window import compute_action

    monkeypatch.setattr(catalog.requests, "get", lambda *a, **k: Resp(200, release("v1.0")))
    cat, g, v = game_com_github()
    catalog.refresh_github_releases(cat)
    opts = g.options_for(v)
    rec = {"version_id": v.id, "version": v.version, "signature": catalog.signature(v, opts, {}), "options": {}}
    assert compute_action(v, rec, opts=opts, chosen={})[0] == "installed"

    monkeypatch.setattr(catalog.requests, "get", lambda *a, **k: Resp(200, release("v1.1"), etag='W/"2"'))
    cat2, g2, v2 = game_com_github()
    catalog.refresh_github_releases(cat2)
    assert compute_action(v2, rec, opts=opts, chosen={}) == ("update", "ATUALIZAR  →  1.1")
