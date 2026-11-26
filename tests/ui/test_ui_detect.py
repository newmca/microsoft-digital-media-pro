import json

from dmpkeys.core import keys
from dmpkeys.ui.detect import DetectDialog, LineParser, identify

from .conftest import wait_until


def key_event(code, scancode, pressed=True):
    return {"event": "key", "node": "event11", "code": code, "pressed": pressed,
            "scancode": scancode}


def test_line_parser_handles_split_lines_and_junk():
    parser = LineParser()
    assert parser.feed(b'{"event":"ready","nodes":["event11"]}\n{"event":"ke') == [
        {"event": "ready", "nodes": ["event11"]}]
    assert parser.feed(b'y","code":113}\nnot json\n[1]\n') == [{"event": "key", "code": 113}]
    assert parser.feed(b"") == []


def test_identify_matches_scancodes_favorites_and_unknown_keys():
    catalog = list(keys.KEYS)
    assert identify(key_event(113, 0x0C00E2), catalog).key.id == "mute"
    assert identify(key_event(186, None), catalog).key.id == "fav3"      # F16, no scancode
    unknown = identify(key_event(425, 0x0C0233), catalog)
    assert unknown.key is None and unknown.native == "presentation"
    assert identify(key_event(30, 0x070004), catalog) is None             # a typing key
    assert identify(key_event(113, 0x0C00E2, pressed=False), catalog) is None
    assert identify({"event": "ready"}, catalog) is None


def test_handled_events_confirm_keys_and_offer_unknown_ones(session):
    dialog = DetectDialog(session)
    seen, added = [], []
    dialog.keySeen.connect(seen.append)
    dialog.keyAdded.connect(added.append)
    dialog.handle_event({"event": "ready", "nodes": ["event11"], "seconds": 15})
    assert "15 s left" in dialog.status.text()
    dialog.handle_event(key_event(113, 0x0C00E2))
    dialog.handle_event(key_event(113, 0x0C00E2))         # repeated press: one row
    assert seen == ["mute", "mute"]
    assert session.view("mute").confirmed
    assert dialog.list.count() == 1 and "confirmed" in dialog.list.item(0).text()
    dialog.handle_event(key_event(425, 0x0C0233))
    assert dialog.list.count() == 2
    press = identify(key_event(425, 0x0C0233), session.keys())
    dialog.add_custom(press, "Presentation")
    assert added == ["scan_c0233"]
    assert session.key("scan_c0233").label == "Presentation"
    assert session.key("scan_c0233").native == "presentation"


def run_capture(session, backend, lines, *, waits=False, stop=False):
    backend.capture_lines = [json.dumps(line) for line in lines]
    backend.capture_waits = waits
    dialog = DetectDialog(session)
    dialog.start()
    assert dialog.running
    if stop:
        assert wait_until(lambda: "left" in dialog.status.text())
        dialog.stop()
    assert wait_until(lambda: not dialog.running, 10000)
    return dialog


def test_capture_process_end_to_end(session, backend):
    dialog = run_capture(session, backend, [
        {"event": "ready", "nodes": ["event10", "event11"], "seconds": 15},
        key_event(186, None),
        key_event(186, None, pressed=False),
        {"event": "done", "ok": True},
    ])
    assert dialog.status.text() == "Finished listening."
    assert "Favorite 3" in dialog.list.item(0).text()


def test_capture_stops_when_stdin_closes(session, backend):
    dialog = run_capture(session, backend, [
        {"event": "ready", "nodes": ["event11"], "seconds": 15},
    ], waits=True, stop=True)
    # The fake helper exits without a "done" line once its stdin closes.
    assert "stopped unexpectedly" in dialog.status.text()


def test_capture_reports_helper_errors(session, backend):
    dialog = run_capture(session, backend, [
        {"event": "done", "ok": False, "error": "keyboard not connected"},
    ])
    assert "keyboard not connected" in dialog.status.text()
