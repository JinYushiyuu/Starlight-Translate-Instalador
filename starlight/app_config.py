"""Configurações do Starlight Translate Instalador."""

CATALOG_URL = (
    "https://raw.githubusercontent.com/JinYushiyuu/Starlight-Translate-Catalogo/main/manifest.json"
)
INSTALLER_REPO = "JinYushiyuu/Starlight-Translate-Instalador"

ASSET_WINDOWS = "Starlight-Translate-Instalador-windows-x64.exe"
ASSET_LINUX = "Starlight-Translate-Instalador-linux-x86_64"

USER_AGENT = "Starlight-Translate-Instalador"

APP_TITLE = "Starlight Translate Instalador"
CREDITS_LINE = "Desenvolvido por Jin_Yushiyuu"


def is_configured() -> bool:
    """Indica se os endereços reais dos repositórios estão configurados."""
    return (
        "JinYushiyuu/Starlight-Translate-Catalogo" in CATALOG_URL
        and INSTALLER_REPO == "JinYushiyuu/Starlight-Translate-Instalador"
    )
