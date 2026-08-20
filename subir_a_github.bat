@echo off
REM ============================================================
REM  Sube esta carpeta a un repositorio de GitHub (Windows).
REM  Antes de correrlo:
REM   1) Entra a https://github.com/new y crea un repo VACIO
REM      (sin README, sin .gitignore). Copia su URL, ej:
REM      https://github.com/TU-USUARIO/cerebro-kommo.git
REM   2) Pega esa URL cuando este script te la pida.
REM ============================================================
setlocal
cd /d "%~dp0"

echo.
set /p REPO="Pega la URL del repo de GitHub (.git) y Enter: "

if "%REPO%"=="" (
  echo No pegaste ninguna URL. Cancelo.
  pause
  exit /b 1
)

git init
git add .
git commit -m "Cerebro de ventas Shopping Asia - version inicial"
git branch -M main
git remote remove origin 2>NUL
git remote add origin %REPO%
git push -u origin main

echo.
echo ============================================================
echo  Si pide usuario/clave: usa tu usuario de GitHub y un
echo  TOKEN personal como contrasena (no la clave normal).
echo  Listo. Ahora en Render conecta este repo.
echo ============================================================
pause
