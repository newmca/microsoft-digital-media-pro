#!/usr/bin/python3 -I
"""dmpkeys privileged helper. Runs as root via pkexec.

Self-contained (stdlib only, Python >= 3.8) because it runs in three ways:
  * installed as /usr/libexec/dmpkeys/dmpkeys-helper (RPM/DEB, own polkit action)
  * `pkexec /usr/bin/python3 -I -c <this source> ...` from an AppImage or
    Flatpak, where no file of ours exists on the host.
It never trusts its input: every path it touches is a fixed constant or is
re-validated here, and hwdb content is checked line by line.

Commands (JSON results on stdout, one object per line):
  apply      read {"hwdb": str|null, "favorites_fix": bool, "disable": [path]}
             from stdin; install/remove our files and reload udev.
  capture N  stream key events from the keyboard for up to N seconds (<= 60),
             or until stdin closes.
  reset      remove everything dmpkeys installed.
"""
import json
import os
import re
import select
import shutil
import struct
import subprocess
import sys
import time

HWDB_DIR = "/etc/udev/hwdb.d"
HWDB_FILE = HWDB_DIR + "/70-dmpkeys.hwdb"
RULES_DIR = "/etc/udev/rules.d"
RULE_FILE = RULES_DIR + "/70-dmpkeys-hid-microsoft.rules"
REBIND_DIR = "/usr/local/libexec"
REBIND_SCRIPT = REBIND_DIR + "/dmpkeys-hid-rebind"
DISABLED_SUFFIX = ".disabled-by-dmpkeys"
HID_DEVICES = "/sys/bus/hid/devices"
HID_PREFIX = "0003:045E:00B0."
HWDB_MATCH = "evdev:input:b0003v045Ep00B0*"

_ENTRY_RE = re.compile(r"^ KEYBOARD_KEY_[0-9a-f]{1,8}=[a-z0-9_]{1,40}$")
_DEVICE_RE = re.compile(r"v045Ep00B0", re.IGNORECASE)
_RULE_DEVICE_RE = re.compile(r"045E", re.IGNORECASE)
_RULE_PRODUCT_RE = re.compile(r"00B0", re.IGNORECASE)

RULE = (
    "# Installed by Digital Media Pro Keys (dmpkeys).\n"
    "# Microsoft Digital Media Pro Keyboard (USB 045E:00B0): move interface 1 from\n"
    "# hid-generic to hid-microsoft so the My Favorites 1-5 keys work. \"add\" covers\n"
    "# the boot-time coldplug replay (hid-generic is usually built in and claims the\n"
    "# keyboard first); \"bind\" covers a replug.\n"
    'ACTION=="add|bind", SUBSYSTEM=="hid", DRIVER=="hid-generic", '
    'ENV{HID_ID}=="0003:0000045E:000000B0", ENV{HID_PHYS}=="*/input1", '
    'RUN+="' + REBIND_SCRIPT + ' %k"\n'
)

REBIND = r"""#!/bin/sh
# Installed by Digital Media Pro Keys (dmpkeys). Called by udev with the HID id
# of the keyboard's interface 1 (e.g. 0003:045E:00B0.0006).
#
# Moves that interface from hid-generic to hid-microsoft with the MS_ERGONOMY
# quirk (driver_data 0x2), which the kernel gives the sibling Digital Media
# keyboard 045E:00B4 but not 00B0. Without it the My Favorites 1-5 keys
# (vendor usage 0xff00:0xff05) are dropped. Interface 0 (typing) is never
# touched, so a failure here can't take the keyboard down.
set -u
PATH=/usr/sbin:/usr/bin:/sbin:/bin
id=$1
gen=/sys/bus/hid/drivers/hid-generic
ms=/sys/bus/hid/drivers/microsoft
log() { logger -t dmpkeys "$id: $*" 2>/dev/null || true; }
driver() { d=$(readlink "/sys/bus/hid/devices/$id/driver" 2>/dev/null) && basename "$d"; }

exec 9>/run/dmpkeys-hid-rebind.lock
flock 9

modprobe hid-microsoft || { log "modprobe hid-microsoft failed"; exit 1; }
[ "$(driver)" = microsoft ] && exit 0
if [ "$(driver)" = hid-generic ]; then
    echo "$id" > "$gen/unbind" || { log "unbind from hid-generic failed"; exit 1; }
fi
# Writing new_id attaches matching unbound devices itself; bind explicitly if
# the id was already registered (then nothing auto-attaches).
echo "0003 045E 00B0 2" > "$ms/new_id" 2>/dev/null
[ "$(driver)" = microsoft ] || echo "$id" > "$ms/bind" 2>/dev/null
if [ "$(driver)" != microsoft ]; then
    log "could not bind to hid-microsoft (driver now: $(driver || echo none))"
    exit 1
fi
"""


class HelperError(Exception):
    pass


def emit(**obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def run(cmd):
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          universal_newlines=True)
    emit(event="run", cmd=cmd, rc=proc.returncode, output=proc.stdout.strip()[-2000:])
    return proc.returncode == 0


def write_file(path, content, mode):
    directory = os.path.dirname(path)
    created_dir = not os.path.isdir(directory)
    os.makedirs(directory, mode=0o755, exist_ok=True)
    tmp = path + ".dmpkeys-tmp"
    with open(tmp, "w") as f:
        f.write(content)
    os.chmod(tmp, mode)
    os.replace(tmp, path)
    restore_context(([directory] if created_dir else []) + [path])
    emit(event="wrote", path=path)


def restore_context(paths):
    """Give new files their default SELinux label (e.g. bin_t for the rebind
    script, so udev may execute it). No-op without SELinux."""
    if paths and shutil.which("restorecon") and os.path.exists("/sys/fs/selinux/enforce"):
        subprocess.run(["restorecon"] + list(paths), stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)


def remove_file(path):
    if os.path.lexists(path):
        os.remove(path)
        emit(event="removed", path=path)


def validate_hwdb(text):
    if len(text) > 64 * 1024:
        raise HelperError("hwdb content too large")
    seen_match = False
    for n, line in enumerate(text.splitlines(), 1):
        if not line or line.startswith("#"):
            continue
        if line == HWDB_MATCH and not seen_match:
            seen_match = True
            continue
        if seen_match and _ENTRY_RE.match(line):
            continue
        raise HelperError("hwdb line %d not allowed: %r" % (n, line[:80]))
    if not seen_match:
        raise HelperError("hwdb content lacks the device match line")


def validate_disable(path):
    """Only other files that configure this keyboard may be disabled."""
    real = os.path.realpath(path)
    directory, name = os.path.split(real)
    if real in (HWDB_FILE, RULE_FILE) or not os.path.isfile(real):
        raise HelperError("refusing to disable %s" % path)
    with open(real, errors="replace") as f:
        text = f.read(256 * 1024)
    if directory == HWDB_DIR and name.endswith(".hwdb"):
        ok = any(_DEVICE_RE.search(l) for l in text.splitlines()
                 if l and not l[0].isspace() and not l.startswith("#"))
    elif directory == RULES_DIR and name.endswith(".rules"):
        ok = bool(_RULE_DEVICE_RE.search(text) and _RULE_PRODUCT_RE.search(text))
    else:
        ok = False
    if not ok:
        raise HelperError("refusing to disable %s: not a config for this keyboard" % path)
    return real


def interfaces():
    try:
        names = sorted(n for n in os.listdir(HID_DEVICES) if n.startswith(HID_PREFIX))
    except OSError:
        return []
    out = []
    for name in names:
        phys = ""
        try:
            with open(os.path.join(HID_DEVICES, name, "uevent")) as f:
                for line in f:
                    if line.startswith("HID_PHYS="):
                        phys = line.strip().split("=", 1)[1]
        except OSError:
            pass
        out.append((name, phys))
    return out


def event_nodes():
    nodes = []
    for name, _ in interfaces():
        base = os.path.join(HID_DEVICES, name, "input")
        try:
            for inp in os.listdir(base):
                for ev in os.listdir(os.path.join(base, inp)):
                    if ev.startswith("event"):
                        nodes.append(ev)
        except OSError:
            continue
    return sorted(nodes)


def reload_udev(hwdb_changed):
    if hwdb_changed:
        run(["systemd-hwdb", "update"])
    run(["udevadm", "control", "--reload"])
    if hwdb_changed:
        # A plain trigger leaves the old keymap; it takes reload + change.
        for ev in event_nodes():
            run(["udevadm", "trigger", "--action=change", "--settle", "/sys/class/input/" + ev])


def apply_favorites_now():
    for name, phys in interfaces():
        if phys.endswith("/input1"):
            run([REBIND_SCRIPT, name])


def cmd_apply():
    try:
        req = json.loads(sys.stdin.read(128 * 1024))
    except ValueError:
        raise HelperError("bad request")
    hwdb = req.get("hwdb")
    favorites = bool(req.get("favorites_fix"))
    disable = [validate_disable(p) for p in req.get("disable", [])]
    if hwdb is not None:
        if not isinstance(hwdb, str):
            raise HelperError("bad hwdb")
        validate_hwdb(hwdb)

    for path in disable:
        os.rename(path, path + DISABLED_SUFFIX)
        emit(event="disabled", path=path)

    hwdb_changed = bool(disable)
    if hwdb is None:
        if os.path.exists(HWDB_FILE):
            remove_file(HWDB_FILE)
            hwdb_changed = True
    else:
        current = None
        if os.path.exists(HWDB_FILE):
            with open(HWDB_FILE) as f:
                current = f.read()
        if current != hwdb:
            write_file(HWDB_FILE, hwdb, 0o644)
            hwdb_changed = True

    if favorites:
        write_file(REBIND_SCRIPT, REBIND, 0o755)
        write_file(RULE_FILE, RULE, 0o644)
    else:
        remove_file(RULE_FILE)
        remove_file(REBIND_SCRIPT)

    reload_udev(hwdb_changed)
    if favorites:
        apply_favorites_now()
    emit(event="done", ok=True)


def cmd_reset():
    for path in (HWDB_FILE, RULE_FILE, REBIND_SCRIPT):
        remove_file(path)
    reload_udev(True)
    emit(event="done", ok=True)


EV_KEY, EV_MSC, MSC_SCAN = 0x01, 0x04, 0x04
EVENT_FMT = "llHHi"   # struct input_event on 64-bit
EVENT_SIZE = struct.calcsize(EVENT_FMT)


def cmd_capture(seconds):
    seconds = max(1.0, min(float(seconds), 60.0))
    fds = {}
    for ev in event_nodes():
        try:
            fds[os.open("/dev/input/" + ev, os.O_RDONLY | os.O_NONBLOCK)] = ev
        except OSError as e:
            emit(event="error", message="cannot open %s: %s" % (ev, e))
    if not fds:
        raise HelperError("keyboard not connected")
    emit(event="ready", nodes=sorted(fds.values()), seconds=seconds)
    watch = list(fds) + [sys.stdin.fileno()]
    deadline = time.time() + seconds
    pending_scan = {}
    while True:
        left = deadline - time.time()
        if left <= 0:
            break
        ready, _, _ = select.select(watch, [], [], left)
        if sys.stdin.fileno() in ready:
            if not os.read(sys.stdin.fileno(), 1024):
                break   # caller closed stdin: stop early
            continue
        for fd in ready:
            try:
                data = os.read(fd, EVENT_SIZE * 64)
            except BlockingIOError:
                continue
            for off in range(0, len(data) - EVENT_SIZE + 1, EVENT_SIZE):
                _, _, etype, code, value = struct.unpack_from(EVENT_FMT, data, off)
                if etype == EV_MSC and code == MSC_SCAN:
                    pending_scan[fd] = value & 0xFFFFFFFF
                elif etype == EV_KEY and value in (0, 1):
                    emit(event="key", node=fds[fd], code=code, pressed=bool(value),
                         scancode=pending_scan.pop(fd, None))
    emit(event="done", ok=True)


def main(argv):
    if os.geteuid() != 0:
        emit(event="done", ok=False, error="must run as root")
        return 1
    try:
        if argv[:1] == ["apply"]:
            cmd_apply()
        elif argv[:1] == ["reset"]:
            cmd_reset()
        elif argv[:1] == ["capture"] and len(argv) == 2:
            cmd_capture(argv[1])
        else:
            raise HelperError("usage: dmpkeys-helper apply|reset|capture SECONDS")
    except (HelperError, OSError) as e:
        emit(event="done", ok=False, error=str(e))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
