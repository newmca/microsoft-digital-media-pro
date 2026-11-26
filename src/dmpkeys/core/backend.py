"""The one object the UI (and CLI) talks to."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import apps, config as config_mod, device, hwdb, host, keycodes, launchers, plan as plan_mod, privileged
from . import state as state_mod
from .config import Action, Config, Kind
from .gnome import GnomeShortcuts
from .kde import KdeShortcuts
from .keys import KeyDef

DESKTOP_KDE = "kde"
DESKTOP_GNOME = "gnome"
DESKTOP_NAMES = {DESKTOP_KDE: "KDE Plasma", DESKTOP_GNOME: "GNOME", None: "Unsupported desktop"}


class _Detect:
    """Sentinel: detect the desktop (the default). Pass None to mean 'no desktop'."""


DETECT = _Detect()


@dataclass
class SystemChange:
    hwdb_text: str | None       # None = remove our hwdb file
    favorites_fix: bool
    disable: list[str]
    needed: bool


@dataclass
class ApplyReport:
    ok: bool
    messages: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    key_errors: dict[str, str] = field(default_factory=dict)


class Backend:
    def __init__(self, *, config_path: Path | None = None, state_path: Path | None = None,
                 kde: KdeShortcuts | None = None, gnome: GnomeShortcuts | None = None,
                 desktop: str | None | _Detect = DETECT):
        self._config_path = config_path
        self._state_path = state_path
        loaded = config_mod.load(config_path)
        self.first_run = loaded is None
        self.config: Config = loaded or Config()
        self.state = state_mod.load(state_path)
        self._kde = kde
        self._gnome = gnome
        self.desktop: str | None = (self._detect_desktop() if isinstance(desktop, _Detect)
                                    else desktop)

    # --- environment ---------------------------------------------------------------
    @property
    def kde(self) -> KdeShortcuts:
        if self._kde is None:
            self._kde = KdeShortcuts()
        return self._kde

    @property
    def gnome(self) -> GnomeShortcuts:
        if self._gnome is None:
            self._gnome = GnomeShortcuts()
        return self._gnome

    def _detect_desktop(self) -> str | None:
        desktops = host.current_desktop()
        if "KDE" in desktops and self.kde.available():
            return DESKTOP_KDE
        if "GNOME" in desktops and self.gnome.available():
            return DESKTOP_GNOME
        return None

    @property
    def desktop_name(self) -> str:
        return DESKTOP_NAMES[self.desktop]

    def status(self) -> device.Status:
        return device.status()

    def apps(self) -> list[apps.App]:
        return apps.installed()

    def packaging(self) -> host.Packaging:
        return host.packaging()

    # --- config --------------------------------------------------------------------
    def keys(self) -> list[KeyDef]:
        return self.config.all_keys()

    def key(self, key_id: str) -> KeyDef | None:
        return self.config.key(key_id)

    def action(self, key_id: str) -> Action:
        return self.config.action(key_id)

    def set_action(self, key_id: str, action: Action) -> None:
        self.config.set_action(key_id, action)
        self.save_config()

    def set_favorites_fix(self, enabled: bool) -> None:
        self.config.favorites_fix = enabled
        self.save_config()

    def add_custom_key(self, scancode: int, native: str, label: str) -> KeyDef:
        existing = next((c for c in self.config.custom_keys if c.scancode == scancode), None)
        if existing is None:
            existing = config_mod.CustomKey(scancode, native, label)
            self.config.custom_keys.append(existing)
            self.save_config()
        return existing.keydef()

    def remove_custom_key(self, scancode: int) -> None:
        self.config.custom_keys = [c for c in self.config.custom_keys if c.scancode != scancode]
        self.config.actions.pop(f"scan_{scancode:x}", None)
        self.save_config()

    def rename_custom_key(self, scancode: int, label: str) -> None:
        for c in self.config.custom_keys:
            if c.scancode == scancode:
                c.label = label
        self.save_config()

    def save_config(self) -> None:
        config_mod.save(self.config, self._config_path)

    def _applied(self) -> Config | None:
        return Config.from_json(self.state.applied_config) if self.state.applied_config else None

    def applied_action(self, key_id: str) -> Action:
        """What the key did at the last successful Apply (Default if never applied)."""
        applied = self._applied()
        return applied.action(key_id) if applied else Action()

    def pending_keys(self) -> list[str]:
        """Key ids whose action differs from what was last applied."""
        return [k.id for k in self.keys() if self.applied_action(k.id) != self.config.action(k.id)]

    def favorites_fix_pending(self) -> bool:
        """The favorites-fix setting differs from what is installed."""
        applied = self._applied()
        if applied is not None and applied.favorites_fix != self.config.favorites_fix:
            return True
        return self.status().favorites_fix_installed != self.config.favorites_fix

    def has_pending_changes(self) -> bool:
        return bool(self.pending_keys()) or self.favorites_fix_pending()

    # --- planning ------------------------------------------------------------------
    def owner_of(self, kk: keycodes.KernelKey) -> str | None:
        """Who else (not us) uses this kernel key's keysym on the desktop."""
        if self.desktop == DESKTOP_KDE and kk.qt is not None:
            for o in self.kde.owners(kk.qt):
                ours = (o.component.startswith(launchers.PREFIX)
                        or kk.qt in self.state.kde.get(o.component, []))
                if not ours:
                    return o.describe()
        elif self.desktop == DESKTOP_GNOME and kk.keysym:
            found = self.gnome.owners(kk.keysym)
            return found[0] if found else None
        return None

    def current_remaps(self) -> dict[int, str]:
        """Scancode remaps in effect now (ours over hand-made ones), to keep carriers stable."""
        remaps: dict[int, str] = {}
        for path in hwdb.legacy_files():
            remaps.update(hwdb.parse(host.host_path(path).read_text()))
        remaps.update(hwdb.installed() or {})
        return remaps

    def plan(self) -> plan_mod.Plan:
        return plan_mod.build(self.config, self.owner_of, can_bind=self.desktop is not None,
                              current=self.current_remaps())

    def system_change(self, plan: plan_mod.Plan, disable_legacy: bool = True) -> SystemChange:
        text = hwdb.render(plan.remaps, plan.remap_notes) if plan.remaps else None
        status = self.status()
        disable = [str(p) for p in status.legacy_hwdb + status.legacy_rules] if disable_legacy else []
        current = hwdb.installed_text()
        needed = (current != text or status.favorites_fix_installed != plan.favorites_fix
                  or bool(disable))
        return SystemChange(text, plan.favorites_fix, disable, needed)

    # --- applying ------------------------------------------------------------------
    def apply(self, disable_legacy: bool = True) -> ApplyReport:
        plan = self.plan()
        report = ApplyReport(ok=True, key_errors=dict(plan.errors))
        change = self.system_change(plan, disable_legacy)
        if change.needed:
            result = privileged.apply(change.hwdb_text, change.favorites_fix, change.disable)
            if not result.ok:
                report.ok = False
                report.errors.append(f"System changes failed: {result.error}")
                return report
            report.messages.append("Updated system key mapping.")
            for e in result.events:
                if e.get("event") == "disabled":
                    report.messages.append(f"Disabled old config {e['path']}.")
        try:
            if self.desktop == DESKTOP_KDE:
                self._apply_kde(plan, report)
            elif self.desktop == DESKTOP_GNOME:
                self._apply_gnome(plan, report)
        except Exception as e:  # D-Bus/gsettings failures: report, keep state consistent
            report.ok = False
            report.errors.append(f"Desktop shortcuts failed: {e}")
            state_mod.save(self.state, self._state_path)
            return report
        self.state.applied_config = self.config.to_json()
        state_mod.save(self.state, self._state_path)
        report.ok = report.ok and not report.key_errors
        return report

    def _apply_kde(self, plan: plan_mod.Plan, report: ApplyReport) -> None:
        wanted: dict[str, tuple[str, list[int]]] = {}
        created: set[str] = set()
        for b in plan.bindings:
            if b.action.kind == Kind.APP:
                did = b.action.target
                app = apps.lookup(did)
                name = app.name if app else (b.action.label or did)
            else:
                did = launchers.write_launcher(b.key.id, b.key.label, b.action)
                created.add(did)
                name = b.action.label or b.action.describe()
            assert b.carrier.qt is not None   # plan only binds bindable keys
            prev_name, qts = wanted.get(did, (name, []))
            wanted[did] = (prev_name, qts + [b.carrier.qt])
        if created and host.which("kbuildsycoca6"):
            host.run(["kbuildsycoca6", "--noincremental"], timeout=120)
        previous_created = set(self.state.kde_created)
        applied = self.kde.apply(wanted, self.state.kde, previous_created | created)
        for did in previous_created - created:
            launchers.remove_launcher(did)
        missing = [did for did, (_, qts) in wanted.items() if set(qts) - set(applied.get(did, []))]
        for did in missing:
            report.errors.append(f"KDE refused a shortcut for {did} (key already taken?).")
        self.state.kde = applied
        self.state.kde_created = sorted(created)
        report.messages.append(f"KDE: {sum(len(v) for v in applied.values())} shortcuts active.")

    def _apply_gnome(self, plan: plan_mod.Plan, report: ApplyReport) -> None:
        wanted = {}
        for b in plan.bindings:
            try:
                command = launchers.shell_command(b.action)
            except LookupError as e:
                report.key_errors[b.key.id] = str(e)
                continue
            assert b.carrier.keysym is not None   # plan only binds bindable keys
            wanted[b.key.id] = (f"{b.key.label}: {b.action.describe()}", command, b.carrier.keysym)
        self.state.gnome = self.gnome.apply(wanted, self.state.gnome)
        report.messages.append(f"GNOME: {len(self.state.gnome)} shortcuts active.")

    def reset_all(self) -> ApplyReport:
        """Remove every system file and shortcut dmpkeys created. Config is kept."""
        report = ApplyReport(ok=True)
        result = privileged.reset()
        if not result.ok:
            return ApplyReport(False, errors=[f"System reset failed: {result.error}"])
        report.messages.append("Removed system key mapping and favorites fix.")
        if self.desktop == DESKTOP_KDE:
            self.kde.apply({}, self.state.kde, set(self.state.kde_created))
        elif self.desktop == DESKTOP_GNOME:
            self.gnome.apply({}, self.state.gnome)
        for did in self.state.kde_created:
            launchers.remove_launcher(did)
        self.state = state_mod.State()
        state_mod.save(self.state, self._state_path)
        report.messages.append("Removed desktop shortcuts.")
        return report

    def capture_argv(self, seconds: int = 15) -> list[str]:
        return privileged.capture_argv(seconds)

    # --- first run -----------------------------------------------------------------
    def import_existing(self) -> list[str]:
        """Adopt a setup made by hand (legacy hwdb files + existing desktop shortcuts).

        Fills the config with what the keys currently do and records existing KDE
        bindings as ours, so the next Apply moves them instead of fighting them.
        Returns human-readable notes on what was imported.
        """
        notes = []
        remaps: dict[int, str] = {}
        for path in hwdb.legacy_files():
            found = hwdb.parse(host.host_path(path).read_text())
            remaps.update(found)
            if found:
                notes.append(f"Read {len(found)} remaps from {path}.")
        for key in self.config.all_keys():
            effective = remaps.get(key.scancode, key.native) if key.scancode is not None else key.native
            kk = keycodes.lookup(effective)
            action = self._existing_binding(kk) if kk else None
            if action is not None:
                self.config.set_action(key.id, action)
                notes.append(f"{key.label}: {action.describe()}")
            elif key.scancode in remaps and remaps[key.scancode] != key.native:
                target = remaps[key.scancode]
                self.config.set_action(key.id, Action(Kind.DISABLE) if target == "reserved"
                                       else Action(Kind.KEY, target))
                notes.append(f"{key.label}: sends {target}")
        self.save_config()
        state_mod.save(self.state, self._state_path)
        self.first_run = False
        return notes

    def _find_existing_binding(self, kk: keycodes.KernelKey) -> tuple[Action, str] | None:
        """A hand-made KDE launcher shortcut on this key, as (action, component). Read-only."""
        if self.desktop != DESKTOP_KDE or kk.qt is None:
            return None
        for owner in self.kde.owners(kk.qt):
            if owner.action != "_launch" or not owner.component.endswith(".desktop"):
                continue
            if owner.is_default_for(kk.qt):
                continue  # KDE's own default (e.g. Calculator -> KCalc), not a customization
            if owner.component.startswith(launchers.PREFIX):
                continue  # ours
            if owner.component.startswith("net.local."):
                return _action_from_launcher(owner.component, owner.friendly), owner.component
            app = apps.lookup(owner.component)
            return Action(Kind.APP, owner.component, app.name if app else owner.friendly), owner.component
        return None

    def _effective_kernel_keys(self) -> list[tuple[KeyDef, keycodes.KernelKey | None, dict[int, str]]]:
        remaps = self.current_remaps()
        out = []
        for key in self.config.all_keys():
            effective = remaps.get(key.scancode, key.native) if key.scancode is not None else key.native
            out.append((key, keycodes.lookup(effective), remaps))
        return out

    def has_existing_setup(self) -> bool:
        """A hand-made setup exists that import_existing() would adopt. Read-only."""
        status = self.status()
        if status.legacy_hwdb or status.legacy_rules:
            return True
        return any(kk is not None and self._find_existing_binding(kk) is not None
                   for _key, kk, _ in self._effective_kernel_keys())

    def _existing_binding(self, kk: keycodes.KernelKey) -> Action | None:
        """Like _find_existing_binding, and records the binding as ours (adoption)."""
        found = self._find_existing_binding(kk)
        if found is None:
            return None
        action, component = found
        assert kk.qt is not None
        adopted = self.state.kde.setdefault(component, [])
        if kk.qt not in adopted:
            adopted.append(kk.qt)
        return action


_FILE_MANAGERS = r"(?:dolphin|nautilus|nemo|thunar|caja|pcmanfm(?:-qt)?|xdg-open)"


def _action_from_launcher(desktop_id: str, friendly: str) -> Action:
    path = apps.find(desktop_id)
    exec_line = ""
    if path is not None:
        entry = apps.parse_desktop(path) or {}
        exec_line = re.sub(r"\s%[fFuUdDnNickvm]", "", entry.get("Exec", "")).strip()
    m = re.fullmatch(_FILE_MANAGERS + r"\s+(/\S+)", exec_line)
    if m:
        return Action(Kind.FOLDER, m.group(1), friendly)
    return Action(Kind.COMMAND, exec_line or desktop_id, friendly)
