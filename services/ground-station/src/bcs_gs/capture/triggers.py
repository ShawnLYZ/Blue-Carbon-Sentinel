"""Frame difference, the stable-change trigger and cloud eligibility (addendum N7, A2; spec section 9)."""

from __future__ import annotations

from datetime import datetime

import cv2
import numpy as np

DIFF_SIZE_PX = 128
DIFF_BLUR_SIGMA = 1.0
CHANGE_THRESHOLD = 6.0


def _processed(rgb: np.ndarray, size: int, sigma: float) -> np.ndarray:
    grey = cv2.cvtColor(np.ascontiguousarray(rgb, np.uint8), cv2.COLOR_RGB2GRAY)
    small = cv2.resize(grey, (size, size), interpolation=cv2.INTER_AREA).astype(np.float32)
    return cv2.GaussianBlur(small, (0, 0), sigma, borderType=cv2.BORDER_REFLECT)


def frame_difference(
    a_rgb: np.ndarray, b_rgb: np.ndarray, size: int = DIFF_SIZE_PX, sigma: float = DIFF_BLUR_SIGMA
) -> float:
    """N7: greyscale -> ``size`` x ``size`` -> Gaussian blur (sigma) -> mean absolute difference, 0-255."""
    return float(np.mean(np.abs(_processed(a_rgb, size, sigma) - _processed(b_rgb, size, sigma))))


class ChangeTrigger:
    """Change captures (N7): motion is a consecutive-frame difference > ``motion_threshold``; the scene
    is stable once no motion has been seen for ``stable_s``; a change capture is due when the stable
    scene differs from the last capture by > ``change_threshold``.

    The trigger keeps no latch: the caller takes the capture, after which ``diff_last_capture`` is
    measured against the new capture and drops, so the same stable scene does not fire again.
    """

    def __init__(
        self, motion_threshold: float = 4.0, change_threshold: float = 6.0, stable_s: float = 2.0
    ) -> None:
        self.motion_threshold = motion_threshold
        self.change_threshold = change_threshold
        self.stable_s = stable_s
        self.moving = False
        self._quiet_since: datetime | None = None  # last motion (or first observation)
        self._last_motion: datetime | None = None

    def observe(self, diff_prev: float, diff_last_capture: float, now: datetime) -> bool:
        if diff_prev > self.motion_threshold:
            self.moving = True
            self._quiet_since = now
            self._last_motion = now
            return False
        self.moving = False
        if self._quiet_since is None:
            self._quiet_since = now
        stable = (now - self._quiet_since).total_seconds() >= self.stable_s
        return stable and diff_last_capture > self.change_threshold

    def settled(self, now: datetime) -> bool:
        """No motion seen within ``stable_s`` before ``now`` (true if no motion was ever seen). A
        capture that is not settled is tagged motion: one of the last frames may still be from the
        movement that just ended."""
        if self.moving:
            return False
        return self._last_motion is None or (now - self._last_motion).total_seconds() >= self.stable_s


def cloud_eligible(
    trigger: str,
    flagged: bool,
    is_baseline: bool,
    referenced: bool,
    change_score: float | None,
    minute_already_sent: bool,
    *,
    change_threshold: float = CHANGE_THRESHOLD,
) -> bool:
    """A2, read literally (ruling j): change and manual captures, flagged captures, baselines and
    referenced captures are sent. Of the other interval captures only the first *unchanged* one of
    each UTC minute is sent (N7: ``change_score`` <= ``change_threshold``; ``None`` counts as
    unchanged). A changed, unflagged interval capture is not sent."""
    if trigger in ("change", "manual") or flagged or is_baseline or referenced:
        return True
    return is_unchanged(change_score, change_threshold) and not minute_already_sent


def is_unchanged(change_score: float | None, change_threshold: float = CHANGE_THRESHOLD) -> bool:
    """N7 "unchanged" score test (the caller also requires an unflagged interval capture)."""
    return change_score is None or change_score <= change_threshold
