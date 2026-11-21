"""Galeria de imagens do site: usa o dados.js real do projeto (globalThis.games)."""
from starlight import project_gallery as pg

SLUG = "atelier-ryza-ever-darkness-the-secret-hideout-dx"
DADOS = '''globalThis.games = [
  {
title: "Outro jogo",
slug: "outro",
imagens: ["./img/x.webp"],
  },
  {
title: "Atelier Ryza: Ever Darkness & the Secret Hideout DX",
slug: "atelier-ryza-ever-darkness-the-secret-hideout-dx",
cover: "url('./img/grids/Ryza1.webp?v=1')",
autores: [
      { nome: "Jin", nota: "projeto de 'Rom Hacking' e estudos", cor: "#ec4899" },      // seu, continua rosa
    ],
youtubeUrl: "https://youtu.be/V_Z0LQEKxuk?si=siwBtf-PqDY36hjD",
imagens: [
"./img/img-traduzidas/Atelier-Ryza-1-Dx/Ryza_00.webp",
"./img/img-traduzidas/Atelier-Ryza-1-Dx/Ryza_01.webp",
"./img/img-traduzidas/Atelier-Ryza-1-Dx/Ryza_02.webp",
"./img/img-traduzidas/Atelier-Ryza-1-Dx/Ryza_03.webp"
    ],
tamanho:{ PC: "220mb" }
  }
];'''


class Resp:
    def __init__(self, body=b"", status=200, ctype="image/webp"):
        self.content, self.status_code, self.headers = body, status, {"Content-Type": ctype}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise pg.requests.HTTPError(f"{self.status_code}")


def test_parser_le_as_4_imagens_do_dados_js_real(monkeypatch):
    monkeypatch.setattr(pg.requests, "get", lambda *a, **k: Resp(DADOS.encode(), ctype="text/javascript"))
    p = pg.get_project(SLUG)
    assert p and len(p["images"]) == 4
    assert p["images"][0] == "https://starlight-translate.com.br/img/img-traduzidas/Atelier-Ryza-1-Dx/Ryza_00.webp"
    assert pg.LAST_ERROR == ""


def test_falha_de_rede_informa_o_motivo(monkeypatch):
    def boom(*a, **k):
        raise pg.requests.ConnectionError("SSL: CERTIFICATE_VERIFY_FAILED")

    monkeypatch.setattr(pg.requests, "get", boom)
    assert pg.get_project(SLUG) is None
    assert "CERTIFICATE_VERIFY_FAILED" in pg.LAST_ERROR


def test_imagem_html_nao_e_aceita(monkeypatch):
    monkeypatch.setattr(pg.requests, "get", lambda *a, **k: Resp(b"<html>", ctype="text/html"))
    try:
        pg.download_image("https://x/y.webp")
    except ValueError as exc:
        assert "HTML" in str(exc)
    else:
        raise AssertionError("deveria recusar HTML")


def test_catalogo_le_gallery_images():
    from starlight import catalog

    data = {"games": [{
        "id": "kh", "name": "KH",
        "gallery_images": [" https://media.phantasietranslate.com.br/site/a.webp ", "", "https://x/b.webp"],
        "versions": [{"id": "v1", "label": "V1", "version": "1.0"}],
    }]}
    games = catalog.parse(data, "teste").games
    assert games[0].gallery_images == [
        "https://media.phantasietranslate.com.br/site/a.webp",
        "https://x/b.webp",
    ]


def test_avif_e_convertido_para_png():
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (32, 18), (10, 120, 200)).save(buf, "AVIF")
    png = pg.to_png_bytes(buf.getvalue())
    assert png and png[:8] == b"\x89PNG\r\n\x1a\n"
    assert pg.to_png_bytes(b"lixo") is None


def test_qt_carrega_o_png_convertido_do_avif():
    import io

    from PIL import Image
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    buf = io.BytesIO()
    Image.new("RGB", (32, 18), (10, 120, 200)).save(buf, "AVIF")
    assert not QPixmap().loadFromData(buf.getvalue())  # Qt sozinho não abre AVIF
    pix = QPixmap()
    assert pix.loadFromData(pg.to_png_bytes(buf.getvalue())) and pix.width() == 32
    assert app is not None
