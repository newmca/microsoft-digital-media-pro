"""Command line entry point. With no command, starts the GUI."""
from __future__ import annotations

import argparse
import sys

from . import APP_NAME, __version__


def _backend():
    from .core.backend import Backend
    return Backend()


def cmd_status(_args) -> int:
    b = _backend()
    s = b.status()
    print(f"Keyboard: {'connected' if s.connected else 'not connected'}")
    for i in s.interfaces:
        print(f"  {i.hid_id} interface {i.number} driver={i.driver or 'none'} nodes={','.join(i.event_nodes)}")
    print(f"Favorites fix: {'installed' if s.favorites_fix_installed else 'not installed'}"
          f", {'active' if s.favorites_active else 'inactive'}")
    print(f"Key mapping file: {'installed' if s.hwdb_installed else 'not installed'}")
    for p in s.legacy_hwdb + s.legacy_rules:
        print(f"Other config for this keyboard: {p}")
    print(f"Desktop: {b.desktop_name}; packaging: {b.packaging().value}")
    return 0


def cmd_plan(_args) -> int:
    b = _backend()
    plan = b.plan()
    for b_ in plan.bindings:
        how = f"remapped to {b_.carrier.name}" if b_.remapped else "native key"
        print(f"{b_.key.label}: {b_.action.describe()} via {b_.carrier.keysym} ({how})")
    for scan, name in sorted(plan.remaps.items()):
        print(f"remap {scan:x} -> {name}")
    for key_id, err in plan.errors.items():
        print(f"ERROR {key_id}: {err}")
    for w in plan.warnings:
        print(f"warning: {w}")
    change = b.system_change(plan)
    print(f"System change needed: {change.needed}")
    return 0 if plan.ok else 1


def _print_report(report) -> int:
    for m in report.messages:
        print(m)
    for e in report.errors:
        print(f"ERROR: {e}", file=sys.stderr)
    for k, e in report.key_errors.items():
        print(f"ERROR {k}: {e}", file=sys.stderr)
    return 0 if report.ok else 1


def cmd_apply(args) -> int:
    return _print_report(_backend().apply(disable_legacy=not args.keep_legacy))


def cmd_reset(_args) -> int:
    return _print_report(_backend().reset_all())


def cmd_import(_args) -> int:
    for note in _backend().import_existing():
        print(note)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dmpkeys", description=APP_NAME)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("status", help="show keyboard and setup state").set_defaults(func=cmd_status)
    sub.add_parser("plan", help="show what Apply would do").set_defaults(func=cmd_plan)
    p = sub.add_parser("apply", help="apply the saved configuration")
    p.add_argument("--keep-legacy", action="store_true", help="don't disable other configs for this keyboard")
    p.set_defaults(func=cmd_apply)
    sub.add_parser("reset", help="remove everything dmpkeys installed").set_defaults(func=cmd_reset)
    sub.add_parser("import", help="adopt an existing hand-made setup into the config").set_defaults(func=cmd_import)
    args = parser.parse_args(argv)
    if args.command is None:
        from .ui.app import run
        return run()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
