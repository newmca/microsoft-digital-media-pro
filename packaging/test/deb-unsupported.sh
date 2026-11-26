#!/usr/bin/env bash
# Expected failure: the distribution has no PySide6 packages, so the DEB cannot be installed.
. /src/packaging/common.sh
export DEBIAN_FRONTEND=noninteractive
apt-get update >/dev/null
echo "container: $(. /etc/os-release && echo "$PRETTY_NAME")"
if log=$(apt-get install -y --no-install-recommends /out/dmpkeys_"$APP_VERSION"_all.deb 2>&1); then
    echo "unexpected: the DEB installed here; add this release to DEB_TEST_IMAGES" >&2
    exit 1
fi
echo "$log" | grep -q 'python3-pyside6' || { echo "$log" >&2; echo "failed for a different reason" >&2; exit 1; }
echo "  ok    refuses to install (python3-pyside6.* not available), as expected"
