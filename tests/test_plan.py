from dmpkeys.core import plan
from dmpkeys.core.config import Action, Config, Kind


def carriers(p):
    return {b.key.id: (b.carrier.name, b.remapped) for b in p.bindings}


def test_owner_setup_without_history_allocates_spares_in_order(owner_setup):
    p = plan.build(owner_setup)
    assert p.ok, p.errors
    c = carriers(p)
    # Keys whose native key has a keysym bind it directly.
    assert c["fav1"] == ("f14", False)
    assert c["my_documents"] == ("documents", False)
    assert c["mail"] == ("mail", False)
    # My Pictures/My Music send codes > 247: remapped to spares, in catalog order.
    assert c["my_pictures"] == ("f19", True)
    assert c["my_music"] == ("f23", True)
    assert p.remaps == {0x0C022D: "brightnessup", 0x0C022E: "brightnessdown",
                        0x0C01B6: "f19", 0x0C01B7: "f23"}


def test_current_carriers_are_kept(owner_setup):
    # What the hand-made setup used: Pictures -> connect, Music -> f19.
    p = plan.build(owner_setup, current={0x0C01B6: "connect", 0x0C01B7: "f19"})
    c = carriers(p)
    assert c["my_pictures"] == ("connect", True)
    assert c["my_music"] == ("f19", True)


def test_taken_native_key_moves_to_a_spare():
    c = Config()
    c.set_action("mail", Action(Kind.APP, "a.desktop"))
    p = plan.build(c, owner_of=lambda k: "Evolution" if k.name == "mail" else None)
    assert carriers(p)["mail"] == ("f19", True)
    assert p.remaps == {0x0C018A: "f19"}


def test_taken_spare_is_skipped():
    c = Config()
    c.set_action("my_music", Action(Kind.APP, "a.desktop"))
    p = plan.build(c, owner_of=lambda k: "someone" if k.name == "f19" else None)
    assert carriers(p)["my_music"] == ("f23", True)


def test_spare_used_as_a_key_target_is_not_reused():
    c = Config()
    c.set_action("slider_up", Action(Kind.KEY, "f19"))
    c.set_action("my_music", Action(Kind.APP, "a.desktop"))
    assert carriers(plan.build(c))["my_music"] == ("f23", True)


def test_native_keysym_that_another_key_is_remapped_to_is_avoided():
    c = Config()
    c.set_action("slider_up", Action(Kind.KEY, "mail"))
    c.set_action("mail", Action(Kind.APP, "a.desktop"))
    assert carriers(plan.build(c))["mail"] == ("f19", True)


def test_favorites_need_the_fix_and_cannot_be_remapped():
    c = Config(favorites_fix=False)
    c.set_action("fav1", Action(Kind.APP, "a.desktop"))
    c.set_action("fav2", Action(Kind.KEY, "volumeup"))
    p = plan.build(c)
    assert "fix" in p.errors["fav1"]
    assert "scancode" in p.errors["fav2"]
    assert p.warnings


def test_taken_favorite_reports_owner():
    c = Config()
    c.set_action("fav1", Action(Kind.APP, "a.desktop"))
    p = plan.build(c, owner_of=lambda k: "Some App" if k.name == "f14" else None)
    assert "Some App" in p.errors["fav1"]


def test_disable_and_no_desktop():
    c = Config()
    c.set_action("log_off", Action(Kind.DISABLE))
    c.set_action("mail", Action(Kind.URL, "https://example.org"))
    p = plan.build(c, can_bind=False)
    assert p.remaps == {0x0C019C: "reserved"}
    assert "desktop" in p.errors["mail"]


def test_runs_out_of_spares():
    c = Config()
    remappable_without_keysym = ["slider_up", "slider_down", "my_pictures", "my_music", "spell", "log_off"]
    for k in remappable_without_keysym:
        c.set_action(k, Action(Kind.COMMAND, "true"))
    p = plan.build(c, owner_of=lambda k: "x" if k.name in plan.SPARE_KEYS[:5] else None)
    assert len(p.bindings) == 4
    assert sum("spare" in e for e in p.errors.values()) == 2
