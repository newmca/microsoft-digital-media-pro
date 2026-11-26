"""KDE merge semantics, launcher files and GNOME settings, with fakes."""
from pathlib import Path

import pytest

from dmpkeys.core import gnome, kde, launchers
from dmpkeys.core.config import Action, Kind

FIREFOX, LAUNCH5, CTRL_ALT_T = 16777360, 16777383, 201326676


class FakeKde(kde.KdeShortcuts):
    def __init__(self, existing: dict[str, list[list[int]]]):
        super().__init__(connection=object())
        self.registry = {k: [list(s) for s in v] for k, v in existing.items()}
        self.unregistered = []

    def keys(self, desktop_id):
        return [list(s) for s in self.registry.get(desktop_id, [])]

    def set_launch_keys(self, desktop_id, name, keep, ours):
        self.registry[desktop_id] = [list(s) for s in keep] + [[q, 0, 0, 0] for q in ours]
        return self.registry[desktop_id]

    def unregister(self, desktop_id):
        self.unregistered.append(desktop_id)
        self.registry.pop(desktop_id, None)


def test_kde_keeps_other_shortcuts_on_the_same_launcher():
    k = FakeKde({"org.kde.konsole.desktop": [[CTRL_ALT_T, 0, 0, 0]]})
    applied = k.apply({"org.kde.konsole.desktop": ("Konsole", [LAUNCH5])}, {}, set())
    assert applied == {"org.kde.konsole.desktop": [LAUNCH5]}
    assert k.registry["org.kde.konsole.desktop"] == [[CTRL_ALT_T, 0, 0, 0], [LAUNCH5, 0, 0, 0]]


def test_kde_moves_our_key_and_cleans_up():
    k = FakeKde({"a.desktop": [[LAUNCH5, 0, 0, 0]], launchers.desktop_id_for("x"): [[FIREFOX, 0, 0, 0]]})
    previous = {"a.desktop": [LAUNCH5], launchers.desktop_id_for("x"): [FIREFOX]}
    applied = k.apply({"b.desktop": ("B", [LAUNCH5])}, previous, {launchers.desktop_id_for("x")})
    assert applied == {"b.desktop": [LAUNCH5]}
    assert k.registry["a.desktop"] == []                       # third-party launcher: just unbound
    assert k.unregistered == [launchers.desktop_id_for("x")]   # ours: unregistered


def test_kde_reports_refused_keys():
    class Refusing(FakeKde):
        def set_launch_keys(self, desktop_id, name, keep, ours):
            return [list(s) for s in keep]          # kglobalaccel drops keys that are taken
    assert Refusing({}).apply({"a.desktop": ("A", [FIREFOX])}, {}, set()) == {}


@pytest.mark.parametrize("arg,quoted", [
    ("/home/u/Documents", "/home/u/Documents"),
    ("/home/u/My Pictures", '"/home/u/My Pictures"'),
    ('a"b$c`d\\e', '"a\\"b\\$c\\`d\\\\e"'),
    ("100%", "100%%"),
])
def test_exec_quote(arg, quoted):
    assert launchers.exec_quote(arg) == quoted


def test_launcher_file_and_removal():
    action = Action(Kind.FOLDER, "/home/u/My Pictures")
    did = launchers.write_launcher("my_pictures", "My Pictures", action)
    path = launchers.applications_dir() / did
    text = path.read_text()
    assert did == "net.local.dmpkeys-my_pictures.desktop"
    assert 'Exec=xdg-open "/home/u/My Pictures"' in text
    assert "NoDisplay=true" in text
    launchers.remove_launcher(did)
    assert not path.exists()


def test_remove_launcher_never_touches_foreign_files():
    d = launchers.applications_dir()
    d.mkdir(parents=True)
    for name in ("org.mozilla.firefox.desktop", "net.local.dmpkeys-hand.desktop"):
        (d / name).write_text("[Desktop Entry]\nExec=x\n")
        launchers.remove_launcher(name)
        assert (d / name).exists()


def test_shell_command_quotes_for_gnome():
    assert launchers.shell_command(Action(Kind.URL, "https://e.org/?a=1&b=2")) == "xdg-open 'https://e.org/?a=1&b=2'"
    assert launchers.shell_command(Action(Kind.COMMAND, "notify-send 'hi'")) == "sh -c 'notify-send '\"'\"'hi'\"'\"''"


def test_gvariant_and_strv_parsing():
    assert gnome.gvariant_str("it's") == "'it\\'s'"
    assert gnome._parse_strv("['XF86Mail', '<Super>e']") == ["XF86Mail", "<Super>e"]
    assert gnome._parse_strv("@as []") == []
    assert gnome._parse_strv("'XF86Mail'") == ["XF86Mail"]


def test_gnome_apply_keeps_foreign_bindings(monkeypatch):
    settings = {(gnome.MEDIA_KEYS, "custom-keybindings"): "['/org/x/custom0/']"}
    calls = []

    def fake(*args):
        calls.append(args)
        if args[0] == "get":
            return settings.get((args[1], args[2]), "''")
        if args[0] == "set":
            settings[(args[1], args[2])] = args[3]
        return ""
    monkeypatch.setattr(gnome, "_gsettings", fake)
    paths = gnome.GnomeShortcuts().apply({"mail": ("Mail: Launches X", "gio launch /x.desktop", "XF86Mail")},
                                         previous=[gnome.path_for("old")])
    assert paths == [gnome.path_for("mail")]
    assert settings[(gnome.MEDIA_KEYS, "custom-keybindings")] == \
        f"['/org/x/custom0/', '{gnome.path_for('mail')}']"
    assert ("reset", f"{gnome.CUSTOM_SCHEMA}:{gnome.path_for('old')}", "binding") in calls
    assert settings[(f"{gnome.CUSTOM_SCHEMA}:{gnome.path_for('mail')}", "binding")] == "'XF86Mail'"


def test_host_env_undoes_appimage_library_path(monkeypatch):
    from dmpkeys.core import host
    monkeypatch.setenv("APPIMAGE", "/x/App.AppImage")
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/.mount_x/usr/lib")
    monkeypatch.setenv("DMPKEYS_ORIG_LD_LIBRARY_PATH", "__unset__")
    assert "LD_LIBRARY_PATH" not in host.host_env()
    monkeypatch.setenv("DMPKEYS_ORIG_LD_LIBRARY_PATH", "/opt/lib")
    assert host.host_env()["LD_LIBRARY_PATH"] == "/opt/lib"
    monkeypatch.delenv("APPIMAGE")
    assert host.host_env()["LD_LIBRARY_PATH"] == "/tmp/.mount_x/usr/lib"   # native: untouched
