"""The UI's view of the backend: cached state plus asynchronous calls through the worker.

Widgets never call the Backend directly. They read cached data from Session
(always on the GUI thread) and ask it to change things; Session forwards every
backend call to the single BackendWorker and emits signals when fresh data
arrives.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable

from PySide6.QtCore import QObject, QTimer, Signal

from ..core.config import Action, Kind
from ..core.keys import KeyDef
from ..core.plan import Binding, Plan
from .text import describe
from .worker import BackendWorker

if TYPE_CHECKING:
    from ..core.apps import App
    from ..core.backend import ApplyReport, Backend
    from ..core.device import Status

PLAN_DELAY_MS = 250
STATUS_POLL_MS = 5000


class Effect(Enum):
    DEFAULT = "default"
    KEY = "key"          # sends another key
    ACTION = "action"    # launches something through a desktop shortcut
    DISABLED = "disabled"


def effect_of(action: Action) -> Effect:
    if action.kind == Kind.DEFAULT:
        return Effect.DEFAULT
    if action.kind == Kind.KEY:
        return Effect.KEY
    if action.kind == Kind.DISABLE:
        return Effect.DISABLED
    return Effect.ACTION


@dataclass(frozen=True)
class KeyView:
    """Everything the UI shows about one key."""
    key: KeyDef
    action: Action
    pending: bool                 # saved but not applied yet
    error: str | None             # why it won't work, from the plan
    confirmed: bool               # verified in the catalog or seen by Detect this session
    binding: Binding | None = None

    @property
    def effect(self) -> Effect:
        return effect_of(self.action)

    @property
    def id(self) -> str:
        return self.key.id


@dataclass(frozen=True)
class Snapshot:
    """Config-derived state, computed on the worker thread after every change."""
    keys: tuple[KeyDef, ...]
    actions: dict[str, Action]
    applied: dict[str, Action]            # at the last successful Apply
    pending: frozenset[str]
    favorites_fix: bool
    favorites_fix_pending: bool
    first_run: bool


def take_snapshot(backend: Backend) -> Snapshot:
    keys = tuple(backend.keys())
    return Snapshot(
        keys=keys,
        actions={k.id: backend.action(k.id) for k in keys},
        applied={k.id: backend.applied_action(k.id) for k in keys},
        pending=frozenset(backend.pending_keys()),
        favorites_fix=backend.config.favorites_fix,
        favorites_fix_pending=backend.favorites_fix_pending(),
        first_run=backend.first_run,
    )


@dataclass
class ApplyPreview:
    """What Apply is about to do, in user terms."""
    key_changes: list[tuple[str, str]] = field(default_factory=list)   # (key, "Sends Brightness up")
    shortcuts: list[tuple[str, str]] = field(default_factory=list)     # (key, "Opens Firefox")
    disable_files: list[str] = field(default_factory=list)
    favorites_fix: str | None = None   # sentence when the fix is installed/removed
    problems: list[tuple[str, str]] = field(default_factory=list)      # (key, message)
    warnings: list[str] = field(default_factory=list)
    needs_password: bool = False
    remaps: list[tuple[str, str]] = field(default_factory=list)        # technical: (scancode, kernel key)


def build_preview(backend: Backend, disable_legacy: bool) -> ApplyPreview:
    plan = backend.plan()
    change = backend.system_change(plan, disable_legacy)
    status = backend.status()
    preview = ApplyPreview(needs_password=change.needed, disable_files=list(change.disable),
                           warnings=list(plan.warnings))
    for key in backend.keys():
        action = backend.action(key.id)
        if key.id in plan.errors:
            preview.problems.append((key.label, plan.errors[key.id]))
        elif action.kind in (Kind.KEY, Kind.DISABLE):
            preview.key_changes.append((key.label, describe(action, key)))
    for b in plan.bindings:
        preview.shortcuts.append((b.key.label, describe(b.action, b.key)))
    if plan.favorites_fix and not status.favorites_fix_installed:
        preview.favorites_fix = "Install the driver fix that makes Favorites 1–5 work."
    elif not plan.favorites_fix and status.favorites_fix_installed:
        preview.favorites_fix = "Remove the favorites driver fix."
    preview.remaps = [(f"0x{scan:x}", name) for scan, name in sorted(plan.remaps.items())]
    return preview


class Session(QObject):
    changed = Signal()            # keys, actions or pending state
    planChanged = Signal()
    statusChanged = Signal()
    errorOccurred = Signal(str)

    def __init__(self, backend: Backend, worker: BackendWorker | None = None,
                 parent: QObject | None = None, *, poll_status: bool = True):
        super().__init__(parent)
        self._backend = backend
        self.worker = worker or BackendWorker()
        self.worker.setParent(self)
        self.worker.failed.connect(self.errorOccurred)
        self.desktop: str | None = backend.desktop
        self.desktop_name: str = backend.desktop_name
        self.keep_legacy = False
        self.status: Status | None = None
        self.plan: Plan | None = None
        self.plan_loading = False
        self.existing_setup = False   # a hand-made setup that Import would adopt
        self._confirmed: set[str] = set()
        self._apps: list[App] | None = None
        self._apps_waiting: list[Callable[[list[App]], None]] = []
        self._plan_running = False
        self._plan_again = False
        # Reading the in-memory config is instant; do it now so the first paint is complete.
        self._snap = take_snapshot(backend)

        self._plan_timer = QTimer(self, singleShot=True, interval=PLAN_DELAY_MS)
        self._plan_timer.timeout.connect(self._start_plan)
        self._status_timer = QTimer(self, interval=STATUS_POLL_MS)
        self._status_timer.timeout.connect(self._poll_status)
        if poll_status and self.worker.threaded:
            self._status_timer.start()

    # --- loading -----------------------------------------------------------------------
    def load(self) -> None:
        """Fetch status, the plan and whether there is a setup to import."""
        self.refresh_status()
        if self._snap.first_run:
            # Only decides whether to offer an import; if it fails, just don't offer it.
            self.worker.submit(self._backend.has_existing_setup, self._got_existing_setup,
                               lambda _e: None)
        self.refresh_plan(now=True)

    def _got_existing_setup(self, found: bool) -> None:
        self.existing_setup = found
        self.statusChanged.emit()

    def refresh_status(self) -> None:
        self.worker.submit(self._backend.status, self._got_status)

    def _poll_status(self) -> None:
        if not self.worker.busy:
            self.worker.submit(self._backend.status, self._got_status, lambda _e: None)

    def _got_status(self, status: Status) -> None:
        if status != self.status:
            self.status = status
            self.statusChanged.emit()

    def refresh_plan(self, now: bool = False) -> None:
        self.plan_loading = True
        if now or not self.worker.threaded:
            self._plan_timer.stop()
            self._start_plan()
        else:
            self._plan_timer.start()

    def _start_plan(self) -> None:
        if self._plan_running:
            self._plan_again = True   # config changed while planning: plan once more after
            return
        self._plan_running = True
        self._plan_again = False
        self.plan_loading = True
        self.planChanged.emit()
        self.worker.submit(self._backend.plan, self._got_plan, self._plan_failed)

    def _got_plan(self, plan: Plan) -> None:
        self._plan_running = False
        self.plan = plan
        self.plan_loading = self._plan_again
        self.planChanged.emit()
        self.changed.emit()
        if self._plan_again:
            self._start_plan()

    def _plan_failed(self, error: BaseException) -> None:
        self._plan_running = False
        self.plan_loading = False
        self.planChanged.emit()
        self.errorOccurred.emit(f"Couldn't check the setup: {error}")

    # --- reading -----------------------------------------------------------------------
    def keys(self) -> tuple[KeyDef, ...]:
        return self._snap.keys

    def key(self, key_id: str) -> KeyDef | None:
        return next((k for k in self._snap.keys if k.id == key_id), None)

    def action(self, key_id: str) -> Action:
        return self._snap.actions.get(key_id, Action())

    def applied_action(self, key_id: str) -> Action:
        return self._snap.applied.get(key_id, Action())

    def view(self, key_id: str) -> KeyView | None:
        key = self.key(key_id)
        return self._view_of(key) if key is not None else None

    def _view_of(self, key: KeyDef) -> KeyView:
        binding = None
        error = None
        if self.plan is not None:
            error = self.plan.errors.get(key.id)
            binding = next((b for b in self.plan.bindings if b.key.id == key.id), None)
        return KeyView(key, self.action(key.id), key.id in self._snap.pending, error,
                       key.verified or key.id in self._confirmed, binding)

    def views(self) -> dict[str, KeyView]:
        return {k.id: self._view_of(k) for k in self._snap.keys}

    @property
    def favorites_fix(self) -> bool:
        return self._snap.favorites_fix

    @property
    def favorites_fix_pending(self) -> bool:
        return self._snap.favorites_fix_pending

    @property
    def favorites_fix_change(self) -> str:
        """What Apply does about the favorites fix, when that is pending."""
        return ("Installs the hid-microsoft driver fix" if self._snap.favorites_fix
                else "Removes the hid-microsoft driver fix")

    @property
    def pending_count(self) -> int:
        return len(self._snap.pending) + int(self._snap.favorites_fix_pending)

    @property
    def first_run(self) -> bool:
        return self._snap.first_run

    @property
    def legacy_files(self) -> list[str]:
        if self.status is None:
            return []
        return [str(p) for p in self.status.legacy_hwdb + self.status.legacy_rules]

    @property
    def offer_import(self) -> bool:
        return self.first_run and self.existing_setup

    def confirm(self, key_id: str) -> None:
        """Detect saw this key: treat it as verified for the rest of the session."""
        if key_id not in self._confirmed:
            self._confirmed.add(key_id)
            self.changed.emit()

    # --- changing ----------------------------------------------------------------------
    def set_action(self, key_id: str, action: Action) -> None:
        actions = dict(self._snap.actions)
        actions[key_id] = action
        self._replace_snapshot(actions=actions)   # optimistic: the UI updates at once
        self._mutate(lambda: self._backend.set_action(key_id, action))

    def set_actions(self, changes: dict[str, Action]) -> None:
        """Several keys at once (slider presets), as one change."""
        actions = dict(self._snap.actions)
        actions.update(changes)
        self._replace_snapshot(actions=actions)

        def run() -> None:
            for key_id, action in changes.items():
                self._backend.set_action(key_id, action)
        self._mutate(run)

    def revert(self, key_id: str) -> None:
        """Back to what was last applied."""
        self.set_action(key_id, self.applied_action(key_id))

    def set_favorites_fix(self, enabled: bool) -> None:
        self._replace_snapshot(favorites_fix=enabled)
        self._mutate(lambda: self._backend.set_favorites_fix(enabled))

    def add_custom_key(self, scancode: int, native: str, label: str,
                       on_done: Callable[[KeyDef], None] | None = None) -> None:
        def done(key: KeyDef) -> None:
            if on_done is not None:
                on_done(key)
        self.worker.submit(lambda: self._backend.add_custom_key(scancode, native, label), done,
                           self._report_error("Couldn't add the key"))
        self._sync()

    def rename_custom_key(self, scancode: int, label: str) -> None:
        self._mutate(lambda: self._backend.rename_custom_key(scancode, label))

    def remove_custom_key(self, scancode: int) -> None:
        self._mutate(lambda: self._backend.remove_custom_key(scancode))

    def _replace_snapshot(self, **changes: Any) -> None:
        self._snap = replace(self._snap, **changes)
        self.changed.emit()

    def _mutate(self, fn: Callable[[], None]) -> None:
        self.worker.submit(fn, None, self._report_error("Couldn't save the change"))
        self._sync()

    def _sync(self) -> None:
        """Re-read config state from the backend, then recheck the plan."""
        self.worker.submit(lambda: take_snapshot(self._backend), self._got_snapshot)
        self.refresh_plan()

    def _got_snapshot(self, snap: Snapshot) -> None:
        self._snap = snap
        self.changed.emit()

    def _report_error(self, prefix: str) -> Callable[[BaseException], None]:
        return lambda e: self.errorOccurred.emit(f"{prefix}: {e}")

    # --- apps --------------------------------------------------------------------------
    def apps(self, on_done: Callable[[list[App]], None]) -> None:
        """Installed apps, loaded once in the background."""
        if self._apps is not None:
            on_done(self._apps)
            return
        self._apps_waiting.append(on_done)
        if len(self._apps_waiting) == 1:
            self.worker.submit(self._backend.apps, self._got_apps, self._apps_failed)

    def _got_apps(self, apps: list[App]) -> None:
        self._apps = apps
        waiting, self._apps_waiting = self._apps_waiting, []
        for cb in waiting:
            cb(apps)

    def _apps_failed(self, error: BaseException) -> None:
        self._got_apps([])
        self.errorOccurred.emit(f"Couldn't list installed apps: {error}")

    # --- applying and other long operations ---------------------------------------------
    def prepare_apply(self, on_done: Callable[[ApplyPreview], None],
                      on_error: Callable[[BaseException], None]) -> None:
        disable = not self.keep_legacy
        self.worker.submit(lambda: build_preview(self._backend, disable), on_done, on_error)

    def apply(self, on_done: Callable[[ApplyReport], None],
              on_error: Callable[[BaseException], None]) -> None:
        disable = not self.keep_legacy
        self.worker.submit(lambda: self._backend.apply(disable_legacy=disable),
                           self._after(on_done), self._after_error(on_error))

    def reset_all(self, on_done: Callable[[ApplyReport], None],
                  on_error: Callable[[BaseException], None]) -> None:
        self.worker.submit(self._backend.reset_all, self._after(on_done),
                           self._after_error(on_error))

    def import_existing(self, on_done: Callable[[list[str]], None],
                        on_error: Callable[[BaseException], None]) -> None:
        self.worker.submit(self._backend.import_existing, self._after(on_done),
                           self._after_error(on_error))

    def _after(self, cb: Callable[[Any], None]) -> Callable[[Any], None]:
        def done(result: Any) -> None:
            self._refresh_all()
            cb(result)
        return done

    def _after_error(self, cb: Callable[[BaseException], None]) -> Callable[[BaseException], None]:
        def failed(error: BaseException) -> None:
            self._refresh_all()
            cb(error)
        return failed

    def _refresh_all(self) -> None:
        self.refresh_status()
        self._sync()

    def capture_argv(self, seconds: int) -> list[str]:
        """Builds a command line only; nothing runs (safe on the GUI thread)."""
        return self._backend.capture_argv(seconds)

    def shutdown(self) -> bool:
        self._status_timer.stop()
        self._plan_timer.stop()
        return self.worker.shutdown()
