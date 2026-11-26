#!/usr/bin/env bash
# Rebuild every package into dist/.   packaging/build-all.sh [rpm] [deb] [appimage] [flatpak]
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
targets=("$@")
[ ${#targets[@]} -gt 0 ] || targets=(rpm deb appimage flatpak)
for t in "${targets[@]}"; do
    case "$t" in
        rpm|deb|appimage|flatpak) "$here/$t/build.sh" ;;
        *) echo "unknown target: $t" >&2; exit 1 ;;
    esac
done
