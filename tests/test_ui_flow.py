"""Teste ponta a ponta da interface (offscreen): baixa, instala, troca de versão,
atualiza e desinstala usando um servidor HTTP local."""
import io
import os
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PySide6 = pytest.importorskip("PySide6")
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from starlight import catalog, installer, state
from starlight.ui import style
from starlight.ui.main_window import MainWindow, compute_action, pending_updates


def zbytes(files):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for k, v in files.items():
            z.writestr(k, v)
    return b.getvalue()


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    a.setStyleSheet(style.QSS)
    return a


@pytest.fixture
def env(tmp_path, app, monkeypatch):
    blobs = {
        "/v1.zip": zbytes({"Data/PACK.PAK": b"V1-TRANSLATED", "extra_v1.txt": b"1"}),
        "/v2.zip": zbytes({"Data/PACK.PAK": b"V2-TRANSLATED-LONGER", "extra_v2.txt": b"2"}),
        "/v2b.zip": zbytes({"Data/PACK.PAK": b"V2-REVISED", "extra_v2.txt": b"2"}),
    }

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            body = blobs[self.path]
            self.send_response(200); self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        def log_message(self, *a): pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"

    game_dir = tmp_path / "Persona 5 Royal"
    (game_dir / "Data").mkdir(parents=True)
    (game_dir / "P5R.exe").write_bytes(b"exe")
    (game_dir / "Data" / "PACK.PAK").write_bytes(b"ORIGINAL")

    doc = {"schema": 1, "games": [{
        "id": "p5r", "name": "Persona 5 Royal", "required_files": ["P5R.exe"], "default_version": "v2",
        "versions": [
            {"id": "v1", "label": "V1", "version": "1.0", "url": base + "/v1.zip"},
            {"id": "v2", "label": "V2", "version": "2.0", "url": base + "/v2.zip"},
            {"id": "v3", "label": "V3", "version": "3.0", "url": ""},
        ]}]}
    cat = catalog.parse(doc)
    monkeypatch.setenv("STARLIGHT_CONFIG_DIR", str(tmp_path / "cfg"))
    state.save_settings({**state.DEFAULT_SETTINGS, "download_dir": str(tmp_path / "dl")})
    state.forget_install("p5r")
    for name in ("information", "warning", "question"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: QMessageBox.Yes))
    w = MainWindow(cat)
    yield w, cat, game_dir, blobs, srv
    w.close()
    srv.shutdown()


def wait_idle(w, timeout=15000):
    loop = QEventLoop()
    t = QTimer(); t.setInterval(30)
    elapsed = {"ms": 0}

    def tick():
        elapsed["ms"] += 30
        if not w._busy or elapsed["ms"] > timeout:
            loop.quit()
    t.timeout.connect(tick); t.start()
    QTimer.singleShot(50, lambda: None)
    loop.exec()
    t.stop()
    assert not w._busy, "job não terminou"


def run_job(w, g, v, folder):
    w._start_job(g, v, folder)
    wait_idle(w)


def test_p5r_versions_switch_update_uninstall(env):
    w, cat, game_dir, blobs, srv = env
    g = cat.game("p5r")
    pack = game_dir / "Data" / "PACK.PAK"

    # selecionado = versão padrão (V2); V3 está indisponível
    assert w._current_game.id == "p5r" and w._current_version_id == "v2"
    assert compute_action(g.version_by_id("v3"), None)[0] == "none"
    assert w.drawer.isVisibleTo(w) and set(w.drawer._cards) == {"v1", "v2", "v3"}

    # instala V1
    run_job(w, g, g.version_by_id("v1"), game_dir)
    assert pack.read_bytes() == b"V1-TRANSLATED"
    assert state.get_install("p5r")["version_id"] == "v1"
    assert not list((tmp := Path(state.download_dir())).glob("*.zip"))  # zip apagado após instalar

    # trocar para V2 (remove V1 e instala V2)
    run_job(w, g, g.version_by_id("v2"), game_dir)
    assert pack.read_bytes() == b"V2-TRANSLATED-LONGER"
    assert not (game_dir / "extra_v1.txt").exists() and (game_dir / "extra_v2.txt").exists()
    assert state.get_install("p5r")["version_id"] == "v2"

    # autor publica V2 revisada no manifest -> "update"
    g.version_by_id("v2").url = srv.server_address and g.version_by_id("v2").url.replace("/v2.zip", "/v2b.zip")
    g.version_by_id("v2").version = "2.1"
    rec = state.get_install("p5r")
    assert compute_action(g.version_by_id("v2"), rec)[0] == "update"
    assert [x[1].version for x in pending_updates(cat)] == ["2.1"]
    run_job(w, g, g.version_by_id("v2"), game_dir)
    assert pack.read_bytes() == b"V2-REVISED"
    assert compute_action(g.version_by_id("v2"), state.get_install("p5r"))[0] == "installed"

    # desinstalar restaura o original
    w._on_uninstall()
    wait_idle(w)
    assert pack.read_bytes() == b"ORIGINAL"
    assert not (game_dir / "extra_v2.txt").exists() and not (game_dir / "Starlight_Backup").exists()
    assert state.get_install("p5r") is None


def test_failed_download_leaves_game_untouched(env):
    w, cat, game_dir, blobs, srv = env
    g = cat.game("p5r")
    v = g.version_by_id("v1")
    v.sha256 = "0" * 64  # não confere
    run_job(w, g, v, game_dir)
    assert (game_dir / "Data" / "PACK.PAK").read_bytes() == b"ORIGINAL"
    assert not installer.has_translation(game_dir) and state.get_install("p5r") is None


def test_render_screenshots(env, tmp_path):
    w, cat, game_dir, blobs, srv = env
    g = cat.game("p5r")
    run_job(w, g, g.version_by_id("v1"), game_dir)
    w.resize(1100, 760); w.show()
    out = Path(os.environ.get("SHOT_DIR", tmp_path))
    out.mkdir(exist_ok=True, parents=True)
    w.grab().save(str(out / "p5r.png"))
    assert (out / "p5r.png").stat().st_size > 5000


def _opts_env(env):
    """Acrescenta as opções do P5R (codinomes + música) ao catálogo do teste."""
    w, cat, game_dir, blobs, srv = env
    base = f"http://127.0.0.1:{srv.server_port}"
    blobs["/classic.zip"] = zbytes({"Data/PACK.PAK": b"V2-CLASSIC-NAMES", "classic_note.txt": b"c"})
    blobs["/music.zip"] = zbytes({"Sound/battle.bin": b"MUSICA-PT"})
    doc = {"schema": 1, "games": [{
        "id": "p5r", "name": "Persona 5 Royal", "required_files": ["P5R.exe"], "default_version": "v2",
        "options": [
            {"id": "codenames", "type": "choice", "label": "Codinomes", "default": "official", "choices": [
                {"id": "official", "label": "Codinomes Oficiais"},
                {"id": "classic", "label": "Codinomes Clássicos", "url": base + "/classic.zip", "version": "1.0"}]},
            {"id": "pt_music", "type": "checkbox", "label": "Música em Português*", "url": base + "/music.zip", "version": "1.0"},
        ],
        "versions": [{"id": "v2", "label": "V2", "version": "2.0", "url": base + "/v2.zip"}]}]}
    cat2 = catalog.parse(doc)
    w.set_catalog(cat2)
    return cat2


def test_options_compute_action():
    cat = catalog.parse({"schema": 1, "games": [{"id": "g", "name": "G",
        "options": [{"id": "m", "type": "checkbox", "label": "M", "url": "http://x/m.zip", "version": "1"}],
        "versions": [{"id": "v1", "version": "1.0", "url": "http://x/b.zip"}]}]})
    g = cat.game("g"); v = g.versions[0]; opts = g.options_for(v)
    assert compute_action(v, None, opts=opts, chosen={"m": "on"})[0] == "install"
    rec = {"version_id": "v1", "version": "1.0", "options": {"m": "off"}, "signature": catalog.signature(v, opts, {"m": "off"})}
    assert compute_action(v, rec, opts=opts, chosen={"m": "off"})[0] == "installed"
    assert compute_action(v, rec, opts=opts, chosen={"m": "on"})[0] == "options"
    v.version = "1.1"
    assert compute_action(v, rec, opts=opts, chosen={"m": "off"})[0] == "update"


def test_options_install_override_uninstall(env):
    w, _, game_dir, blobs, srv = env
    cat = _opts_env(env)
    g = cat.game("p5r"); v = g.versions[0]
    pack = game_dir / "Data" / "PACK.PAK"

    # o painel aparece com menu suspenso + checkbox
    assert w.opts_panel.isVisibleTo(w)
    assert set(w.opts_panel._widgets) == {"codenames", "pt_music"}

    # instala: Codinomes Clássicos + Música PT (pacotes extras por cima da base)
    run_job(w, g, v, game_dir) if False else None
    w._start_job(g, v, game_dir, {"codenames": "classic", "pt_music": "on"})
    wait_idle(w)
    assert pack.read_bytes() == b"V2-CLASSIC-NAMES"              # pacote de codinomes sobrescreve a base
    assert (game_dir / "Sound" / "battle.bin").read_bytes() == b"MUSICA-PT"
    rec = state.get_install("p5r")
    assert rec["options"] == {"codenames": "classic", "pt_music": "on"}
    assert not list(state.download_dir().glob("*.zip"))

    # abrir de novo: painel mostra o que está instalado e o botão diz "instalada"
    w._current_version_id = "v2"; w._show_game(g)
    assert w.opts_panel.chosen() == {"codenames": "classic", "pt_music": "on"}
    assert w.btn_main.text().strip().endswith("INSTALADA")

    # desmarcar música -> "APLICAR OPÇÕES"; aplicar remove o arquivo de música
    w.opts_panel._widgets["pt_music"].setChecked(False)
    assert w.btn_main.text() == "APLICAR OPÇÕES"
    w._on_main_click()
    wait_idle(w)
    assert not (game_dir / "Sound").exists() and pack.read_bytes() == b"V2-CLASSIC-NAMES"
    assert state.get_install("p5r")["options"]["pt_music"] == "off"

    # voltar para Codinomes Oficiais (só a base)
    w.opts_panel._widgets["codenames"].setCurrentIndex(0)
    w._on_main_click()
    wait_idle(w)
    assert pack.read_bytes() == b"V2-TRANSLATED-LONGER" and not (game_dir / "classic_note.txt").exists()

    # desinstalar volta ao original em tudo
    w._on_uninstall()
    wait_idle(w)
    assert pack.read_bytes() == b"ORIGINAL" and not (game_dir / "Sound").exists()
    assert not (game_dir / "Starlight_Backup").exists()


def test_option_without_package_yet_is_blocked():
    cat = catalog.load_bundled()
    g = cat.game("persona-5-royal"); v = g.versions[0]
    v.url, v.available = "http://x/p5r.zip", True
    opts = g.options_for(v)
    assert {o.id for o in opts} == {"codenames", "pt_music"}
    assert compute_action(v, None, opts=opts, chosen={})[0] == "install"          # padrão: Oficiais, sem música
    assert compute_action(v, None, opts=opts, chosen={"pt_music": "on"})[1] == "OPÇÃO AINDA INDISPONÍVEL"
