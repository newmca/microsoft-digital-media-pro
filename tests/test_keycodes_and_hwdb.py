import pytest

from dmpkeys.core import hwdb, keycodes, keys


@pytest.mark.parametrize("name,keysym,qt", [
    # Measured on the real setup: these are the Qt keys KDE matched.
    ("bookmarks", "XF86Favorites", 16777361),
    ("f14", "XF86Launch5", 16777383),       # favorites key 1 reaches Qt as Launch5, not F14
    ("f18", "XF86Launch9", 16777387),
    ("documents", "XF86Documents", 16777427),
    ("connect", "XF86Go", 16777431),
    ("f19", "F19", 16777282),
    ("mail", "XF86Mail", 16777376),
    ("homepage", "XF86HomePage", 16777360),
    ("chat", "XF86Messenger", 16777465),
    ("config", "XF86Tools", 16777457),
])
def test_known_keys_map_to_measured_qt_codes(name, keysym, qt):
    key = keycodes.require(name)
    assert (key.keysym, key.qt) == (keysym, qt)
    assert key.bindable


@pytest.mark.parametrize("name", ["zoomin", "zoomout", "images", "audio", "spellcheck", "logoff"])
def test_codes_above_247_have_no_keysym(name):
    key = keycodes.require(name)
    assert key.code + 8 > 255
    assert not key.bindable


def test_valid_targets():
    assert keycodes.is_valid_target("brightnessup")
    assert keycodes.is_valid_target("reserved")
    assert not keycodes.is_valid_target("Brightnessup")
    assert not keycodes.is_valid_target("nope")
    assert not keycodes.is_valid_target("f19\nRUN+=x")


def test_catalog_scancodes_unique_and_natives_exist():
    scans = [k.scancode for k in keys.KEYS if k.scancode is not None]
    assert len(scans) == len(set(scans))
    for k in keys.KEYS:
        assert keycodes.lookup(k.native) is not None, k.id


def test_render_parse_roundtrip():
    remaps = {0x0C022D: "brightnessup", 0x0C01B6: "connect"}
    text = hwdb.render(remaps, {0x0C022D: "slider up"})
    assert keys.HWDB_MATCH in text
    assert " KEYBOARD_KEY_c022d=brightnessup" in text.splitlines()
    assert hwdb.parse(text) == remaps


def test_render_rejects_bad_target():
    with pytest.raises(ValueError):
        hwdb.render({0x0C022D: "brightness up"})


LEGACY = """\
# hand made
evdev:input:b0003v045Ep00B0*
 KEYBOARD_KEY_c022d=brightnessup
 KEYBOARD_KEY_c01b6=connect

evdev:input:b0003v046Dp0000*
 KEYBOARD_KEY_c022d=volumeup
"""


def test_parse_only_takes_this_keyboards_block():
    assert hwdb.parse(LEGACY) == {0x0C022D: "brightnessup", 0x0C01B6: "connect"}
    assert hwdb.mentions_device(LEGACY)
    assert not hwdb.mentions_device("evdev:input:b0003v046Dp0000*\n KEYBOARD_KEY_1=a\n")


def test_legacy_files_skips_ours(tmp_path):
    (tmp_path / "61-hand.hwdb").write_text(LEGACY)
    (tmp_path / "62-other.hwdb").write_text("evdev:input:b0003v046Dp0000*\n KEYBOARD_KEY_1=a\n")
    assert hwdb.legacy_files(tmp_path) == [tmp_path / "61-hand.hwdb"]
