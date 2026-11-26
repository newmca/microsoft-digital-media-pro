"""The root helper is the security boundary: test its validation hard."""
import io
import json

import pytest

from dmpkeys import helper
from dmpkeys.core import hwdb


@pytest.fixture
def fake_root(tmp_path, monkeypatch):
    etc_hwdb, etc_rules, libexec = tmp_path / "hwdb.d", tmp_path / "rules.d", tmp_path / "libexec"
    for d in (etc_hwdb, etc_rules):
        d.mkdir()
    monkeypatch.setattr(helper, "HWDB_DIR", str(etc_hwdb))
    monkeypatch.setattr(helper, "HWDB_FILE", str(etc_hwdb / "70-dmpkeys.hwdb"))
    monkeypatch.setattr(helper, "RULES_DIR", str(etc_rules))
    monkeypatch.setattr(helper, "RULE_FILE", str(etc_rules / "70-dmpkeys-hid-microsoft.rules"))
    monkeypatch.setattr(helper, "REBIND_SCRIPT", str(libexec / "dmpkeys-hid-rebind"))
    monkeypatch.setattr(helper, "restore_context", lambda paths: None)
    ran = []
    monkeypatch.setattr(helper, "run", lambda cmd: ran.append(cmd) or True)
    monkeypatch.setattr(helper, "interfaces", lambda: [("0003:045E:00B0.0005", "usb-x/input0"),
                                                       ("0003:045E:00B0.0006", "usb-x/input1")])
    monkeypatch.setattr(helper, "event_nodes", lambda: ["event10", "event11"])
    return tmp_path, ran


def run_apply(monkeypatch, capsys, request: dict):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(request)))
    helper.cmd_apply()
    return [json.loads(line) for line in capsys.readouterr().out.splitlines()]


def test_rendered_hwdb_passes_validation():
    helper.validate_hwdb(hwdb.render({0x0C022D: "brightnessup", 0x010082: "reserved"}))


@pytest.mark.parametrize("bad", [
    "evdev:input:*\n KEYBOARD_KEY_c022d=brightnessup\n",                  # other devices
    hwdb.render({}) + "evdev:input:b0003v046Dp*\n",                         # second match line
    hwdb.render({}) + ' KEYBOARD_KEY_c022d=a\nRUN+="/bin/sh"\n',            # anything else
    hwdb.render({}) + " ID_INPUT_KEYBOARD=0\n",                             # other properties
    hwdb.render({}) + " KEYBOARD_KEY_c022d=Bad Name\n",
    "# only a comment\n",
])
def test_hwdb_validation_rejects(bad):
    with pytest.raises(helper.HelperError):
        helper.validate_hwdb(bad)


def test_disable_only_configs_for_this_keyboard(fake_root):
    root, _ = fake_root
    ours = root / "hwdb.d/61-hand.hwdb"
    ours.write_text("evdev:input:b0003v045Ep00B0*\n KEYBOARD_KEY_c022d=f23\n")
    other = root / "hwdb.d/61-logitech.hwdb"
    other.write_text("evdev:input:b0003v046Dp*\n KEYBOARD_KEY_1=a\n")
    rule = root / "rules.d/61-hand.rules"
    rule.write_text('ENV{HID_ID}=="0003:0000045E:000000B0", RUN+="x"\n')
    assert helper.validate_disable(str(ours)) == str(ours)
    assert helper.validate_disable(str(rule)) == str(rule)
    for path in (str(other), "/etc/passwd", str(root / "hwdb.d/missing.hwdb"), helper.HWDB_FILE):
        with pytest.raises(helper.HelperError):
            helper.validate_disable(path)


def test_apply_installs_files_and_reloads(fake_root, monkeypatch, capsys):
    root, ran = fake_root
    legacy = root / "hwdb.d/61-hand.hwdb"
    legacy.write_text("evdev:input:b0003v045Ep00B0*\n KEYBOARD_KEY_c022d=f23\n")
    text = hwdb.render({0x0C022D: "brightnessup"})
    events = run_apply(monkeypatch, capsys, {"hwdb": text, "favorites_fix": True, "disable": [str(legacy)]})
    assert events[-1] == {"event": "done", "ok": True}
    assert (root / "hwdb.d/70-dmpkeys.hwdb").read_text() == text
    assert not legacy.exists() and (root / "hwdb.d/61-hand.hwdb.disabled-by-dmpkeys").exists()
    rule = (root / "rules.d/70-dmpkeys-hid-microsoft.rules").read_text()
    assert 'ENV{HID_PHYS}=="*/input1"' in rule
    assert 'RUN+="/usr/local/libexec/dmpkeys-hid-rebind %k"' in rule
    assert (root / "libexec/dmpkeys-hid-rebind").stat().st_mode & 0o777 == 0o755
    assert ["systemd-hwdb", "update"] in ran
    assert ["udevadm", "trigger", "--action=change", "--settle", "/sys/class/input/event11"] in ran
    # Only interface 1 is rebound right away; typing (interface 0) is never touched.
    assert [helper.REBIND_SCRIPT, "0003:045E:00B0.0006"] in ran
    assert [helper.REBIND_SCRIPT, "0003:045E:00B0.0005"] not in ran


def test_apply_is_idempotent_and_can_remove(fake_root, monkeypatch, capsys):
    root, ran = fake_root
    text = hwdb.render({0x0C022D: "brightnessup"})
    run_apply(monkeypatch, capsys, {"hwdb": text, "favorites_fix": False, "disable": []})
    ran.clear()
    run_apply(monkeypatch, capsys, {"hwdb": text, "favorites_fix": False, "disable": []})
    assert ["systemd-hwdb", "update"] not in ran   # unchanged hwdb: no rebuild
    run_apply(monkeypatch, capsys, {"hwdb": None, "favorites_fix": False, "disable": []})
    assert not (root / "hwdb.d/70-dmpkeys.hwdb").exists()
    assert not (root / "rules.d/70-dmpkeys-hid-microsoft.rules").exists()


def test_apply_rejects_bad_request_before_touching_anything(fake_root, monkeypatch, capsys):
    root, ran = fake_root
    with pytest.raises(helper.HelperError):
        run_apply(monkeypatch, capsys, {"hwdb": "evdev:input:*\n", "favorites_fix": True, "disable": []})
    assert not any(root.rglob("70-dmpkeys*")) and not ran


def test_main_requires_root(monkeypatch, capsys):
    monkeypatch.setattr(helper.os, "geteuid", lambda: 1000)
    assert helper.main(["reset"]) == 1
    assert "root" in capsys.readouterr().out


def test_helper_source_runs_standalone():
    """AppImage/Flatpak pass the source to the host python with -c: no package imports allowed."""
    from importlib import resources
    source = resources.files("dmpkeys").joinpath("helper.py").read_text()
    assert "from dmpkeys" not in source and "import dmpkeys" not in source
    compile(source, "<helper>", "exec")
