# Starlight Translate Instalador (Windows + Linux)

- **Usuários comuns:** leiam `USUARIO.md` (baixar e dar dois cliques; sem comandos).
- **Publicar sem terminal:** `PUBLICAR.md`.
- O restante deste arquivo é para desenvolvimento.

Instalador de traduções reformado: um único código para os dois sistemas, lista de jogos
vinda do GitHub (sem recompilar), atualização automática, desinstalação limpa e seletor
de versões (ex.: Persona 5 Royal V1 / V2 / V3).

## 1) Configurar (uma vez)

Edite `starlight/app_config.py`:

| Constante | O que colocar |
|---|---|
| `CATALOG_URL` | link **raw** do `manifest.json` no repositório das traduções |
| `INSTALLER_REPO` | `usuario/repositorio` do instalador (para ele se atualizar) |

Sugestão de dois repositórios:
- **Starlight-Translate-Catalogo**: contém só o `manifest.json` (copie de `catalog/manifest.json`).
- **Starlight-Translate-Instalador**: este projeto. Os `.zip` das traduções podem ficar em Releases de qualquer repositório (ou Drive, como hoje).

## 2) Lançar/atualizar uma tradução (sem mexer no instalador)

1. Suba o `.zip` (Release do GitHub é o ideal).
2. `python tools/hash_zip.py Pacote.zip --id v2 --label V2 --version 2.1 --url <link do zip>`
3. Cole o trecho gerado na lista `versions` do jogo em `manifest.json` e faça commit.

Quem já tem a tradução instalada vê **⬆ Atualizar** na próxima vez que abrir o instalador
(o que dispara a atualização é a mudança do campo `version`). O `sha256` garante que o arquivo baixado não está corrompido.

Persona 5 Royal já está no catálogo com V1/V2/V3 (sem links ainda). Preencha `url`, `version`, `notes`,
confirme o `required_files` (`P5R.exe`) e coloque `img/icons/P5R.jpg` e `img/banner/P5R.jpg`
(ou use URLs `https://` no `icon`/`banner`).


## Opções da tradução (menu suspenso e caixa de marcar)

Cada opção escolhida pode trazer um `.zip` extra, aplicado por cima da tradução base na mesma instalação
(se dois pacotes tiverem o mesmo arquivo, vale o último; o original do jogo é sempre o que fica no backup).
Trocar uma opção depois mostra o botão **APLICAR OPÇÕES**, que refaz a instalação sozinho.

No `manifest.json`, dentro do jogo (vale para todas as versões) ou dentro de uma versão (só para ela):

```json
"options": [
  { "id": "codenames", "type": "choice", "label": "Codinomes", "default": "official",
    "choices": [
      { "id": "official", "label": "Codinomes Oficiais" },
      { "id": "classic",  "label": "Codinomes Clássicos", "url": "https://.../classicos.zip", "sha256": "", "size": 0, "version": "1.0" }
    ] },
  { "id": "pt_music", "type": "checkbox", "label": "Música Importante em Português*", "default": false,
    "url": "https://.../musica.zip", "sha256": "", "size": 0, "version": "1.0",
    "note": "*Texto explicativo que aparece abaixo da caixa." }
]
```
- Escolha **sem** `url` (como "Oficiais") = só a tradução base, nada extra para baixar.
- Escolha com a chave `url` **vazia** = pacote ainda não enviado; aparece "(em breve)" e o botão fica bloqueado.
- Para republicar um pacote de opção, aumente o `version` dele: quem usa a opção vê **⬆ Atualizar**.

## 3) Lançar uma versão nova do instalador

1. Aumente `__version__` em `starlight/__init__.py`.
2. `git tag v2.1.0 && git push --tags`: o GitHub Actions roda os testes, compila Windows e Linux e anexa ao Release.
3. Instaladores antigos mostram "Nova versão disponível" e trocam o próprio executável.

## 4) Rodar / compilar localmente

```
pip install -r requirements-dev.txt
python main.py                  # executar
python -m pytest                # testes (use QT_QPA_PLATFORM=offscreen sem monitor)
pyinstaller --noconfirm starlight.spec   # gera dist/ do seu sistema
```
Linux: o Qt precisa de `libxcb-cursor0` (Debian/Ubuntu) ou `xcb-util-cursor` (Arch/SteamOS).

## Como a instalação funciona
- Arquivos originais que a tradução substitui são **movidos** para `Starlight_Backup/` (instantâneo, sem duplicar GBs); arquivos novos são anotados em `install.json`.
- Falhou no meio? Tudo é desfeito sozinho. Desinstalar restaura os originais e apaga o que foi adicionado.
- Se a Steam atualizou um arquivo depois da instalação, a desinstalação **não** o sobrescreve com backup antigo.
- Traduções feitas pelo instalador antigo (`Starlight_Backup` sem `install.json`) são reconhecidas e removidas corretamente.
- Linux: nomes de arquivo são casados sem diferenciar maiúsculas (Windows/Proton), a Steam é achada em `~/.steam`, `~/.local/share/Steam`, Flatpak e Snap, e em todas as bibliotecas extras.

## Abrir no VS Code
Abra a pasta, crie o ambiente (`python3 -m venv .venv`, ative, `pip install -r requirements-dev.txt`), escolha o interpretador `.venv`
(Ctrl+Shift+P → *Python: Select Interpreter*) e use F5: **Instalador (abrir)** ou **Testes**.