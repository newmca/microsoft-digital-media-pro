from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from dmpkeys.core.config import Action, Kind
from dmpkeys.ui import keynames
from dmpkeys.ui.editor import EditorPanel, normalize_url
from dmpkeys.ui.icons import AppIcons


def make_editor(session, key_id: str) -> EditorPanel:
    editor = EditorPanel(session, AppIcons())
    editor.resize(420, 900)
    editor.show()
    editor.show_key(key_id)
    return editor


def test_favorites_cannot_send_keys_or_be_disabled(session):
    editor = make_editor(session, "fav1")
    assert not editor.radios[Kind.KEY].isEnabled()
    assert not editor.radios[Kind.DISABLE].isEnabled()
    assert editor.radios[Kind.APP].isEnabled()
    assert editor.restriction.isVisible() and "Favorites 1–5" in editor.restriction.text()
    assert "hid-microsoft" in editor.note_text.text()


def test_send_another_key_through_the_picker(session):
    editor = make_editor(session, "mute")
    editor.radios[Kind.KEY].setChecked(True)
    assert session.action("mute") == Action()          # nothing saved until a key is picked
    assert editor.hint.isVisible()
    editor.key_picker.picked.emit("micmute")
    assert session.action("mute") == Action(Kind.KEY, "micmute")
    assert session.view("mute").pending
    assert "Mute microphone" in editor.effect.text()


def test_key_picker_search_looks_through_all_keys(qapp):
    from dmpkeys.ui.pickers import KeyPicker
    picker = KeyPicker()
    picker.category.setCurrentText("Brightness")
    assert "brightnessup" in picker.visible_values() and "volumeup" not in picker.visible_values()
    picker.search.setText("volume up")
    assert picker.category.currentText() == keynames.ALL_KEYS
    assert picker.visible_values() == ["volumeup"]
    picker.search.setText("kbdillum")      # kernel names match too
    assert "kbdillumup" in picker.visible_values()


def test_default_and_disable_save_immediately(session):
    session.set_action("stop", Action(Kind.KEY, "stopcd"))
    editor = make_editor(session, "stop")
    editor.radios[Kind.DISABLE].setChecked(True)
    assert session.action("stop") == Action(Kind.DISABLE)
    editor.radios[Kind.DEFAULT].setChecked(True)
    assert session.action("stop") == Action()


def test_app_picker_lists_apps_and_saves_the_name(session):
    editor = make_editor(session, "mail")
    editor.radios[Kind.APP].setChecked(True)
    assert "net.thunderbird.Thunderbird.desktop" in editor.app_picker.visible_values()
    editor.app_picker.search.setText("thunder")
    assert editor.app_picker.visible_values() == ["net.thunderbird.Thunderbird.desktop"]
    QTest.keyClick(editor.app_picker.search, Qt.Key.Key_Return)
    assert session.action("mail") == Action(Kind.APP, "net.thunderbird.Thunderbird.desktop",
                                            "Thunderbird")


def test_folder_must_exist(session, tmp_path):
    editor = make_editor(session, "my_documents")
    editor.radios[Kind.FOLDER].setChecked(True)
    editor.folder.setText(str(tmp_path / "missing"))
    editor.folder.editingFinished.emit()
    assert editor.error.isVisible() and "no folder" in editor.error.text()
    assert session.action("my_documents") == Action()
    (tmp_path / "Docs").mkdir()
    editor.folder.setText(str(tmp_path / "Docs"))
    editor.folder.editingFinished.emit()
    assert session.action("my_documents") == Action(Kind.FOLDER, str(tmp_path / "Docs"), "Docs")
    assert not editor.error.isVisible()


def test_url_gets_a_scheme_and_command_keeps_its_name(session):
    assert normalize_url(" example.com ") == "https://example.com"
    assert normalize_url("mailto:me@example.com") == "mailto:me@example.com"
    editor = make_editor(session, "web_home")
    editor.radios[Kind.URL].setChecked(True)
    editor.url.setText("kde.org")
    editor.url.editingFinished.emit()
    assert session.action("web_home") == Action(Kind.URL, "https://kde.org")
    editor.show_key("calculator")
    editor.radios[Kind.COMMAND].setChecked(True)
    editor.command_name.setText("Calculator")
    editor.command.setText("kcalc")
    editor.command.editingFinished.emit()
    assert session.action("calculator") == Action(Kind.COMMAND, "kcalc", "Calculator")


def test_slider_presets_set_both_halves_and_show_which_is_active(session):
    editor = make_editor(session, "slider_up")
    assert editor.presets.isVisible()
    assert editor.preset_buttons["zoom"].isChecked()
    editor.preset_buttons["brightness"].click()
    assert session.action("slider_up") == Action(Kind.KEY, "brightnessup")
    assert session.action("slider_down") == Action(Kind.KEY, "brightnessdown")
    assert editor.preset_buttons["brightness"].isChecked()
    # One half changed on its own: no preset matches any more.
    editor.key_picker.picked.emit("volumeup")
    assert not any(b.isChecked() for b in editor.preset_buttons.values())
    assert editor.preset_hint.text().startswith("Custom")
    editor.show_key("mute")
    assert not editor.presets.isVisible()


def test_problem_and_undo_are_shown(qapp, backend):
    from .conftest import make_session
    from .fakes import owner_setup
    owner_setup(backend)
    session = make_session(backend)
    editor = make_editor(session, "fav5")
    assert editor.current.tone == "error" and "Spectacle" in editor.state.text()
    editor.show_key("calculator")
    assert editor.current.tone == "pending"
    editor.state.linkActivated.emit("undo")
    assert session.action("calculator") == Action()
    assert editor.current.tone == "neutral"
