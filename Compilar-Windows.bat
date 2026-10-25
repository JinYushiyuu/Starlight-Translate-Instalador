@echo off
chcp 65001 >nul
title Compilar Starlight Translate Instalador
cd /d "%~dp0"
echo.
echo === Compilando o Starlight Translate Instalador (Windows) ===
echo.
where py >nul 2>nul
if errorlevel 1 (
  echo Python nao encontrado. Instale em https://www.python.org/downloads/
  echo e marque a opcao "Add Python to PATH" no instalador. Depois rode este arquivo de novo.
  pause
  exit /b 1
)
if not exist .venv (
  py -m venv .venv || goto erro
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip >nul
pip install -r requirements-dev.txt || goto erro
pyinstaller --noconfirm starlight.spec || goto erro
echo.
echo PRONTO! O programa esta em:  %~dp0dist\Starlight-Translate-Instalador-windows-x64.exe
explorer "%~dp0dist"
pause
exit /b 0
:erro
echo.
echo Algo deu errado. Copie o texto acima e me envie.
pause
exit /b 1
