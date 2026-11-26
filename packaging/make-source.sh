#!/usr/bin/env bash
# Create dist/src/dmpkeys-<version>.tar.gz, the source tree RPM and DEB builds from.
set -euo pipefail
. "$(dirname "$0")/common.sh"

for f in README.md LICENSE; do
    [ -f "$ROOT/$f" ] || die "$f is missing from the repository root"
done

out="$DIST/src/dmpkeys-$VERSION.tar.gz"
mkdir -p "$DIST/src"
tar -C "$ROOT" --sort=name --mtime='UTC 2026-11-25' --owner=0 --group=0 --numeric-owner \
    --exclude='__pycache__' --exclude='*.pyc' --exclude='*.egg-info' \
    --transform "s,^,dmpkeys-$VERSION/," \
    -czf "$out" pyproject.toml README.md LICENSE src data
echo "$out"
