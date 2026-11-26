"""Keyboard and system state readable without root (sysfs, /etc)."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import host, hwdb

SYSFS_HID = Path("/sys/bus/hid/devices")
HID_PREFIX = "0003:045E:00B0."
RULES_DIR = Path("/etc/udev/rules.d")
RULE_FILE = RULES_DIR / "70-dmpkeys-hid-microsoft.rules"
REBIND_SCRIPT = Path("/usr/local/libexec/dmpkeys-hid-rebind")


@dataclass(frozen=True)
class Interface:
    hid_id: str      # 0003:045E:00B0.0006
    phys: str        # usb-0000:00:14.0-5.3/input1
    driver: str      # hid-generic | microsoft | ""
    event_nodes: tuple[str, ...]

    @property
    def number(self) -> int | None:
        m = re.search(r"/input(\d+)$", self.phys)
        return int(m.group(1)) if m else None


@dataclass
class Status:
    connected: bool
    interfaces: list[Interface] = field(default_factory=list)
    favorites_fix_installed: bool = False
    hwdb_installed: bool = False
    legacy_hwdb: list[Path] = field(default_factory=list)
    legacy_rules: list[Path] = field(default_factory=list)

    @property
    def favorites_active(self) -> bool:
        """Interface 1 (the one carrying the favorites keys) is on hid-microsoft."""
        return any(i.number == 1 and i.driver == "microsoft" for i in self.interfaces)


def _read_uevent(path: Path) -> dict[str, str]:
    try:
        return dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line)
    except OSError:
        return {}


def interfaces(sysfs: Path = SYSFS_HID) -> list[Interface]:
    out = []
    try:
        entries = sorted(p for p in sysfs.iterdir() if p.name.startswith(HID_PREFIX))
    except OSError:
        return []
    for dev in entries:
        uevent = _read_uevent(dev / "uevent")
        driver = os.path.basename(os.readlink(dev / "driver")) if (dev / "driver").is_symlink() else ""
        events = tuple(sorted(e.name for e in dev.glob("input/input*/event*")))
        out.append(Interface(dev.name, uevent.get("HID_PHYS", ""), driver, events))
    return out


def legacy_rules(rules_dir: Path | None = None) -> list[Path]:
    """Other udev rules in /etc that target this keyboard (e.g. a hand-made rebind rule).
    Returns host paths."""
    out = []
    readable_dir = rules_dir or host.host_path(RULES_DIR)
    for readable in sorted(readable_dir.glob("*.rules")):
        path = RULES_DIR / readable.name if rules_dir is None else readable
        if path == RULE_FILE:
            continue
        try:
            text = readable.read_text()
        except OSError:
            continue
        if re.search("045E", text, re.I) and re.search("00B0", text, re.I):
            out.append(path)
    return out


def status() -> Status:
    ifaces = interfaces()
    return Status(
        connected=bool(ifaces),
        interfaces=ifaces,
        favorites_fix_installed=(host.host_path(RULE_FILE).exists()
                                 and host.host_path(REBIND_SCRIPT).exists()),
        hwdb_installed=host.host_path(hwdb.HWDB_FILE).exists(),
        legacy_hwdb=hwdb.legacy_files(),
        legacy_rules=legacy_rules(),
    )
