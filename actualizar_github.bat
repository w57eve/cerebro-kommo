@echo off
REM Sube los cambios del cerebro a GitHub (Render vuelve a desplegar solo).
REM Poné este archivo en la carpeta cerebro-kommo (donde esta la carpeta .git)
REM y hace doble clic cada vez que cambiemos algo del codigo.
setlocal
cd /d "%~dp0"
git add -A
git commit -m "Actualizacion del cerebro"
git push
echo.
echo Listo. En 1-2 minutos Render vuelve a desplegar con los cambios.
pause
