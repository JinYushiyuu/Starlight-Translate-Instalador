"""Configurações fixas do instalador.

>>> EDITE AQUI os dois endereços do GitHub antes de publicar. <<<

CATALOG_URL
    Endereço do manifest.json (o "catálogo") no repositório das traduções.
    Sempre que você editar esse arquivo no GitHub, todos os instaladores já
    instalados passam a enxergar a mudança (nova versão, novo jogo, etc.)
    SEM precisar baixar o instalador de novo.

INSTALLER_REPO
    Repositório do próprio instalador ("dono/repositorio"). Quando você
    publica um Release lá, os instaladores existentes avisam o usuário e se
    atualizam sozinhos.
"""

CATALOG_URL = (
    "https://raw.githubusercontent.com/JinYushiyuu/Starlight-Translate-Catalogo/main/manifest.json"
)
INSTALLER_REPO = "SEU-USUARIO/Starlight-Translate-Instalador"

# Nomes dos arquivos que você anexa em cada Release do instalador.
ASSET_WINDOWS = "Starlight-Translate-Instalador-windows-x64.exe"
ASSET_LINUX = "Starlight-Translate-Instalador-linux-x86_64"

USER_AGENT = "Starlight-Translate-Instalador"

APP_TITLE = "Starlight Translate Instalador"
CREDITS_LINE = "Desenvolvido por Jin_Yushiyuu"


def is_configured() -> bool:
    """False enquanto os endereços ainda são os de exemplo."""
    return "JinYushiyuu/Starlight-Translate-Instalador" not in CATALOG_URL
