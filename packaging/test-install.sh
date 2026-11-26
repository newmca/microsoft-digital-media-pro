#!/usr/bin/env bash
# Install each artifact from dist/ in a clean environment and check it.
#   packaging/test-install.sh [rpm] [deb] [appimage] [flatpak]    (default: all four)
# rpm/deb/appimage run in throwaway containers; flatpak installs --user on this host
# and uninstalls the app again afterwards (runtimes are left alone).
set -euo pipefail
. "$(dirname "$0")/common.sh"

APPIMAGE_TEST_IMAGES="${APPIMAGE_TEST_IMAGES:-ubuntu:22.04 debian:12 fedora:44}"
# Ubuntu 24.04 ships no PySide6 packages; the DEB must refuse to install there.
DEB_UNSUPPORTED_IMAGES="${DEB_UNSUPPORTED_IMAGES:-ubuntu:24.04}"

test_rpm() {
    log "RPM on $RPM_IMAGE"
    container_run "$RPM_IMAGE" packaging/test/native-in-container.sh rpm
}

test_deb() {
    local image
    for image in $DEB_TEST_IMAGES; do
        log "DEB on $image"
        container_run "$image" packaging/test/native-in-container.sh deb
    done
    for image in $DEB_UNSUPPORTED_IMAGES; do
        log "DEB on $image (expected to be uninstallable)"
        container_run "$image" packaging/test/deb-unsupported.sh
    done
}

test_appimage() {
    local image
    for image in $APPIMAGE_TEST_IMAGES; do
        log "AppImage on $image"
        container_run "$image" packaging/test/appimage-in-container.sh
    done
}

test_flatpak() {
    local bundle="$DIST/DigitalMediaProKeys-$VERSION.flatpak"
    [ -f "$bundle" ] || die "$bundle not found"
    log "Flatpak (user install on this host)"
    flatpak install --user -y --noninteractive "$bundle" >/dev/null
    trap 'flatpak uninstall --user -y --noninteractive "$APP_ID" >/dev/null' RETURN
    local fp=(flatpak run --command=dmpkeys "$APP_ID")
    [ "$("${fp[@]}" --version)" = "dmpkeys $VERSION" ]
    "${fp[@]}" status | grep -q '^Keyboard: '
    flatpak run --command=python3 "$APP_ID" -I -c \
        'import PySide6.QtCore, PySide6.QtGui, PySide6.QtWidgets, PySide6.QtSvg, PySide6.QtSvgWidgets, jeepney'
    flatpak run --command=sh "$APP_ID" -c 'test -d /sys/bus/hid/devices && ls /run/host/usr/share/applications >/dev/null && ls /run/host/etc >/dev/null'
    if [ -z "${CI:-}" ]; then   # CI runners have no session helper behind flatpak-spawn --host
        flatpak run --command=flatpak-spawn "$APP_ID" --host true
    else
        echo "  SKIP  flatpak-spawn --host (CI)"
    fi
    if flatpak run --command=python3 "$APP_ID" -I -c 'import importlib.util as u, sys; sys.exit(0 if u.find_spec("dmpkeys.ui.app") else 1)'; then
        flatpak run --env=QT_QPA_PLATFORM=offscreen --command=python3 "$APP_ID" -c 'import dmpkeys.ui.app'
        echo "  ok    GUI import under QT_QPA_PLATFORM=offscreen"
    else
        echo "  SKIP  GUI import: dmpkeys.ui.app is not in this package"
    fi
    echo "  ok    flatpak: version, status, imports, sandbox paths"
}

targets=("$@")
[ ${#targets[@]} -gt 0 ] || targets=(rpm deb appimage flatpak)
for t in "${targets[@]}"; do
    case "$t" in
        rpm|deb|appimage|flatpak) "test_$t" ;;
        *) die "unknown target: $t" ;;
    esac
done
log "all requested install tests passed: ${targets[*]}"
