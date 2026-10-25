import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from starlight import catalog, download, fsutil, selfupdate, state, steam


# ------------------------------------------------------------------ catálogo
def test_bundled_catalog_parses_and_p5r_has_options_but_one_version():
    c = catalog.load_bundled()
    p5r = c.game("persona-5-royal")
    assert len(p5r.versions) == 1          # sem gaveta V1/V2/V3
    assert {o.id for o in p5r.options} == {"codenames", "pt_music"}
    p4g = c.game("persona-4-golden")
    assert p4g.available and p4g.required_files == ["p4g.exe", "data.cpk"]


def test_individual_translation_manifest_updates_game_version():
    cat = catalog.load_bundled()
    game = cat.game("atelier-ryza-1")
    game.manifest_url = "https://example.invalid/manifest.json"
    doc = {
        "schema": 1,
        "id": "atelier-ryza-1",
        "version": "1.1.0",
        "label": "V1",
        "download_url": "https://example.invalid/traducao.zip",
        "sha256": "a" * 64,
        "size": 1234,
        "notes": "Correções de texto",
    }
    assert catalog._apply_translation_manifest(game, doc)
    version = game.default()
    assert version.version == "1.1.0"
    assert version.url == "https://example.invalid/traducao.zip"
    assert version.sha256 == "a" * 64
    assert version.size == 1234


def test_catalog_rejects_newer_schema():
    with pytest.raises(ValueError):
        catalog.parse({"schema": 99, "games": []})


def test_catalog_remote_cache_fallback(tmp_path):
    doc = {"schema": 1, "games": [{"id": "x", "name": "X", "versions": [{"id": "v1", "version": "9", "url": "http://a/b.zip"}]}]}

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps(doc).encode()
            self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        def log_message(self, *a): pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_port}/manifest.json"
    c = catalog.load(url)
    assert c.source == "remote" and c.game("x").versions[0].version == "9"
    srv.shutdown()
    c2 = catalog.load(url, timeout=1)  # servidor fora do ar -> cópia salva
    assert c2.source == "cache" and c2.game("x")


# ------------------------------------------------------------------ download
def _server(routes):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            ctype, body = routes[self.path.split("?")[0]](self)
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *a): pass
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_download_with_sha_and_drive_interstitial(tmp_path):
    payload = b"PK-fake-zip" * 5000
    sha = hashlib.sha256(payload).hexdigest()
    srv = _server({
        "/file": lambda h: ("application/zip", payload),
        "/drive": lambda h: ("text/html", b'<form id="download-form" action="/file"><input type="hidden" name="id" value="1"><input type="hidden" name="confirm" value="t"></form>'),
    })
    base = f"http://127.0.0.1:{srv.server_port}"
    seen = []
    d = download.Downloader()
    out = d.download(base + "/drive", tmp_path / "a.zip", lambda a, b: seen.append((a, b)), sha256=sha)
    assert out.read_bytes() == payload and seen[-1][0] == len(payload)
    assert not (tmp_path / "a.zip.part").exists()
    with pytest.raises(download.DownloadError):
        download.Downloader().download(base + "/file", tmp_path / "b.zip", sha256="0" * 64)
    assert not (tmp_path / "b.zip").exists() and not (tmp_path / "b.zip.part").exists()
    srv.shutdown()


def test_download_cancel(tmp_path):
    srv = _server({"/file": lambda h: ("application/zip", b"x" * 3_000_000)})
    d = download.Downloader()
    def prog(done, total):
        d.cancel()
    with pytest.raises(download.DownloadCancelled):
        d.download(f"http://127.0.0.1:{srv.server_port}/file", tmp_path / "c.zip", prog)
    assert not (tmp_path / "c.zip").exists() and not (tmp_path / "c.zip.part").exists()
    srv.shutdown()


# ------------------------------------------------------------------ arquivos / Steam
def test_case_insensitive_requirements(tmp_path):
    (tmp_path / "Data").mkdir()
    (tmp_path / "Data" / "Pack01.pak").write_bytes(b"1")
    (tmp_path / "Game.EXE").write_bytes(b"1")
    assert fsutil.all_requirements_met(tmp_path, ["data\\PACK01.PAK", "*.exe"])
    assert not fsutil.all_requirements_met(tmp_path, ["data/outro.pak"])
    assert not fsutil.all_requirements_met(tmp_path, [])


def test_steam_library_parsing_and_find(tmp_path):
    steam_root = tmp_path / "Steam"
    (steam_root / "steamapps" / "common").mkdir(parents=True)
    lib2 = tmp_path / "disco2" / "SteamLibrary"
    game = lib2 / "steamapps" / "common" / "Persona 4 Golden"
    game.mkdir(parents=True)
    (game / "P4G.exe").write_bytes(b"1")
    (game / "data.cpk").write_bytes(b"1")
    (steam_root / "steamapps" / "libraryfolders.vdf").write_text(
        '"libraryfolders"\n{\n "0" { "path" "%s" }\n "1" { "path" "%s" }\n}\n' % (str(steam_root).replace("\\", "\\\\"), str(lib2).replace("\\", "\\\\"))
    )
    found = steam.find_in_steam(["p4g.exe", "data.cpk"], roots=[steam_root])
    assert found == game


def test_scan_finds_nested_game_and_skips_ignored(tmp_path):
    deep = tmp_path / "Jogos" / "Emulados" / "KH"
    deep.mkdir(parents=True)
    (deep / "kh.exe").write_bytes(b"1")
    hidden = tmp_path / ".cache" / "kh2"
    hidden.mkdir(parents=True)
    (hidden / "kh.exe").write_bytes(b"1")
    assert steam.scan(["kh.exe"], roots=[tmp_path]) == deep


# ------------------------------------------------------------------ estado / auto-update
def test_state_forgets_missing_install(tmp_path):
    g = tmp_path / "jogo"
    (g / "Starlight_Backup").mkdir(parents=True)
    state.set_install("jogo", g, "v2", "2.0")
    assert state.get_install("jogo")["version_id"] == "v2"
    (g / "Starlight_Backup").rmdir()
    assert state.get_install("jogo") is None
    assert "jogo" not in state.load_installs()


def test_version_compare():
    assert selfupdate.is_newer("2.1.0", "2.0.0") and selfupdate.is_newer("v10.0", "9.9.9")
    assert not selfupdate.is_newer("2.0.0", "2.0.0") and not selfupdate.is_newer("1.9", "2.0.0")


def test_linux_shortcut_created(tmp_path, monkeypatch):
    import os
    if os.name == "nt":
        pytest.skip("teste do atalho Linux")
    from starlight import shortcut
    fake_exe = tmp_path / "Starlight-Instalador"
    fake_exe.write_bytes(b"x")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr(shortcut.Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(shortcut.paths, "executable_path", lambda: fake_exe)
    made = shortcut.create()
    desktop = tmp_path / "data" / "applications" / "starlight-translate.desktop"
    assert str(desktop) in made and f'Exec="{fake_exe}"' in desktop.read_text()
    assert os.access(fake_exe, os.X_OK)
