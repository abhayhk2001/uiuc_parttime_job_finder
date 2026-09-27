#!/usr/bin/env bash
# Sign and notarize dist/UIUC Part-Time Job Scanner.app for distribution.
#
# Prerequisites (one-time setup):
#
#   1. Apple Developer Program membership ($99/yr).
#      https://developer.apple.com/programs/enroll/
#
#   2. A "Developer ID Application" certificate installed in your
#      keychain. Open Keychain Access -> Certificate Assistant ->
#      Request a Certificate from a Certificate Authority with your
#      email + common name. Then go to
#      https://developer.apple.com/account/resources/certificates/list
#      and create a "Developer ID Application" cert using that CSR.
#      Approve it in Xcode (Xcode > Settings > Accounts > your Apple ID >
#      Manage Certificates > the cert should appear and download).
#
#   3. A notarytool keychain profile, so this script can submit to
#      Apple's notary service without leaking your Apple ID:
#
#         xcrun notarytool store-credentials jobscanner-notary \
#             --apple-id you@example.com \
#             --team-id  ABCDE12345 \
#             --password <app-specific-password-from-appleid.apple.com>
#
#      Store the profile name in NOTARY_PROFILE.
#
# Usage:
#
#   # Ad-hoc sign only (default; no Developer ID needed)
#   ./scripts/sign-and-notarize.sh
#
#   # Sign with a real Developer ID
#   CODESIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)" \
#       ./scripts/sign-and-notarize.sh
#
#   # Sign + notarize + staple
#   CODESIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)" \
#   NOTARY_PROFILE="jobscanner-notary" \
#       ./scripts/sign-and-notarize.sh
#
# Environment variables:
#   APP                  the .app to sign (default: dist/UIUC Part-Time Job Scanner.app)
#   CODESIGN_IDENTITY    "Developer ID Application: ..." string; ad-hoc if empty
#   NOTARY_PROFILE       notarytool keychain profile name; no notarization if empty
#   ENTITLEMENTS         path to entitlements.plist (default: ./entitlements.plist)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.."

APP="${APP:-dist/UIUC Part-Time Job Scanner.app}"
ENTITLEMENTS="${ENTITLEMENTS:-$SCRIPT_DIR/../entitlements.plist}"

if [ ! -d "$APP" ]; then
  echo "error: $APP does not exist; run build-mac.sh first" >&2
  exit 1
fi

# -- 1. Sign ------------------------------------------------------------
# Use xcrun for everything Xcode-related so this script works regardless
# of how the Xcode developer dir was set up.
CODESIGN="$(command -v codesign || echo /usr/bin/codesign)"
SPCTL="$(command -v spctl || echo /usr/sbin/spctl)"
NOTARYTOOL="$(xcrun --find notarytool 2>/dev/null || command -v notarytool || true)"
STAPLER="$(command -v stapler || echo /usr/bin/stapler)"

if [ -n "${CODESIGN_IDENTITY:-}" ]; then
  echo "==> Deep signing with: $CODESIGN_IDENTITY"
  "$CODESIGN" \
      --deep \
      --options runtime \
      --entitlements "$ENTITLEMENTS" \
      --sign "$CODESIGN_IDENTITY" \
      --timestamp \
      --force \
      "$APP"
else
  echo "==> Ad-hoc signing (no Developer ID set)"
  "$CODESIGN" --force --deep --sign - "$APP"
fi

# Verify.
echo "==> Verifying signature"
# Note: --strict fails on PyInstaller bundles because it checks for
# legacy "sealed resources" that aren't used by modern .app bundles.
"$CODESIGN" --verify --deep --verbose=2 "$APP"

# Gatekeeper assessment. For Developer-ID-signed bundles this should pass;
# for ad-hoc-signed bundles it'll fail with "rejected", which is fine.
echo "==> Gatekeeper assessment"
"$SPCTL" --assess --type execute --verbose=2 "$APP" || true

# -- 2. Notarize (optional) --------------------------------------------
if [ -n "${NOTARY_PROFILE:-}" ]; then
  if [ -z "$NOTARYTOOL" ]; then
    echo "error: notarytool not found (install Xcode Command Line Tools)" >&2
    exit 1
  fi
  echo "==> Submitting to notarytool with profile: $NOTARY_PROFILE"

  # ditto --sequesterRsrc preserves extended attributes that Apple's
  # notary service uses to verify code signature integrity.
  TMP_ZIP="$(mktemp -t jobscanner-notarize).zip"
  trap 'rm -f "$TMP_ZIP"' EXIT

  /usr/bin/ditto -c -k --sequesterRsrc --keepParent "$APP" "$TMP_ZIP"

  "$NOTARYTOOL" submit "$TMP_ZIP" \
      --keychain-profile "$NOTARY_PROFILE" \
      --wait

  echo "==> Stapling the notarization ticket"
  "$STAPLER" staple "$APP"
  "$STAPLER" validate "$APP"
else
  echo "==> Skipping notarization (NOTARY_PROFILE not set)"
fi

echo "==> Done. Distribution-ready artifact: $APP"
