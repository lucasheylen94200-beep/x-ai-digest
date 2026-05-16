@echo off
REM Daily AI Digest - pipeline complet
REM Fetch tweets > Gemini process > Build HTML > Push GitHub > Send email
setlocal
cd /d "%~dp0"

REM Loguer la date dans le fichier log
echo. >> daily.log
echo === Run %DATE% %TIME% === >> daily.log

echo === Daily AI Digest ===
echo.

REM === ETAPE 1-3 : Fetch + Process + Build ===
python digest.py all
if errorlevel 1 (
  echo [ERREUR] Le pipeline digest a echoue >> daily.log
  echo.
  echo [ERREUR] Pipeline digest en echec. Verifie le log.
  pause
  exit /b 1
)

REM === ETAPE 4 : Push sur GitHub (publication de la page) ===
echo.
echo === PUSH GITHUB ===
git add data/ index.html accounts.json 2>nul
REM Commit seulement s'il y a des changements
git diff --cached --quiet
if errorlevel 1 (
  git commit -m "Digest du %DATE%" 2>nul
  git push origin main 2>nul
  if errorlevel 1 (
    echo [WARN] git push echoue, le mail sera quand meme envoye
    echo [WARN] git push echoue %DATE% %TIME% >> daily.log
  ) else (
    echo [OK] Push GitHub reussi
  )
) else (
  echo Pas de changement a pusher.
)

REM === ETAPE 5 : Envoi de l'email ===
echo.
echo === EMAIL ===
python send_email.py
if errorlevel 1 (
  echo [WARN] Envoi email en echec
  echo [WARN] mail echoue %DATE% %TIME% >> daily.log
)

REM === Ouverture locale de la page (si on est interactif) ===
if "%1"=="" (
  echo.
  echo Ouverture du digest local dans le navigateur...
  start "" "%~dp0index.html"
)

echo.
echo === Termine ===
echo [OK] Run termine %DATE% %TIME% >> daily.log
