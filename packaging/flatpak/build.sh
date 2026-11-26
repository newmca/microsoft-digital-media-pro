#!/usr/bin/env bash
# Build dist/DigitalMediaProKeys-<version>.flatpak (host-side entry point).
#
# Needs flatpak-builder (or the org.flatpak.Builder flatpak). The flathub remote is added to
# the user installation if missing, and the KDE runtime/SDK and PySide6 BaseApp are
# installed from it (--user) on demand.
set -euo pipefail
. "$(dirname "$0")/../common.sh"

manifest="$ROOT/packaging/flatpak/$APP_ID.yml"
bundle="$DIST/DigitalMediaProKeys-$VERSION.flatpak"
work="$ROOT/build/flatpak"

if command -v flatpak-builder >/dev/null; then
    builder=(flatpak-builder)
elif flatpak info --user org.flatpak.Builder >/dev/null 2>&1 || flatpak info org.flatpak.Builder >/dev/null 2>&1; then
    builder=(flatpak run org.flatpak.Builder)
else
    die "flatpak-builder not found (install it, or: flatpak install --user flathub org.flatpak.Builder)"
fi

flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo

mkdir -p "$DIST" "$work"
log "flatpak-builder"
cd "$ROOT"
"${builder[@]}" --force-clean --user \
    --install-deps-from=flathub --default-branch=stable \
    --state-dir="$ROOT/.flatpak-builder" --repo="$work/repo" "$work/build" "$manifest"

log "Bundling"
flatpak build-bundle --runtime-repo=https://dl.flathub.org/repo/flathub.flatpakrepo "$work/repo" "$bundle" "$APP_ID" stable
ls -l "$bundle"
