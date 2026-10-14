"""Asyncio helpers for background work that must stop cleanly (shutdown, the test reset; ruling R30).

* ``to_thread_settled(fn, ...)``: ``asyncio.to_thread``, except that a cancellation waits for the thread to
  finish before ``CancelledError`` propagates. A plain ``to_thread`` returns at once on cancellation while
  its thread keeps running, so a write (a row, a media file) could land after the caller believed the
  task was gone, e.g. after ``/test/reset`` cleared the tables.
* ``cancel_and_wait(tasks)``: cancel the tasks and wait until every one has ended.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable, Iterable
from typing import Any, TypeVar

T = TypeVar("T")


async def to_thread_settled(fn: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    fut = asyncio.ensure_future(asyncio.to_thread(fn, *args, **kwargs))
    try:
        return await asyncio.shield(fut)
    except asyncio.CancelledError:
        while not fut.done():  # the thread cannot be stopped: wait for it, whatever else is cancelled
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.wait({fut})
        if not fut.cancelled():
            fut.exception()  # retrieved: a failure of the abandoned work is not reported again
        raise


async def cancel_and_wait(tasks: Iterable[asyncio.Task[Any]]) -> None:
    pending = [t for t in tasks if not t.done()]
    for t in pending:
        t.cancel()
    if pending:
        await asyncio.wait(pending)  # never raises the tasks' own errors; a cancel of the caller still does
