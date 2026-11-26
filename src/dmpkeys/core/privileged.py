"""Run the root helper (helper.py) through pkexec.

Native installs ship /usr/libexec/dmpkeys/dmpkeys-helper plus a polkit action
(io.github.newmca.DmpKeys.helper) for a clear authentication prompt. AppImage
and Flatpak builds have no file root can execute on the host (an AppImage's
FUSE mount is unreadable to root), so they pass the helper's source to the
host's python3 with -c instead; polkit then shows its generic "run python3 as
root" prompt.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from . import host

INSTALLED_HELPER = Path("/usr/libexec/dmpkeys/dmpkeys-helper")
HOST_PYTHON = "/usr/bin/python3"


class PrivilegedError(Exception):
    pass


@dataclass
class HelperResult:
    ok: bool
    error: str = ""
    events: list[dict] = field(default_factory=list)


def helper_argv(*args: str) -> list[str]:
    if host.packaging() == host.Packaging.NATIVE and INSTALLED_HELPER.exists():
        argv = ["pkexec", str(INSTALLED_HELPER), *args]
    else:
        source = resources.files("dmpkeys").joinpath("helper.py").read_text()
        argv = ["pkexec", HOST_PYTHON, "-I", "-c", source, *args]
    return host.host_argv(argv)


def parse_events(stdout: str) -> HelperResult:
    events = []
    for line in stdout.splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    done = next((e for e in reversed(events) if e.get("event") == "done"), None)
    if done is None:
        return HelperResult(False, "helper exited without a result (authentication cancelled?)", events)
    return HelperResult(bool(done.get("ok")), done.get("error", ""), events)


def call(*args: str, stdin: str = "", timeout: float = 120) -> HelperResult:
    try:
        proc = subprocess.run(helper_argv(*args), input=stdin, capture_output=True, text=True,
                              timeout=timeout, env=host.host_env())
    except FileNotFoundError as e:
        raise PrivilegedError(f"pkexec not available: {e}") from e
    except subprocess.TimeoutExpired as e:
        raise PrivilegedError("helper timed out") from e
    # pkexec: 126 = authorization dismissed/denied, 127 = not authorized
    if proc.returncode in (126, 127) and not proc.stdout.strip():
        return HelperResult(False, "Authentication was cancelled or denied.")
    result = parse_events(proc.stdout)
    if not result.ok and not result.error and proc.stderr.strip():
        result.error = proc.stderr.strip()[-500:]
    return result


def apply(hwdb_text: str | None, favorites_fix: bool, disable: list[str]) -> HelperResult:
    request = json.dumps({"hwdb": hwdb_text, "favorites_fix": favorites_fix, "disable": disable})
    return call("apply", stdin=request)


def reset() -> HelperResult:
    return call("reset")


def capture_argv(seconds: int) -> list[str]:
    """For streaming use (e.g. QProcess): keep stdin open, close it to stop early."""
    return helper_argv("capture", str(seconds))
