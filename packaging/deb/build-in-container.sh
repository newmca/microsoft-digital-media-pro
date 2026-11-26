#!/usr/bin/env bash
# Runs inside the Debian container. See build.sh.
. /src/packaging/common.sh

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends build-essential debhelper dpkg-dev fakeroot >/dev/null

work=/tmp/build
rm -rf "$work"
mkdir -p "$work"
tar -C "$work" -xzf "/out/src/dmpkeys-$APP_VERSION.tar.gz"
cd "$work/dmpkeys-$APP_VERSION"
cp -r /src/packaging/deb/debian debian
sed -i "s/@VERSION@/$APP_VERSION/" debian/changelog

# Installs the Build-Depends from debian/control.
apt-get build-dep -y -qq . >/dev/null 2>&1 || {
    apt-get install -y -qq --no-install-recommends devscripts equivs >/dev/null
    mk-build-deps --install --remove --root-cmd '' \
        --tool 'apt-get -y -qq --no-install-recommends' debian/control >/dev/null
}
dpkg-buildpackage -us -uc -b

rm -f /out/dmpkeys_*.deb
cp "$work"/dmpkeys_*_all.deb /out/
hand_back_out
