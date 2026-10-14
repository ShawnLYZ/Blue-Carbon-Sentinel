"""The Demo Director state machine (design §27, addendum I2/I3/J2).

In memory only. It listens to the EventBus and advances the *current* step when that step's real trigger
event arrives. Events for any other step are ignored (a late event never re-opens a skipped or finished
step). Every state change publishes ``director.state``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from bcs_protocol.timefmt import to_iso

from bcs_gs.api import models as m
from bcs_gs.core.clock import Clock
from bcs_gs.core.events import Event, EventBus
from bcs_gs.director.steps import EARLY_WARNING, STEPS, Context, StepDef

log = logging.getLogger("bcs_gs.director")

CAMERA_OFFLINE_REASON = "Camera offline — step requires live captures"


class DirectorInactive(Exception):
    """skip/retry while the Director is not running."""


class Director:
    def __init__(self, bus: EventBus, camera: Any, clock: Clock) -> None:
        self._bus = bus
        self._camera = camera
        self._clock = clock
        self._sub: Any = None
        self._listener: asyncio.Task[None] | None = None
        self._reset(active=False, branch="main")

    # ---- lifecycle of the listener ------------------------------------------------------------------
    def open(self) -> None:
        self._sub = self._bus.subscribe(10000)
        self._listener = asyncio.create_task(self._listen(), name="director-listen")

    async def aclose(self) -> None:
        if self._sub is not None:
            self._sub.close()
        if self._listener is not None:
            self._listener.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._listener
            self._listener = None

    async def _listen(self) -> None:
        while True:
            sub = self._sub
            async for ev in sub:
                try:
                    self._on_event(ev)
                except Exception:
                    log.exception("director failed on %s", ev.type)
            if not sub.overflowed:
                return
            log.warning("director event subscription overflowed; resubscribing")
            self._sub = self._bus.subscribe(10000)

    # ---- controls -----------------------------------------------------------------------------------
    def start(self, branch: str = "main") -> m.DirectorState:
        self._reset(active=True, branch=branch)
        self._enter(0)
        return self._publish()

    def skip(self) -> m.DirectorState:
        i = self._require_current()
        self._status[i] = "skipped"
        self._blocked[i] = None
        self._ctx.clear_progress(self._defs[i].key)  # keep what other steps found
        self._enter(i + 1)
        return self._publish()

    def retry(self) -> m.DirectorState:
        i = self._require_current()
        self._detected[i] = None
        self._ctx.clear_progress(self._defs[i].key)
        self._ctx.step_started_at = self._clock.now()
        self._refresh(i)
        return self._publish()

    def stop(self) -> m.DirectorState:
        self._active = False
        self._current = None
        return self._publish()

    def reset(self) -> None:
        """Test reset: forget everything, publish nothing."""
        self._reset(active=False, branch="main")

    def state(self) -> m.DirectorState:
        defs = self._defs
        steps = [
            m.DirectorStep(
                key=d.key, n=d.n, caption=d.caption, action=d.action, status=self._status[i],
                blocked_reason=self._blocked[i], detected=self._detected[i],
            )
            for i, d in enumerate(defs)
        ]  # fmt: skip
        current = defs[self._current].key if self._current is not None else None
        return m.DirectorState(
            active=self._active, branch=self._branch, current=current, started_at=self._started_at, steps=steps
        )  # type: ignore[arg-type]

    # ---- internals ----------------------------------------------------------------------------------
    def _reset(self, *, active: bool, branch: str) -> None:
        self._active = active
        self._branch = branch
        self._defs: list[StepDef] = ([EARLY_WARNING] if branch == "early_warning" else []) + STEPS
        n = len(self._defs)
        self._status: list[str] = ["pending"] * n
        self._blocked: list[str | None] = [None] * n
        self._detected: list[m.DirectorDetected | None] = [None] * n
        self._current: int | None = None
        self._ctx = Context()
        self._started_at = to_iso(self._clock.now()) if active else None

    def _require_current(self) -> int:
        if not self._active or self._current is None:
            raise DirectorInactive("The Demo Director has no current step.")
        return self._current

    def _enter(self, i: int) -> None:
        if i >= len(self._defs):
            self._current = None  # every step is done or skipped
            return
        self._current = i
        self._ctx.step_started_at = self._clock.now()
        self._refresh(i)

    def _camera_online(self) -> bool:
        try:
            return bool(self._camera.status().online)
        except Exception:  # noqa: BLE001 (a failing status read counts as offline; never break the step)
            return False

    def _refresh(self, i: int) -> None:
        """Waiting or blocked, for the current step."""
        if self._defs[i].needs_camera and not self._camera_online():
            self._status[i], self._blocked[i] = "blocked", CAMERA_OFFLINE_REASON
        else:
            self._status[i], self._blocked[i] = "waiting", None

    def _publish(self) -> m.DirectorState:
        state = self.state()
        self._bus.publish("director.state", state.model_dump(mode="json"))
        return state

    def _on_event(self, ev: Event) -> None:
        if not self._active or self._current is None or ev.type == "director.state":
            return
        i = self._current
        if ev.type == "plan.updated" and ev.data.get("status") == "applied":
            # Carried in context whenever it happens, so restore's first phase is satisfied if the operator
            # applied the plan earlier (e.g. during predict). It never reopens or advances another step.
            self._ctx.note_plan(ev.data)
        if ev.type == "camera.status":
            before = (self._status[i], self._blocked[i])
            self._refresh(i)
            if (self._status[i], self._blocked[i]) != before:
                self._publish()
            return
        d = self._defs[i]
        if not d.advance_on(ev, self._ctx):
            return
        self._status[i], self._blocked[i] = "done", None
        self._detected[i] = m.DirectorDetected(type=ev.type, at=ev.at, summary=d.summarize(ev, self._ctx))
        self._enter(i + 1)
        self._publish()
