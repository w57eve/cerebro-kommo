@echo off
REM ============================================================
REM  Enlaza ESTA carpeta con tu repo de GitHub (w57eve/cerebro-kommo)
REM  y sube los cambios. Ejecutalo UNA sola vez (doble clic).
REM  Despues, para futuros cambios, usa actualizar_github.bat.
REM ============================================================
setlocal
cd /d "%~dp0"

git init
git branch -M main
git remote remove origin 2>NUL
git remote add origin https://github.com/w57eve/cerebro-kommo.git
git fetch origin
git reset --soft origin/main
git add -A
git commit -m "Pagina de prueba + orden de carpeta"
git push -u origin main

echo.
echo ============================================================
echo  Si pide usuario/clave: usuario de GitHub y tu TOKEN como clave.
echo  Listo: Render vuelve a desplegar en 1-2 minutos.
echo  De ahora en mas, para cambios usa actualizar_github.bat
echo ============================================================
pause
