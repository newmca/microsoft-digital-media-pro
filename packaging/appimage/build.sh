#!/usr/bin/env bash
# Build the x86_64 AppImage into dist/ inside an Ubuntu 22.04 container (host-side entry point).
set -euo pipefail
. "$(dirname "$0")/../common.sh"

[ "$(uname -m)" = x86_64 ] || die "the AppImage build only supports x86_64 hosts"
"$ROOT/packaging/make-source.sh" >/dev/null
log "AppImage build in $APPIMAGE_IMAGE"
container_run "$APPIMAGE_IMAGE" packaging/appimage/build-in-container.sh
ls -l "$DIST"/*.AppImage
