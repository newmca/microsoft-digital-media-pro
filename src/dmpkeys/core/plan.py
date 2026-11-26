"""Turn the desired config into concrete changes: hwdb remaps + desktop bindings.

A key bound to an action (app/folder/url/command) needs a keysym the desktop
can grab. If the key's native kernel key has one, and nothing else on the
desktop uses it, the binding goes on that keysym and nothing is remapped.
Otherwise the key's scancode is remapped (hwdb) to a spare kernel key whose
keysym is free, and the binding goes there. Keys without a scancode (the
favorites 1-5) can only use their native key.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from . import keycodes
from .config import Action, Config, Kind
from .keys import KeyDef

# Kernel keys with a clean level-1 keysym in xkeyboard-config's inet(evdev) and a
# Qt key, that this keyboard never sends natively. Order = allocation order.
# Not used: f13 (XF86Tools: GNOME opens Settings), f20-f22 (mic mute and
# touchpad toggles), f14-f18 (the favorites keys).
SPARE_KEYS = ("f19", "f23", "f24", "connect", "finance", "shop", "sport", "prog3", "prog4")

# Returns a description of who else uses this kernel key's keysym, or None if free.
OwnerLookup = Callable[[keycodes.KernelKey], "str | None"]


@dataclass(frozen=True)
class Binding:
    key: KeyDef
    action: Action
    carrier: keycodes.KernelKey   # the kernel key the desktop sees for this key
    remapped: bool                # carrier comes from an hwdb remap


@dataclass
class Plan:
    remaps: dict[int, str] = field(default_factory=dict)        # scancode -> kernel key
    remap_notes: dict[int, str] = field(default_factory=dict)
    bindings: list[Binding] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)        # key id -> message
    warnings: list[str] = field(default_factory=list)
    favorites_fix: bool = True

    @property
    def ok(self) -> bool:
        return not self.errors


def build(config: Config, owner_of: OwnerLookup | None = None, *, can_bind: bool = True,
          current: dict[int, str] | None = None) -> Plan:
    """current: scancode remaps in effect now; a key keeps its spare carrier when it can."""
    owner_of = owner_of or (lambda _k: None)
    current = current or {}
    plan = Plan(favorites_fix=config.favorites_fix)
    keys = config.all_keys()

    # Pass 1: explicit key remaps and disables; collect what they occupy.
    occupied: set[str] = set()
    key_targets: set[str] = set()   # kernel keys other keys are remapped to
    for key in keys:
        action = config.action(key.id)
        error = action.validate(key)
        if error:
            plan.errors[key.id] = error
            continue
        if action.kind in (Kind.KEY, Kind.DISABLE):
            scan = key.scancode
            assert scan is not None   # guaranteed by Action.validate
            target = action.target if action.kind == Kind.KEY else "reserved"
            plan.remaps[scan] = target
            plan.remap_notes[scan] = (f"{key.label}: sends {target}" if action.kind == Kind.KEY
                                      else f"{key.label}: disabled")
            if action.kind == Kind.KEY:
                occupied.add(target)
                key_targets.add(target)
        elif action.kind == Kind.DEFAULT:
            occupied.add(key.native)

    # Pass 2: desktop actions. Keys that already ride on a spare keep it.
    spares = [s for s in SPARE_KEYS if s not in occupied]
    reserved = {}
    for key in keys:
        held = current.get(key.scancode) if key.scancode is not None else None
        if held in spares and config.action(key.id).is_desktop_action and key.id not in plan.errors:
            reserved[key.id] = held
            spares.remove(held)
    for key in keys:
        action = config.action(key.id)
        if key.id in plan.errors or not action.is_desktop_action:
            continue
        if not can_bind:
            plan.errors[key.id] = "No supported desktop (KDE Plasma or GNOME) to bind actions on."
            continue
        if key.needs_hid_microsoft and not config.favorites_fix:
            plan.errors[key.id] = "Turn on the favorites fix: without it this key sends nothing."
            continue
        native = keycodes.lookup(key.native)
        if (native is not None and native.bindable and native.name not in key_targets
                and owner_of(native) is None):
            plan.bindings.append(Binding(key, action, native, remapped=False))
            if key.id in reserved:
                spares.append(reserved.pop(key.id))
            continue
        if not key.hwdb_remappable:
            who = owner_of(native) if native else None
            plan.errors[key.id] = (f"Its key ({native.keysym if native else key.native}) is already "
                                   f"used by {who}." if who else "This key can't be bound on this desktop.")
            continue
        carrier = None
        held = reserved.pop(key.id, None)
        if held is not None and owner_of(keycodes.require(held)) is None:
            carrier = keycodes.require(held)
        elif held is not None:
            spares.append(held)   # someone else grabbed its keysym; let it go
        while carrier is None and spares:
            candidate = keycodes.require(spares.pop(0))
            if owner_of(candidate) is None:
                carrier = candidate
                break
        if carrier is None:
            plan.errors[key.id] = "Ran out of spare key codes for actions."
            continue
        assert key.scancode is not None   # checked by hwdb_remappable above
        plan.remaps[key.scancode] = carrier.name
        plan.remap_notes[key.scancode] = f"{key.label}: carrier for {action.describe()} ({carrier.keysym})"
        plan.bindings.append(Binding(key, action, carrier, remapped=True))

    if any(k.needs_hid_microsoft for k in keys) and not config.favorites_fix:
        plan.warnings.append("Favorites 1-5 send nothing without the favorites fix.")
    return plan
