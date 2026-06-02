#!/usr/bin/env bash
# YT Dubber — one-command setup for Linux and macOS
# Usage: bash setup.sh

set -e

OS="$(uname -s)"
echo ""
echo "╔══════════════════════════════════╗"
echo "║       YT Dubber — Setup          ║"
echo "╚══════════════════════════════════╝"
echo ""

# ── 1. System tools ────────────────────────────────────────────────
echo "▶ Checking system tools..."

install_linux() {
    sudo apt-get update -qq
    sudo apt-get install -y mpv ffmpeg pulseaudio-utils
}

install_mac() {
    if ! command -v brew &>/dev/null; then
        echo "  Homebrew not found. Install it from https://brew.sh then re-run this script."
        exit 1
    fi
    brew install mpv ffmpeg
    echo "  ⚠️  Live Dub is Linux-only (needs PulseAudio). Video URL mode works fine on macOS."
}

if [ "$OS" = "Linux" ]; then
    install_linux
elif [ "$OS" = "Darwin" ]; then
    install_mac
else
    echo "  ⚠️  Unknown OS '$OS' — install mpv and ffmpeg manually."
fi

# yt-dlp (always via pip for latest version)
echo "▶ Installing yt-dlp..."
pip3 install -U yt-dlp --break-system-packages 2>/dev/null || pip3 install -U yt-dlp

# ── 2. Python dependencies ──────────────────────────────────────────
echo "▶ Installing Python dependencies..."
pip3 install --break-system-packages -r backend/requirements.txt 2>/dev/null \
    || pip3 install -r backend/requirements.txt

# ── 3. Node / Electron dependencies ────────────────────────────────
echo "▶ Installing Node dependencies..."
cd frontend && npm install && cd ..

# ── 4. API key reminder ─────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  Almost done! One manual step required:                      ║"
echo "║                                                              ║"
echo "║  Get a FREE Groq API key → https://console.groq.com/keys    ║"
echo "║                                                              ║"
echo "║  Then add this to your ~/.bashrc or ~/.zshrc:                ║"
echo "║    export GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxx              ║"
echo "║                                                              ║"
echo "║  Then run:                                                   ║"
echo "║    source ~/.bashrc   (or restart your terminal)             ║"
echo "║    cd frontend && npm start                                  ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "✅ Setup complete!"
