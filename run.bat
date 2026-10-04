@echo off
REM repo_radar launcher - double click to run
REM Edit the QUERIES / OPTIONS lines below to match your own topics.

setlocal
cd /d "%~dp0"

REM ============================================================
REM  GitHub token is kept in ONE place:
REM      %USERPROFILE%\.config\gh-radar\token.env
REM  Open that file and edit the GITHUB_TOKEN= line. This block
REM  loads it automatically. If it is blank/missing, the tool
REM  just falls back to anonymous mode (lower rate limit).
REM ============================================================
if not defined GITHUB_TOKEN if exist "%USERPROFILE%\.config\gh-radar\token.env" (
  for /f "usebackq tokens=1,* delims==" %%a in (`findstr /b /i "GITHUB_TOKEN=" "%USERPROFILE%\.config\gh-radar\token.env"`) do set "GITHUB_TOKEN=%%b"
)

REM ============================================================
REM  Your search keywords. Add or remove -q entries as you like.
REM ============================================================
set QUERIES=-q "predictive maintenance" -q "inventory forecast" -q "spare parts optimization"

REM ============================================================
REM  Filters. Remove a line to disable that filter.
REM ============================================================
set OPTIONS=--min-stars 100 --pushed-after 2025-01-01 --top 20

echo.
python repo_radar.py %QUERIES% %OPTIONS% --json result.json

echo.
echo ============================================================
echo  Done. Full ranking saved to result.json
echo ============================================================
pause
