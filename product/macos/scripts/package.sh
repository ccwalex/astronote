#!/usr/bin/env bash
# Build a distributable AstroNote.app (client only — no backend).
# Connect to your AstroNote server over Tailscale with a device API token.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

APP_NAME="AstroNote"
BUNDLE_ID="space.astronote.mac"
MARKETING_VERSION="${MARKETING_VERSION:-${1:-0.1.0}}"
BUILD_VERSION="${BUILD_VERSION:-${MARKETING_VERSION}}"

DIST_DIR="$ROOT/dist"
APP_PATH="$DIST_DIR/${APP_NAME}.app"
CONTENTS="$APP_PATH/Contents"
MACOS_DIR="$CONTENTS/MacOS"
RESOURCES_DIR="$CONTENTS/Resources"

echo "==> AstroNote macOS package (v${MARKETING_VERSION}, build ${BUILD_VERSION})"

rm -rf "$APP_PATH"
mkdir -p "$MACOS_DIR" "$RESOURCES_DIR"

# Launch Services reads Contents/Info.plist (not Resources/) for ATS exceptions.
INFO_PLIST="$CONTENTS/Info.plist"
sed \
  -e "s/\$(MARKETING_VERSION)/${MARKETING_VERSION}/g" \
  -e "s/\$(BUILD_VERSION)/${BUILD_VERSION}/g" \
  "$ROOT/Resources/Info.plist" > "$INFO_PLIST"
cp "$INFO_PLIST" "$RESOURCES_DIR/Info.plist"
printf 'APPL????' > "$CONTENTS/PkgInfo"

build_arch() {
  local triple="$1"
  # Avoid Mach-O __info_plist; packaged apps use Contents/Info.plist for ATS.
  ASTRONOTE_EMBED_PLIST=0 swift build -c release --triple "$triple" 1>&2
  echo "$ROOT/.build/${triple}/release/${APP_NAME}"
}

ARM_BIN="$(build_arch "arm64-apple-macosx")"
X64_BIN="$(build_arch "x86_64-apple-macosx")"
UNIVERSAL="$ROOT/.build/universal-release/${APP_NAME}"
mkdir -p "$(dirname "$UNIVERSAL")"
lipo -create -output "$UNIVERSAL" "$ARM_BIN" "$X64_BIN"
echo "==> Universal binary: $(lipo -info "$UNIVERSAL")"

cp "$UNIVERSAL" "$MACOS_DIR/${APP_NAME}"
chmod +x "$MACOS_DIR/${APP_NAME}"

xattr -cr "$APP_PATH" 2>/dev/null || true

ENTITLEMENTS="$ROOT/Resources/AstroNote.entitlements"

if codesign --force --deep --sign - --entitlements "$ENTITLEMENTS" "$APP_PATH" 2>/dev/null; then
  echo "==> Ad-hoc signed ${APP_NAME}.app"
else
  echo "==> Warning: codesign failed; app may be blocked by Gatekeeper until signed."
fi

ZIP_PATH="$DIST_DIR/${APP_NAME}-${MARKETING_VERSION}-macOS-universal.zip"
(
  cd "$DIST_DIR"
  ditto -c -k --keepParent "${APP_NAME}.app" "$(basename "$ZIP_PATH")"
)

DMG_PATH="$DIST_DIR/${APP_NAME}-${MARKETING_VERSION}-macOS-universal.dmg"
STAGING="$DIST_DIR/dmg-staging"
rm -rf "$STAGING"
mkdir -p "$STAGING"
cp -R "$APP_PATH" "$STAGING/"
ln -s /Applications "$STAGING/Applications"
hdiutil create -volname "$APP_NAME" -srcfolder "$STAGING" -ov -format UDZO "$DMG_PATH" >/dev/null
rm -rf "$STAGING"

echo ""
echo "Done."
echo "  App:  $APP_PATH"
echo "  Zip:  $ZIP_PATH"
echo "  DMG:  $DMG_PATH"
echo ""
echo "Install: drag AstroNote.app to Applications, open once, then connect with"
echo "  Server: http://<your-machine>.<tailnet>:5173  (or http://100.x.x.x:5173)"
echo "  Token:  mint on server — python3 code/astronote_token_cli.py mint --label Mac"
