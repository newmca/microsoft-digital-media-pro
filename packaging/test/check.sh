#!/usr/bin/env bash
# Checks shared by every install test. Runs inside a test container.
#   PY       interpreter dmpkeys was installed for (python3, or the AppImage's bundled one)
#   DMPKEYS  command line that starts dmpkeys (dmpkeys, or the AppImage invocation)
# Exits non-zero on the first failing check.
set -euo pipefail
: "${PY:?}" "${DMPKEYS:?}" "${APP_VERSION:?}"

pass() { printf '  ok    %s\n' "$*"; }

out="$($DMPKEYS --version)"
[ "$out" = "dmpkeys $APP_VERSION" ] || { echo "unexpected --version output: $out" >&2; exit 1; }
pass "--version: $out"

# `status` must work with no keyboard and no desktop session.
status="$($DMPKEYS status)"
echo "$status" | grep -q '^Keyboard: ' || { echo "unexpected status output: $status" >&2; exit 1; }
pass "status: $(echo "$status" | head -1)"

$PY -I -c 'import PySide6.QtCore, PySide6.QtGui, PySide6.QtWidgets, PySide6.QtSvg, PySide6.QtSvgWidgets, jeepney'
pass "imports: PySide6 QtCore/Gui/Widgets/Svg/SvgWidgets, jeepney"

# Qt platform, SVG image-format and icon-engine plugins load (catches an over-pruned bundle).
svg="$(mktemp --suffix=.svg)"
echo '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16"><rect width="16" height="16" fill="red"/></svg>' >"$svg"
QT_QPA_PLATFORM=offscreen $PY -I -c '
import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from PySide6.QtSvg import QSvgRenderer
app = QApplication([])
assert QSvgRenderer(sys.argv[1]).isValid(), "svg renderer"
assert not QIcon(sys.argv[1]).pixmap(16, 16).isNull(), "svg icon"
' "$svg"
rm -f "$svg"
pass "QApplication (offscreen) + SVG rendering and icons"

# GUI smoke test: only once the UI exists in the installed package.
if $PY -I -c 'import importlib.util as u, sys; sys.exit(0 if u.find_spec("dmpkeys.ui.app") else 1)' 2>/dev/null; then
    QT_QPA_PLATFORM=offscreen $PY -c 'import dmpkeys.ui.app'
    pass "GUI import under QT_QPA_PLATFORM=offscreen"
else
    echo "  SKIP  GUI import: dmpkeys.ui.app is not in this package"
fi
