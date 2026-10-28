#!/usr/bin/env bash
# One-off: render public/icon.svg to the PNG icons the PWA manifest and iOS need.
# Not part of the build; the PNGs are committed. Re-run only after editing icon.svg.
# Needs Google Chrome (macOS path below; override with CHROME=...).
set -euo pipefail
cd "$(dirname "$0")/../public"
CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

render() { # <size> <output>
  printf '<!doctype html><style>html,body{margin:0;background:#0b0a12}img{display:block;width:%spx;height:%spx}</style><img src="file://%s/icon.svg">' \
    "$1" "$1" "$PWD" > "$work/p.html"
  "$CHROME" --headless=new --disable-gpu --hide-scrollbars --force-device-scale-factor=1 \
    --window-size="$1,$1" --screenshot="$PWD/$2" "file://$work/p.html" >/dev/null 2>&1
}

# icon.svg is full-bleed with the bird inside the central 80%, so one source serves "any" and "maskable".
render 192 icon-192.png
render 512 icon-512.png
render 512 icon-maskable-512.png
render 180 apple-touch-icon.png
