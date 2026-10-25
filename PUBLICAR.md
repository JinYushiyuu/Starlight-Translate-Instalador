# Publicar o instalador (você só faz isso uma vez; sem terminal)

O GitHub compila os programas de Windows e Linux de graça. Você só usa o navegador.

## Uma vez só
1. Crie uma conta em github.com e um repositório **público** chamado `Starlight-Translate-Instalador`.
2. Confira `starlight/app_config.py`; `INSTALLER_REPO` deve apontar para `JinYushiyuu/Starlight-Translate-Instalador`. Cada jogo recebe o endereço do seu manifesto individual no campo `manifest_url` de `catalog/manifest.json`.
3. Suba todos os arquivos desta pasta no repositório (botão **Add file → Upload files**, arrastando tudo; ou use o **GitHub Desktop**, que é visual).

## Lançar o instalador (primeira vez e a cada versão nova)
1. Em `starlight/__init__.py`, ajuste `__version__` (ex.: `"2.0.0"`).
2. No repositório: **Releases → Draft a new release**. Em *Choose a tag*, digite `v2.0.0` (mesmo número) → **Create new tag** → **Publish release**.
3. Aguarde uns 10 minutos (aba **Actions** mostra o progresso). Os dois arquivos aparecem sozinhos no Release.
4. Pronto: o link para os usuários é sempre o mesmo, e aponta para a versão mais nova:
   - `https://github.com/SEU-USUARIO/Starlight-Translate-Instalador/releases/latest/download/Starlight-Translate-Instalador-windows-x64.exe`
   - `https://github.com/SEU-USUARIO/Starlight-Translate-Instalador/releases/latest/download/Starlight-Translate-Instalador-linux-x86_64`

Quem já usa o instalador recebe a versão nova automaticamente.

## Lançar/atualizar uma tradução (não precisa de Release do instalador)
Edite o `manifest.json` no repositório da própria tradução: atualize o objeto correspondente dentro de `versions` (campos `version`, `url`, `sha256` e `size`, veja `tools/hash_zip.py`) e salve. Os usuários veem "⬆ Atualizar" ao abrir o instalador. O endereço raw desse manifesto precisa estar configurado uma vez no campo `manifest_url` do jogo em `catalog/manifest.json`.

## Se o Actions falhar
Abra a aba **Actions**, clique na execução vermelha e me mande o texto do erro.
