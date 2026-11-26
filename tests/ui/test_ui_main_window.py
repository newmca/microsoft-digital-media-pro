from dmpkeys.core.config import Action, Kind
from dmpkeys.ui import main_window as main_window_mod
from dmpkeys.ui.dialogs import ApplyDialog
from dmpkeys.ui.main_window import MainWindow

from .conftest import make_session
from .fakes import owner_setup


def test_apply_bar_counts_pending_changes(window, session):
    bar = window.apply_bar
    assert bar.text.text() == "Favorites fix not installed yet"
    rows = [window.changes.topLevelItem(i) for i in range(window.changes.topLevelItemCount())]
    assert [(r.text(0), r.text(2)) for r in rows] == [("Favorites fix", "Not applied")]
    assert window.changes_title.text() == "Changes (1)"
    session.set_action("mute", Action(Kind.DISABLE))
    assert bar.text.text() == "2 changes not applied"
    assert window.changes.topLevelItemCount() == 2
    assert bar.apply.isEnabled()
    session.set_action("mute", Action())
    assert bar.text.text() == "Favorites fix not installed yet"


def test_apply_flow_preview_then_result(window, session, backend):
    session.set_action("slider_up", Action(Kind.KEY, "brightnessup"))
    window.apply_changes()
    dialog: ApplyDialog = window.apply_dialog
    assert dialog.stack.currentWidget() is dialog.preview_page
    text = dialog.preview_text.text()
    assert "Zoom slider up" in text and "Brightness up" in text
    assert "admin password" in dialog.password.text()
    dialog.apply_button.click()
    assert backend.apply_calls == [True]
    assert dialog.stack.currentWidget() is dialog.result_page
    assert dialog.result_title.text() == "Your keys are ready"
    dialog.close_button.click()
    assert window.apply_bar.text.text() == "All changes applied"
    assert not window.apply_bar.apply.isEnabled()


def test_apply_failure_is_reported(window, session, backend):
    backend.apply_errors = ["System changes failed: Authentication was cancelled or denied."]
    window.apply_changes()
    window.apply_dialog.apply_button.click()
    assert window.apply_dialog.result_title.text() == "Some changes didn't work"
    assert "Authentication" in window.apply_dialog.result_text.text()
    assert window.apply_bar.text.text() == "Favorites fix not installed yet"


def test_legacy_banner_and_keep_checkbox(qapp, legacy_backend):
    session = make_session(legacy_backend)
    window = MainWindow(session)
    window.show()
    assert window.legacy_banner.isVisible()
    assert "61-ms-digital-media-pro.hwdb" in window.legacy_banner.text.text()
    window.keep_legacy.setChecked(True)
    window.apply_changes()
    window.apply_dialog.apply_button.click()
    assert legacy_backend.apply_calls == [False]
    window.close()


def test_first_run_offers_import(qapp, legacy_backend):
    session = make_session(legacy_backend)
    window = MainWindow(session)
    window.show()
    assert window.import_banner.isVisible()
    window.import_setup()
    assert not window.import_banner.isVisible()
    assert session.action("web_home").kind == Kind.APP
    assert not session.first_run
    window.close()


def test_selecting_from_changes_list_selects_key(qapp, backend):
    owner_setup(backend)
    window = MainWindow(make_session(backend))
    window.show()
    items = [window.changes.topLevelItem(i) for i in range(window.changes.topLevelItemCount())]
    calc = next(i for i in items if i.text(0) == "Calculator")
    assert calc.text(2) == "Not applied"
    assert next(i for i in items if i.text(0) == "Favorite 5").text(2) == "Problem"
    window.changes.setCurrentItem(calc)
    assert window.keyboard.selected == "calculator"
    assert window.editor.key_id == "calculator"
    window.close()


def test_favorites_fix_toggle(window, session, backend):
    window.header.fix.setChecked(False)
    assert backend.config.favorites_fix is False
    assert "send nothing" in window.header.fix_note.text()
    window.select_key("fav2")
    assert "Turn on" in window.editor.note_text.text()


def test_reset_after_confirmation(window, backend, monkeypatch):
    monkeypatch.setattr(main_window_mod, "confirm_reset", lambda _parent: False)
    window.reset_all()
    assert backend.reset_calls == 0
    monkeypatch.setattr(main_window_mod, "confirm_reset", lambda _parent: True)
    window.reset_all()
    assert backend.reset_calls == 1


def test_preview_warns_when_old_setup_was_not_imported(qapp, legacy_backend):
    session = make_session(legacy_backend)
    window = MainWindow(session)
    window.apply_changes()
    assert "been imported" in window.apply_dialog.preview_text.text()
    window.apply_dialog.reject()
    window.import_setup()
    window.apply_changes()
    assert "been imported" not in window.apply_dialog.preview_text.text()
    window.close()


def test_detected_key_can_be_renamed_and_removed(window, session, monkeypatch):
    from dmpkeys.ui import editor as editor_mod
    window.show()
    session.add_custom_key(0x0C0233, "presentation", "Key c0233")
    window.select_key("scan_c0233")
    editor = window.editor
    assert editor.custom_tools.isVisible()
    monkeypatch.setattr(editor_mod.QInputDialog, "getText",
                        staticmethod(lambda *a, **k: ("Presentation", True)))
    editor.rename_button.click()
    assert session.key("scan_c0233").label == "Presentation"
    assert editor.title.text() == "Presentation"
    monkeypatch.setattr(editor_mod.QMessageBox, "question",
                        staticmethod(lambda *a, **k: editor_mod.QMessageBox.StandardButton.Yes))
    editor.remove_button.click()
    assert session.key("scan_c0233") is None
    assert window.keyboard.spot_rect("scan_c0233") is None
    assert editor.placeholder.isVisible() and not editor.details.isVisible()


def test_custom_keys_have_no_rename_controls_for_catalog_keys(window):
    window.show()
    window.select_key("mute")
    assert not window.editor.custom_tools.isVisible()
