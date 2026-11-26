"""Backend import/apply flow with a fake KDE and a fake privileged helper."""
import pytest

from dmpkeys.core import backend as backend_mod, config, hwdb, kde, privileged
from dmpkeys.core.config import Action, Kind
from tests.test_desktop import FakeKde

LAUNCH5, LAUNCH6, FAVORITES, DOCUMENTS, CALC, GO = 16777383, 16777384, 16777361, 16777427, 16777419, 16777431


class FakeKdeWithOwners(FakeKde):
    def __init__(self, existing, defaults=None):
        super().__init__(existing)
        self.defaults = defaults or {}

    def available(self):
        return True

    def owners(self, qt):
        return [kde.Owner(did, "_launch", did.split(".")[-2], tuple(self.defaults.get(did, ())))
                for did, seqs in self.registry.items() if [qt, 0, 0, 0] in seqs]


@pytest.fixture
def system(monkeypatch, tmp_path):
    """No real /etc: legacy files come from tmp; privileged calls are recorded."""
    hwdb_dir = tmp_path / "hwdb.d"
    hwdb_dir.mkdir()
    calls = []
    monkeypatch.setattr(backend_mod.hwdb, "legacy_files", lambda: sorted(hwdb_dir.glob("*.hwdb")))
    monkeypatch.setattr(backend_mod.hwdb, "installed_text", lambda: None)
    monkeypatch.setattr(backend_mod.hwdb, "installed", lambda: None)
    monkeypatch.setattr(backend_mod.host, "host_path", lambda p: p)
    monkeypatch.setattr(backend_mod.device, "status", lambda: backend_mod.device.Status(
        connected=True, legacy_hwdb=sorted(hwdb_dir.glob("*.hwdb")),
        favorites_fix_installed=bool(calls) and calls[-1][1]))
    monkeypatch.setattr(privileged, "apply", lambda text, fav, disable: calls.append((text, fav, disable))
                        or privileged.HelperResult(True))
    monkeypatch.setattr(backend_mod.host, "which", lambda name: False)
    monkeypatch.setattr(backend_mod.apps, "lookup", lambda did: None)
    return hwdb_dir, calls


def make(fake):
    return backend_mod.Backend(kde=fake, desktop=backend_mod.DESKTOP_KDE)


def test_import_adopts_hand_made_setup_but_not_kde_defaults(system):
    hwdb_dir, _ = system
    (hwdb_dir / "61-hand.hwdb").write_text(
        "evdev:input:b0003v045Ep00B0*\n KEYBOARD_KEY_c022d=brightnessup\n KEYBOARD_KEY_c01b6=connect\n")
    fake = FakeKdeWithOwners({
        "org.kde.konsole.desktop": [[LAUNCH5, 0, 0, 0]],
        "net.local.open-pictures.desktop": [[GO, 0, 0, 0]],
        "org.kde.kcalc.desktop": [[CALC, 0, 0, 0]],
    }, defaults={"org.kde.kcalc.desktop": [CALC]})
    b = make(fake)
    assert b.first_run
    b.import_existing()
    assert b.action("slider_up") == Action(Kind.KEY, "brightnessup")
    assert b.action("fav1").kind == Kind.APP and b.action("fav1").target == "org.kde.konsole.desktop"
    assert b.action("my_pictures").kind == Kind.COMMAND          # launcher file not found in tmp
    assert b.action("calculator").kind == Kind.DEFAULT            # KDE default, left alone
    assert b.state.kde == {"org.kde.konsole.desktop": [LAUNCH5], "net.local.open-pictures.desktop": [GO]}
    assert config.load() is not None                              # saved


def test_apply_moves_adopted_bindings_to_managed_launchers(system):
    hwdb_dir, calls = system
    fake = FakeKdeWithOwners({"net.local.open-documents.desktop": [[DOCUMENTS, 0, 0, 0]]})
    b = make(fake)
    b.state.kde = {"net.local.open-documents.desktop": [DOCUMENTS]}   # as after import
    b.set_action("my_documents", Action(Kind.FOLDER, "/home/u/Documents"))
    report = b.apply()
    assert report.ok, report
    managed = "net.local.dmpkeys-my_documents.desktop"
    assert fake.registry[managed] == [[DOCUMENTS, 0, 0, 0]]
    assert fake.registry["net.local.open-documents.desktop"] == []
    assert b.state.kde == {managed: [DOCUMENTS]}
    assert b.state.kde_created == [managed]
    assert calls and calls[0][0] is None and calls[0][1] is True   # favorites fix, no remaps
    assert not b.has_pending_changes()


def test_apply_sends_rendered_hwdb_and_disables_legacy(system, owner_setup):
    hwdb_dir, calls = system
    legacy = hwdb_dir / "61-hand.hwdb"
    legacy.write_text("evdev:input:b0003v045Ep00B0*\n KEYBOARD_KEY_c01b6=connect\n KEYBOARD_KEY_c01b7=f19\n")
    b = make(FakeKdeWithOwners({}))
    b.config = owner_setup
    report = b.apply()
    assert report.ok, report
    text, fav, disable = calls[0]
    assert hwdb.parse(text) == {0x0C022D: "brightnessup", 0x0C022E: "brightnessdown",
                                0x0C01B6: "connect", 0x0C01B7: "f19"}     # carriers kept
    assert disable == [str(legacy)]
    assert b.state.kde["org.kde.konsole.desktop"] == [LAUNCH5]
    assert b.state.kde["systemsettings.desktop"] == [FAVORITES]


def test_failed_system_step_stops_before_desktop_changes(system, monkeypatch):
    monkeypatch.setattr(privileged, "apply", lambda *a: privileged.HelperResult(False, "Authentication was cancelled or denied."))
    fake = FakeKdeWithOwners({})
    b = make(fake)
    b.set_action("fav1", Action(Kind.APP, "a.desktop"))
    report = b.apply()
    assert not report.ok and "cancelled" in report.errors[0]
    assert fake.registry == {} and b.has_pending_changes()


def test_has_existing_setup_is_read_only(system):
    fake = FakeKdeWithOwners({"org.kde.konsole.desktop": [[LAUNCH5, 0, 0, 0]]})
    b = make(fake)
    assert b.has_existing_setup()
    assert b.state.kde == {} and not b.config.actions


def test_custom_keys_can_be_removed(system):
    b = make(FakeKdeWithOwners({}))
    key = b.add_custom_key(0x0C0224, "back", "Back")
    b.set_action(key.id, Action(Kind.URL, "https://e.org"))
    b.rename_custom_key(0x0C0224, "Browser back")
    assert b.key(key.id).label == "Browser back"
    b.remove_custom_key(0x0C0224)
    assert b.key(key.id) is None and key.id not in b.config.actions


def test_pending_keys(system):
    b = make(FakeKdeWithOwners({}))
    b.set_action("mail", Action(Kind.APP, "a.desktop"))
    assert b.pending_keys() == ["mail"]
    b.apply()
    assert b.pending_keys() == []
    b.set_action("mail", Action())
    assert b.pending_keys() == ["mail"]


def test_config_roundtrip(owner_setup):
    owner_setup.custom_keys.append(config.CustomKey(0x0C0224, "back", "Back"))
    again = config.Config.from_json(owner_setup.to_json())
    assert again.to_json() == owner_setup.to_json()
    assert again.key("scan_c0224").label == "Back"
