from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from dmpkeys.core import keys
from dmpkeys.core.config import Action, Kind
from dmpkeys.ui import layout
from dmpkeys.ui.icons import AppIcons
from dmpkeys.ui.keyboard_view import UNVERIFIED_TIP, KeyboardView, tooltip


def test_layout_places_every_catalog_key_without_overlap():
    diagram = layout.build(keys.KEYS)
    assert {s.key_id for s in diagram.spots} == {k.id for k in keys.KEYS}
    spots = diagram.spots
    for i, a in enumerate(spots):
        for b in spots[i + 1:]:
            assert not a.rect.intersects(b.rect), (a.key_id, b.key_id)


def test_layout_puts_custom_keys_in_a_strip_below():
    custom = keys.custom_key(0x0C0233, "presentation", "Presentation")
    diagram = layout.build([*keys.KEYS, custom])
    spot = diagram.spot(custom.id)
    assert spot is not None and spot.rect.top() >= layout.BODY_H
    assert any(d.text == "Detected keys" for d in diagram.decos)


def make_view(session) -> KeyboardView:
    view = KeyboardView(AppIcons())
    view.resize(900, 400)
    view.set_views(session.views())
    view.show()
    return view


def center(view: KeyboardView, key_id: str) -> QPoint:
    return view.spot_rect(key_id).center().toPoint()


def test_click_selects_key(session):
    view = make_view(session)
    seen = []
    view.keySelected.connect(seen.append)
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=center(view, "slider_down"))
    assert seen == ["slider_down"] and view.selected == "slider_down"
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=center(view, "fav3"))
    assert view.selected == "fav3"


def test_arrow_keys_move_between_neighbours(session):
    view = make_view(session)
    view.select("help")
    QTest.keyClick(view, Qt.Key.Key_Right)
    assert view.selected == "undo"
    QTest.keyClick(view, Qt.Key.Key_Left)
    assert view.selected == "help"
    QTest.keyClick(view, Qt.Key.Key_Up)
    assert keys.get(view.selected).group in (keys.Group.FAVORITES, keys.Group.LAUNCH)
    view.select("slider_up")
    QTest.keyClick(view, Qt.Key.Key_Down)
    assert view.selected == "slider_down"


def test_tooltip_marks_unconfirmed_keys(session):
    assert UNVERIFIED_TIP in tooltip(session.view("mute"))
    assert UNVERIFIED_TIP not in tooltip(session.view("slider_up"))
    session.confirm("mute")
    assert UNVERIFIED_TIP not in tooltip(session.view("mute"))


def test_paints_every_state_without_errors(session):
    session.set_action("mute", Action(Kind.DISABLE))
    session.set_action("fav1", Action(Kind.APP, "org.mozilla.firefox.desktop", "Firefox"))
    session.set_action("slider_up", Action(Kind.KEY, "brightnessup"))
    view = make_view(session)
    view.select("fav1")
    view.flash("mute")
    image = view.grab()
    assert not image.isNull()
