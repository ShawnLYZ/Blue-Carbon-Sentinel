"""Alerts (spec 25): deduplicated, acknowledgeable alerts raised from events."""

from bcs_gs.alerts.rules import ALERT_RULES, AlertRule
from bcs_gs.alerts.service import AlertService

__all__ = ["ALERT_RULES", "AlertRule", "AlertService"]
