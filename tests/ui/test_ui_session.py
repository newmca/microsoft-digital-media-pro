import threading

from dmpkeys.core.config import Action, Kind
from dmpkeys.ui import keynames, presets
from dmpkeys.ui.session import Effect, build_preview
from dmpkeys.ui.text import describe
from dmpkeys.ui.worker import BackendWorker

from .conftest import make_session, wait_until
from .fakes import owner_setup


def test_fresh_setup_counts_the_favorites_fix_as_pending(session):
    assert session.favorites_fix and session.favorites_fix_pending
    assert session.pending_count == 1
    assert "Installs" in session.favorites_fix_change


def test_offers_import_only_for_an_existing_setup(qapp, backend, legacy_backend):
    assert not make_session(backend).offer_import
    assert make_session(legacy_backend).offer_import


def test_set_action_updates_view_and_pending_count(session, backend):
    session.set_action("mute", Action(Kind.KEY, "micmute"))
    view = session.view("mute")
    assert view.effect == Effect.KEY and view.pending
    assert backend.action("mute") == Action(Kind.KEY, "micmute")   # saved through the backend
    assert session.pending_count == 2


def test_revert_goes_back_to_what_was_applied(qapp, backend):
    owner_setup(backend)
    session = make_session(backend)
    assert session.view("calculator").pending
    session.revert("calculator")
    assert session.action("calculator") == Action()
    assert not session.view("calculator").pending


def test_plan_errors_reach_the_key_view(qapp, backend):
    owner_setup(backend)
    session = make_session(backend)
    assert "Spectacle" in session.view("fav5").error
    assert session.view("fav1").error is None
    assert session.view("fav1").binding.carrier.name == "f14"


def test_slider_preset_sets_both_halves(session):
    volume = next(p for p in presets.PRESETS if p.id == "volume")
    session.set_actions(volume.actions())
    assert presets.matching(session.action("slider_up"), session.action("slider_down")) == volume
    assert presets.matching(Action(Kind.KEY, "volumeup"), Action()) is None


def test_apply_preview_lists_remaps_shortcuts_files_and_password(qapp, legacy_backend):
    owner_setup(legacy_backend)
    preview = build_preview(legacy_backend, disable_legacy=True)
    assert ("Zoom slider up", "Sends Brightness up") in preview.key_changes
    assert ("Web/Home", "Opens Firefox") in preview.shortcuts
    assert any(label == "Favorite 5" for label, _ in preview.problems)
    assert preview.disable_files == [str(p) for p in
                                     legacy_backend.status().legacy_hwdb
                                     + legacy_backend.status().legacy_rules]
    assert preview.needs_password
    assert build_preview(legacy_backend, disable_legacy=False).disable_files == []


def test_apply_clears_pending_and_honours_keep_legacy(qapp, legacy_backend):
    session = make_session(legacy_backend)
    session.set_action("mute", Action(Kind.DISABLE))
    session.keep_legacy = True
    reports = []
    session.apply(reports.append, lambda e: reports.append(e))
    assert reports[0].ok
    assert legacy_backend.apply_calls == [False]
    assert session.pending_count == 0


def test_confirm_marks_unverified_key_confirmed(session):
    assert not session.view("mute").confirmed
    session.confirm("mute")
    assert session.view("mute").confirmed


def test_threaded_worker_runs_jobs_in_order_off_the_gui_thread(qapp):
    worker = BackendWorker()
    results, threads = [], []
    for i in range(5):
        worker.submit(lambda i=i: (threads.append(threading.get_ident()), i)[1], results.append)
    assert wait_until(lambda: len(results) == 5)
    assert results == [0, 1, 2, 3, 4]
    assert threading.get_ident() not in threads
    errors = []
    worker.submit(lambda: 1 / 0, None, errors.append)
    assert wait_until(lambda: errors)
    assert isinstance(errors[0], ZeroDivisionError)
    assert worker.shutdown()


def test_keynames_categories_use_real_kernel_names():
    cats = keynames.categories()
    for name, members in keynames.CATEGORIES.items():
        assert set(cats[name]) == set(members), name   # nothing silently dropped
    assert keynames.human_name("brightnessup") == "Brightness up"
    assert keynames.human_name("f19") == "F19"
    assert keynames.category_of("nextsong") == "Media"
    assert describe(Action(Kind.KEY, "brightnessup")) == "Sends Brightness up"
