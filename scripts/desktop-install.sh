#!/usr/bin/env bash
# Build the desktop app and put it in the app launcher (Linux).
#   scripts/desktop-install.sh                          # a release build, installed under ~/.local
#   DOTTIE_URL=https://dottie.example.com scripts/desktop-install.sh   # for a server elsewhere than localhost:8370
#   scripts/desktop-install.sh --autostart              # also start it at login (tray icon and notifications)
#   scripts/desktop-install.sh --remove                 # take it all out again
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=scripts/lib.sh
source scripts/lib.sh

bin="$HOME/.local/bin/dottie-desktop"
icon="$HOME/.local/share/icons/hicolor/512x512/apps/dottie.png"
entry="$HOME/.local/share/applications/dottie.desktop"
autostart="$HOME/.config/autostart/dottie.desktop"

case "${1:-}" in
  "" | --autostart) ;;
  --remove)
    rm -f "$bin" "$icon" "$entry" "$autostart"
    echo "Removed Dottie from the launcher."
    exit 0
    ;;
  *)
    echo "usage: $0 [--autostart | --remove]" >&2
    exit 1
    ;;
esac

need cargo "https://rustup.rs (or: sudo pacman -S rust)"
need npm "https://nodejs.org"
(cd desktop && npm install --silent && npm run build -- --no-bundle)

install -Dm755 desktop/src-tauri/target/release/dottie-desktop "$bin"
install -Dm644 desktop/src-tauri/icons/icon.png "$icon"
mkdir -p "$(dirname "$entry")"
cat >"$entry" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Dottie
Comment=Your dotties, on the desktop
Exec=env DOTTIE_URL=${DOTTIE_URL:-http://localhost:8370} $bin
Icon=dottie
Categories=Network;Chat;
StartupWMClass=dottie-desktop
Terminal=false
DESKTOP
echo "Installed: $bin, and Dottie in the launcher (server ${DOTTIE_URL:-http://localhost:8370})."

if [ "${1:-}" = "--autostart" ]; then
  mkdir -p "$(dirname "$autostart")"
  cp "$entry" "$autostart"
  echo "It will start at login."
fi
