#!/usr/bin/env bash
# Runs inside the Ubuntu 22.04 container. See build.sh.
#
# Ubuntu 22.04 (glibc 2.35) is the oldest base the PySide6 wheel (manylinux_2_34)
# runs on, so the AppImage works on any distribution at least that recent.
. /src/packaging/common.sh
here=/src/packaging/appimage

# Pinned build inputs (sha256 checked).
PYTHON_URL=https://github.com/astral-sh/python-build-standalone/releases/download/20261124/cpython-3.13.18%2B20261124-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz
PYTHON_SHA256=b56ceb4fc1d8f0c49b7bd4dc91cd176bad7b86a88b9fc509bae6b10b3ee36692
APPIMAGETOOL_URL=https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage
APPIMAGETOOL_SHA256=ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0
RUNTIME_URL=https://github.com/AppImage/type2-runtime/releases/download/20251108/runtime-x86_64
RUNTIME_SHA256=2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d

# X11/xkb libraries Qt's xcb plugin links against that are not part of every
# desktop install. Core libs (libxcb, libX11, libGL, fontconfig, ...) come from the host.
XCB_PACKAGES="libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0
 libxcb-shape0 libxcb-xkb1 libxcb-util1 libxkbcommon-x11-0"

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends curl ca-certificates binutils squashfs-tools \
    desktop-file-utils file $XCB_PACKAGES >/dev/null

work=/tmp/appimage
rm -rf "$work"
mkdir -p "$work/dl" "$work/src"

fetch() {  # fetch URL SHA256 FILE
    curl -fsSL "$1" -o "$work/dl/$3"
    echo "$2  $work/dl/$3" | sha256sum -c --quiet - || die "checksum mismatch for $1"
}
fetch "$PYTHON_URL" "$PYTHON_SHA256" python.tar.gz
fetch "$APPIMAGETOOL_URL" "$APPIMAGETOOL_SHA256" appimagetool
fetch "$RUNTIME_URL" "$RUNTIME_SHA256" runtime
chmod +x "$work/dl/appimagetool"

appdir="$work/AppDir"
mkdir -p "$appdir/opt" "$appdir/usr/lib" "$appdir/usr/share"/{applications,metainfo,icons/hicolor/scalable/apps}
tar -C "$appdir/opt" -xzf "$work/dl/python.tar.gz"
py="$appdir/opt/python/bin/python3"

log "Installing dependencies and dmpkeys"
tar -C "$work/src" -xzf "/out/src/dmpkeys-$APP_VERSION.tar.gz"
"$py" -m pip install -q --no-compile --require-hashes --only-binary=:all: \
    --root-user-action=ignore -r "$here/requirements.txt"
"$py" -m pip install -q --no-compile --no-deps --root-user-action=ignore "$work/src/dmpkeys-$APP_VERSION"

site="$("$py" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
"$py" "$here/prune.py" "$site"

# The AppImage only needs to run dmpkeys: drop pip/setuptools and the stdlib extras.
"$py" -m pip uninstall -y -q --root-user-action=ignore pip setuptools 2>/dev/null || true
pylib="$appdir/opt/python/lib/python3.13"
rm -rf "$pylib"/{test,idlelib,tkinter,turtledemo,ensurepip,lib2to3} "$appdir/opt/python/share" \
       "$appdir/opt/python/include"
"$py" -m compileall -q -j0 "$appdir/opt/python/lib" "$site" >/dev/null || true
find "$appdir" -name '*.a' -delete

# Bundle the xcb helper libraries (resolved through the xcb plugin's own links).
xcb_plugin="$site/PySide6/Qt/plugins/platforms/libqxcb.so"
LD_LIBRARY_PATH="$site/PySide6/Qt/lib" ldd "$xcb_plugin" | awk '/=> \/(usr\/)?lib/ {print $3}' \
    | grep -E 'libxcb-(cursor|icccm|image|keysyms|render-util|shape|xkb|util)|libxkbcommon-x11' \
    | while read -r lib; do cp -L "$lib" "$appdir/usr/lib/"; done

install -m0755 "$here/AppRun" "$appdir/AppRun"
install -m0644 "/src/data/$APP_ID.desktop" "$appdir/$APP_ID.desktop"
install -m0644 "/src/data/$APP_ID.desktop" "$appdir/usr/share/applications/"
install -m0644 "/src/data/$APP_ID.metainfo.xml" "$appdir/usr/share/metainfo/"
icon="/src/data/icons/hicolor/scalable/apps/$APP_ID.svg"
install -m0644 "$icon" "$appdir/$APP_ID.svg"
install -m0644 "$icon" "$appdir/usr/share/icons/hicolor/scalable/apps/"
ln -s "$APP_ID.svg" "$appdir/.DirIcon"

log "Packing AppImage"
# appimagetool is itself an AppImage; extract it so no FUSE is needed.
(cd "$work/dl" && ./appimagetool --appimage-extract >/dev/null)
out="/out/DigitalMediaProKeys-$APP_VERSION-x86_64.AppImage"
rm -f /out/*.AppImage
ARCH=x86_64 "$work/dl/squashfs-root/AppRun" --no-appstream --runtime-file "$work/dl/runtime" \
    "$appdir" "$out"
hand_back_out
