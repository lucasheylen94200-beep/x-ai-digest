@echo off
REM Daily AI Digest - script de lancement
cd /d "%~dp0"
echo === Daily AI Digest ===
echo.
python digest.py all
if errorlevel 1 (
  echo.
  echo [ERREUR] le script a echoue. Verifie Python et les dependances.
  pause
  exit /b 1
)
echo.
echo Ouverture du digest dans le navigateur...
start "" "%~dp0index.html"
