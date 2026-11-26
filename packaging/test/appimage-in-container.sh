#!/usr/bin/env bash
# Run the AppImage in a clean container (no FUSE). Runs as a plain user would, so Qt's
# desktop libraries are installed first; --version and status are also checked before that.
. /src/packaging/common.sh
appimage=$(ls /out/DigitalMediaProKeys-"$APP_VERSION"-x86_64.AppImage)
quiet() { local log; log="$("$@" 2>&1)" || { echo "$log" >&2; return 1; }; }
echo "container: $(. /etc/os-release && echo "$PRETTY_NAME")"

run=("$appimage" --appimage-extract-and-run)
[ "$("${run[@]}" --version)" = "dmpkeys $APP_VERSION" ]
"${run[@]}" status | grep -q '^Keyboard: '
echo "  ok    runs bare (--version, status) via --appimage-extract-and-run"

# Libraries every desktop already has but a bare container lacks.
. /etc/os-release
case "$ID" in
ubuntu|debian)
    export DEBIAN_FRONTEND=noninteractive
    quiet apt-get update
    quiet apt-get install -y --no-install-recommends libgl1 libegl1 libfontconfig1 libdbus-1-3 \
        libxkbcommon0 libglib2.0-0 ;;
fedora)
    quiet dnf -y install mesa-libGL mesa-libEGL fontconfig dbus-libs libxkbcommon glib2 ;;
esac

# Extract once so the bundled interpreter can be checked directly.
cd /tmp && "$appimage" --appimage-extract >/dev/null
PY=/tmp/squashfs-root/opt/python/bin/python3 DMPKEYS="${run[*]}" /src/packaging/test/check.sh
# The extracted AppRun must work too (this is what the mounted AppImage executes).
[ "$(/tmp/squashfs-root/AppRun --version)" = "dmpkeys $APP_VERSION" ]
echo "  ok    extracted AppRun --version"
