#!/usr/bin/env bash
# Install /out/<package> in a clean container and check it. usage: native-in-container.sh rpm|deb
. /src/packaging/common.sh
kind="$1"

# Run a noisy package-manager command, showing its output only if it fails.
quiet() { local log; log="$("$@" 2>&1)" || { echo "$log" >&2; return 1; }; }

echo "container: $(. /etc/os-release && echo "$PRETTY_NAME")"
case "$kind" in
rpm)
    quiet dnf -y install /out/dmpkeys-"$APP_VERSION"-*.noarch.rpm libxml2 desktop-file-utils appstream
    ;;
deb)
    export DEBIAN_FRONTEND=noninteractive
    quiet apt-get update
    quiet apt-get install -y --no-install-recommends /out/dmpkeys_"$APP_VERSION"_all.deb \
        libxml2-utils desktop-file-utils appstream
    ;;
esac
echo "installed $kind"

helper=/usr/libexec/dmpkeys/dmpkeys-helper
[ -x "$helper" ] || { echo "$helper is not executable" >&2; exit 1; }
[ "$(head -1 "$helper")" = '#!/usr/bin/python3 -I' ] || { echo "unexpected helper shebang" >&2; exit 1; }
[ "$(stat -c %U:%a "$helper")" = root:755 ] || { echo "helper has wrong owner/mode" >&2; exit 1; }
printf '  ok    %s is root:755 with an isolated-python shebang\n' "$helper"
# The helper must at least start and reject a bad command (as root, without polkit).
if "$helper" bogus >/dev/null 2>&1; then echo "helper accepted a bogus command" >&2; exit 1; fi
printf '  ok    helper runs and rejects an unknown command\n'

policy=/usr/share/polkit-1/actions/$APP_ID.policy
xmllint --noout "$policy"
grep -q 'org.freedesktop.policykit.exec.path">/usr/libexec/dmpkeys/dmpkeys-helper<' "$policy"
printf '  ok    polkit policy parses and points at the helper\n'

desktop-file-validate "/usr/share/applications/$APP_ID.desktop"
appstreamcli validate --no-net "/usr/share/metainfo/$APP_ID.metainfo.xml" >/dev/null
test -s "/usr/share/icons/hicolor/scalable/apps/$APP_ID.svg"
printf '  ok    desktop file, metainfo and icon are installed and valid\n'

PY=python3 DMPKEYS=dmpkeys /src/packaging/test/check.sh
