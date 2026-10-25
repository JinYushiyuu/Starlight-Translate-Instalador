"""Configurações fixas do instalador.

Cada tradução possui seu próprio repositório e seu próprio manifest.json.
O catálogo embutido em catalog/manifest.json guarda os metadados dos jogos e
o endereço do manifesto individual de cada tradução.
"""

INSTALLER_REPO = "JinYushiyuu/Starlight-Translate-Instalador"

# Nomes dos arquivos anexados a cada Release do instalador.
ASSET_WINDOWS = "Starlight-Translate-Instalador-windows-x64.exe"
ASSET_LINUX = "Starlight-Translate-Instalador-linux-x86_64"

USER_AGENT = "Starlight-Translate-Instalador"

APP_TITLE = "Starlight Translate Instalador"
CREDITS_LINE = "Desenvolvido por Jin_Yushiyuu"


def is_configured() -> bool:
    """Indica se o repositório de atualização do instalador foi configurado."""
    return bool(INSTALLER_REPO) and "SEU-USUARIO" not in INSTALLER_REPO
