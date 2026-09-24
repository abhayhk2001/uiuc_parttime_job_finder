#!/usr/bin/env bash
# Build a clean macOS .app bundle of the UIUC Part-Time Job Scanner.
#
# Why a clean venv: PyInstaller copies every importable package it can see
# in the active interpreter into the bundle. The project's development venv
# often picks up stray packages (numpy/pandas/matplotlib/etc.) that bloat
# the bundle by tens of MB. Building inside a throwaway venv that
# contains only the project's real deps keeps the .app small and
# reproducible.
#
# Usage:
#   ./build-mac.sh                       # unsigned, ad-hoc build
#   CODESIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)" \
#     NOTARY_PROFILE="my-notary-profile" \
#     ./build-mac.sh                     # signed + notarized
#
# Environment variables:
#   BUILD_VENV         path to the throwaway venv (default: .build-venv)
#   PYTHON             python interpreter to use (default: python3)
#   CODESIGN_IDENTITY  if set, codesign + notarize via scripts/sign-and-notarize.sh
#   NOTARY_PROFILE     notarytool keychain profile (required for notarization)
#
# Requirements: Xcode command-line tools (for codesign / notarytool / ditto),
# Python 3.9+ on PATH.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON="${PYTHON:-python3}"
BUILD_VENV="${BUILD_VENV:-$SCRIPT_DIR/.build-venv}"

echo "==> Cleaning previous build artefacts"
rm -rf build dist
rm -rf "$BUILD_VENV"

echo "==> Creating throwaway venv at $BUILD_VENV"
"$PYTHON" -m venv "$BUILD_VENV"

echo "==> Installing project + runtime dependencies"
"$BUILD_VENV/bin/pip" install --upgrade pip wheel >/dev/null
"$BUILD_VENV/bin/pip" install -r requirements.txt
"$BUILD_VENV/bin/pip" install -e . >/dev/null

echo "==> Installing PyInstaller"
"$BUILD_VENV/bin/pip" install pyinstaller >/dev/null

echo "==> Building .app bundle"
"$BUILD_VENV/bin/pyinstaller" pyinstaller.spec

APP="dist/UIUC Part-Time Job Scanner.app"
SIZE=$(du -sh "$APP" | cut -f1)
echo "==> Build complete: $APP ($SIZE)"

if [ -n "${CODESIGN_IDENTITY:-}" ]; then
  echo "==> Signing + notarizing"
  CODESIGN_IDENTITY="$CODESIGN_IDENTITY" NOTARY_PROFILE="${NOTARY_PROFILE:-}" \
    "$SCRIPT_DIR/scripts/sign-and-notarize.sh"
fi
