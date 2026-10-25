import threading
import zipfile
from pathlib import Path

import pytest

from starlight import installer as inst


def make_zip(path: Path, files: dict):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return path


@pytest.fixture
def game(tmp_path):
    g = tmp_path / "game"
    (g / "Data").mkdir(parents=True)
    (g / "p4g.exe").write_bytes(b"EXE")
    (g / "Data" / "PACK01.PAK").write_bytes(b"ORIGINAL-PACK")
    return g


def test_install_and_uninstall_restores_everything(game, tmp_path):
    z = make_zip(tmp_path / "t.zip", {"data/pack01.pak": b"TRANSLATED!!", "Novo/extra.txt": b"x", "leia.txt": b"hi"})
    rec = inst.install(game, z, "g", "v1", "1.0")
    # nome diferente em maiúsculas NÃO cria pasta duplicada
    assert sorted(p.name for p in game.iterdir() if p.is_dir()) == ["Data", "Novo", "Starlight_Backup"]
    assert (game / "Data" / "PACK01.PAK").read_bytes() == b"TRANSLATED!!"
    assert set(rec["added"]) == {"Novo/extra.txt", "leia.txt"}
    assert inst.has_translation(game) and not inst.is_legacy(game)

    res = inst.uninstall(game)
    assert (game / "Data" / "PACK01.PAK").read_bytes() == b"ORIGINAL-PACK"
    assert not (game / "Novo").exists() and not (game / "leia.txt").exists()
    assert not (game / "Starlight_Backup").exists()
    assert res.restored == 1 and res.removed == 2


def test_rollback_on_cancel_midway(game, tmp_path):
    z = make_zip(tmp_path / "t.zip", {"Data/PACK01.PAK": b"NEW", "a.txt": b"1", "b.txt": b"2"})
    ev = threading.Event()

    def prog(i, n, rel):
        if i == 2:
            ev.set()

    with pytest.raises(inst.Cancelled):
        inst.install(game, z, "g", "v1", "1.0", progress=prog, cancel=ev)
    assert (game / "Data" / "PACK01.PAK").read_bytes() == b"ORIGINAL-PACK"
    assert not (game / "a.txt").exists() and not (game / "Starlight_Backup").exists()


def test_zip_slip_blocked(game, tmp_path):
    z = make_zip(tmp_path / "t.zip", {"../evil.txt": b"x"})
    with pytest.raises(inst.InstallError):
        inst.install(game, z, "g", "v1", "1.0")
    assert not (tmp_path / "evil.txt").exists()


def test_not_a_zip(game, tmp_path):
    bad = tmp_path / "t.zip"
    bad.write_text("<html>aviso do drive</html>")
    with pytest.raises(inst.InstallError):
        inst.install(game, bad, "g", "v1", "1.0")


def test_double_install_refused(game, tmp_path):
    z = make_zip(tmp_path / "t.zip", {"a.txt": b"1"})
    inst.install(game, z, "g", "v1", "1.0")
    with pytest.raises(inst.InstallError):
        inst.install(game, z, "g", "v1", "1.0")


def test_update_v1_to_v2(game, tmp_path):
    z1 = make_zip(tmp_path / "1.zip", {"Data/PACK01.PAK": b"V1", "so_v1.txt": b"a"})
    z2 = make_zip(tmp_path / "2.zip", {"Data/PACK01.PAK": b"VERSION-2", "so_v2.txt": b"b"})
    inst.install(game, z1, "g", "v1", "1.0")
    inst.uninstall(game)
    inst.install(game, z2, "g", "v2", "2.0")
    assert (game / "Data" / "PACK01.PAK").read_bytes() == b"VERSION-2"
    assert not (game / "so_v1.txt").exists() and (game / "so_v2.txt").exists()
    inst.uninstall(game)
    assert (game / "Data" / "PACK01.PAK").read_bytes() == b"ORIGINAL-PACK"


def test_uninstall_does_not_downgrade_file_changed_by_steam(game, tmp_path):
    z = make_zip(tmp_path / "t.zip", {"Data/PACK01.PAK": b"TRANSLATED"})
    inst.install(game, z, "g", "v1", "1.0")
    # Steam atualiza o jogo e troca o arquivo por outro de tamanho diferente
    (game / "Data" / "PACK01.PAK").write_bytes(b"OFFICIAL-NEW-PATCH-CONTENT")
    res = inst.uninstall(game)
    assert (game / "Data" / "PACK01.PAK").read_bytes() == b"OFFICIAL-NEW-PATCH-CONTENT"
    assert res.skipped_changed == ["Data/PACK01.PAK"]
    assert not (game / "Starlight_Backup").exists()


def test_legacy_backup_is_restored(game):
    # instalador antigo: Starlight_Backup/<arquivo> sem install.json
    (game / "Starlight_Backup" / "Data").mkdir(parents=True)
    (game / "Starlight_Backup" / "Data" / "PACK01.PAK").write_bytes(b"BACKUP-OLD")
    (game / "Data" / "PACK01.PAK").write_bytes(b"TRANSLATED")
    assert inst.is_legacy(game)
    res = inst.uninstall(game)
    assert res.legacy and (game / "Data" / "PACK01.PAK").read_bytes() == b"BACKUP-OLD"
    assert not (game / "Starlight_Backup").exists()
