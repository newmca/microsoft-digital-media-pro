#!/usr/bin/env bash
# Runs inside the Fedora container. See build.sh.
. /src/packaging/common.sh

dnf -y -q install rpm-build python3-devel pyproject-rpm-macros desktop-file-utils appstream libxml2 >/dev/null

top=/tmp/rpmbuild
mkdir -p "$top"/{SOURCES,SPECS}
cp "/out/src/dmpkeys-$APP_VERSION.tar.gz" "$top/SOURCES/"
cp /src/packaging/rpm/dmpkeys.spec "$top/SPECS/"

defs=(--define "_topdir $top" --define "dmpkeys_version $APP_VERSION")
spec="$top/SPECS/dmpkeys.spec"

# %generate_buildrequires only runs under rpmbuild, so iterate: -br writes a
# .buildreqs.nosrc.rpm, builddep installs it, repeat until the build can start.
for _ in 1 2 3; do
    dnf -y -q builddep "${defs[@]}" "$spec" >/dev/null
    if rpmbuild -br "${defs[@]}" "$spec" >/dev/null 2>&1; then break; fi
    dnf -y -q builddep "$top"/SRPMS/*.buildreqs.nosrc.rpm >/dev/null
done
rpmbuild -ba "${defs[@]}" "$spec"

rm -f /out/dmpkeys-*.rpm
cp "$top"/RPMS/noarch/*.rpm "$top"/SRPMS/*.src.rpm /out/
hand_back_out
