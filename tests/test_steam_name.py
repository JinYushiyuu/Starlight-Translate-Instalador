"""Detecção automática: '*.exe' sozinho não pode aceitar qualquer pasta da Steam."""
from pathlib import Path

from starlight import catalog, steam
from starlight.ui.main_window import translation_version_text

TRAILS = "Trails in the Sky 1st Chapter"


def lib(tmp_path: Path, *folders: str) -> Path:
    root = tmp_path / "Steam"
    for f in folders:
        d = root / "steamapps" / "common" / f
        d.mkdir(parents=True)
        (d / "jogo.exe").write_bytes(b"MZ")
    return root


def test_another_eden_nao_e_aceito_como_trails(tmp_path):
    root = lib(tmp_path, "Another Eden")
    assert steam.find_in_steam(["*.exe"], roots=[root], name=TRAILS) is None


def test_acha_a_pasta_certa_mesmo_com_outras_na_frente(tmp_path):
    root = lib(tmp_path, "Another Eden", "Atelier Ryza 2", TRAILS)
    found = steam.find_in_steam(["*.exe"], roots=[root], name=TRAILS)
    assert found and found.name == TRAILS


def test_trails_antigos_fc_sc_3rd_nao_valem_para_o_1st_chapter(tmp_path):
    root = lib(tmp_path, "Trails in the Sky FC", "Trails in the Sky SC", "Trails in the Sky the 3rd")
    assert steam.find_in_steam(["*.exe"], roots=[root], name=TRAILS) is None


def test_nome_de_pasta_diferente_mas_compativel(tmp_path):
    root = lib(tmp_path, "The Legend of Heroes Trails in the Sky 1st Chapter")
    assert steam.find_in_steam(["*.exe"], roots=[root], name=TRAILS)


def test_numero_distingue_ryza_1_2_3():
    m = steam.folder_matches_game
    assert m("Atelier Ryza 2 Lost Legends & the Secret Fairy", "Atelier Ryza 2: Lost Legends & the Secret Fairy")
    assert not m("Atelier Ryza 3 Alchemist of the End & the Secret Key", "Atelier Ryza 2: Lost Legends & the Secret Fairy")
    assert not m("Atelier Ryza Ever Darkness & the Secret Hideout", "Atelier Ryza 2: Lost Legends & the Secret Fairy")
    assert not m("Atelier", "Atelier Ryza 2")


def test_steam_folders_do_catalogo_tem_prioridade(tmp_path):
    root = lib(tmp_path, "Pasta Com Nome Estranho", "Trails in the Sky 1st Chapter")
    found = steam.find_in_steam(["*.exe"], roots=[root], name=TRAILS, hints=["nome estranho"])
    assert found and found.name == "Pasta Com Nome Estranho"


def test_arquivo_concreto_nao_exige_nome_de_pasta(tmp_path):
    root = tmp_path / "Steam" / "steamapps" / "common" / "Qualquer Nome"
    root.mkdir(parents=True)
    (root / "p4g.exe").write_bytes(b"MZ")
    (root / "data.cpk").write_bytes(b"x")
    assert steam.find_in_steam(["p4g.exe", "data.cpk"], roots=[tmp_path / "Steam"]) == root


def test_varredura_de_disco_tambem_respeita_o_nome(tmp_path):
    (tmp_path / "jogos" / "Another Eden").mkdir(parents=True)
    (tmp_path / "jogos" / "Another Eden" / "x.exe").write_bytes(b"MZ")
    certo = tmp_path / "jogos" / TRAILS
    certo.mkdir()
    (certo / "x.exe").write_bytes(b"MZ")
    assert steam.scan(["*.exe"], roots=[tmp_path], name=TRAILS) == certo
    assert steam.scan(["*.exe"], roots=[tmp_path / "jogos" / "Another Eden"], name=TRAILS) is None


def test_catalogo_le_steam_folders_e_trails_tem_nome_para_comparar():
    c = catalog.load_bundled()
    g = c.game("trails-in-the-sky-1st-chapter")
    assert steam.needs_name_check(g.required_files)
    assert steam.folder_matches_game(TRAILS, g.name)
    data = {"schema": 1, "games": [{"id": "x", "name": "X", "steam_folders": ["Foo", " "], "versions": []}]}
    assert catalog.parse(data).game("x").steam_folders == ["Foo"]


def test_texto_da_versao_da_traducao():
    v = catalog.Version(id="v1", label="V1", version="1.2")
    assert translation_version_text(v) == "Versão da tradução: v1.2"
    assert translation_version_text(v, {"version_id": "v1", "version": "1.1"}) == \
        "Tradução instalada: v1.1  ·  disponível: v1.2"
    assert translation_version_text(v, {"version_id": "v1", "version": "1.2"}) == "Versão da tradução: v1.2"
    assert translation_version_text(catalog.Version(id="v1", label="V1", version="31/05/2026")) == \
        "Versão da tradução: 31/05/2026"
    assert translation_version_text(None) == ""
