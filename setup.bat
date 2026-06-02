@echo off
:: YT Dubber — one-command setup for Windows
:: Run this in a terminal with Administrator privileges

echo.
echo ╔══════════════════════════════════╗
echo ║       YT Dubber — Setup          ║
echo ╚══════════════════════════════════╝
echo.

:: ── 1. Check Python ──────────────────────────────────────────────
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found.
    echo Install Python 3.10+ from https://python.org/downloads
    echo Make sure to tick "Add Python to PATH" during install.
    pause
    exit /b 1
)

:: ── 2. Check Node ────────────────────────────────────────────────
where node >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Node.js not found.
    echo Install Node.js 18+ from https://nodejs.org
    pause
    exit /b 1
)

:: ── 3. Check mpv ─────────────────────────────────────────────────
where mpv >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARNING] mpv not found on PATH.
    echo Download mpv from https://mpv.io/installation/
    echo Extract mpv.exe and add its folder to your PATH.
    echo Press any key to continue anyway...
    pause >nul
)

:: ── 4. Check ffmpeg ──────────────────────────────────────────────
where ffmpeg >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARNING] ffmpeg not found on PATH.
    echo Download from https://ffmpeg.org/download.html and add to PATH.
    pause >nul
)

:: ── 5. Python dependencies ───────────────────────────────────────
echo Installing Python dependencies...
pip install -r backend\requirements.txt
pip install -U yt-dlp

:: ── 6. Node / Electron ───────────────────────────────────────────
echo Installing Node dependencies...
cd frontend
npm install
cd ..

:: ── 7. Done ──────────────────────────────────────────────────────
echo.
echo ╔══════════════════════════════════════════════════════════════╗
echo ║  Almost done! One manual step required:                      ║
echo ║                                                              ║
echo ║  Get a FREE Groq API key:  https://console.groq.com/keys    ║
echo ║                                                              ║
echo ║  Set it permanently (run in PowerShell as Admin):            ║
echo ║    setx GROQ_API_KEY "gsk_xxxxxxxxxxxxxxxxxxxx"              ║
echo ║                                                              ║
echo ║  Then restart your terminal and run:                         ║
echo ║    cd frontend                                               ║
echo ║    npm start                                                 ║
echo ║                                                              ║
echo ║  NOTE: Live Dub is Linux-only. Video URL mode works fine.   ║
echo ╚══════════════════════════════════════════════════════════════╝
echo.
echo Setup complete!
pause
