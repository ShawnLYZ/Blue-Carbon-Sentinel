"""Ensure the Ground Station's own broker identity ``bcs-gs`` exists (addendum G6).

Runs as a background task: it never delays serving. When the broker or the admin credentials are
missing it does nothing (preflight reports them); when the broker is not up yet it retries with
back-off.
"""

from __future__ import annotations

import asyncio
import logging

from bcs_gs.core.config import Settings
from bcs_gs.nodes.broker_admin import BrokerAdmin

log = logging.getLogger("bcs_gs.broker_identity")

GS_USER = "bcs-gs"
FIRST_DELAY_S = 1.0
MAX_DELAY_S = 30.0


async def ensure_gs_identity(settings: Settings, *, max_attempts: int | None = None) -> bool:
    """Create or refresh ``bcs-gs``; True on success, False when skipped or attempts ran out."""
    admin_pw, gs_pw = settings.broker_admin_password, settings.gs_mqtt_password
    if admin_pw is None or gs_pw is None:
        return False
    admin = BrokerAdmin(
        "127.0.0.1", settings.broker_port, settings.broker_admin_user, admin_pw.get_secret_value()
    )
    delay = FIRST_DELAY_S
    attempt = 0
    while max_attempts is None or attempt < max_attempts:
        attempt += 1
        try:
            await asyncio.to_thread(admin.ensure_service_identity, GS_USER, gs_pw.get_secret_value())
            log.info("broker identity %s ready", GS_USER)
            return True
        except Exception as exc:  # noqa: BLE001
            log.info("broker identity not ready (%s); retrying in %.0fs", type(exc).__name__, delay)
        await asyncio.sleep(delay)
        delay = min(delay * 2, MAX_DELAY_S)
    return False
