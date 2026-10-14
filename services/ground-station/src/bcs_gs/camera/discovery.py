"""Find the ESP32-CAM: configured address, then the system resolver, then zeroconf (addendum L3)."""

from __future__ import annotations

import logging
import socket

log = logging.getLogger("bcs_gs.camera")

MDNS_SERVICE_TYPE = "_http._tcp.local."
MDNS_SERVICE_NAME = "sentinel-cam._http._tcp.local."
ZEROCONF_TIMEOUT_MS = 2500


def _system_resolve(host: str) -> str | None:
    try:
        infos = socket.getaddrinfo(host, 80, socket.AF_INET, socket.SOCK_STREAM)
    except OSError:
        return None
    for info in infos:
        sockaddr = info[4]
        if sockaddr and sockaddr[0]:
            return str(sockaddr[0])
    return None


def _zeroconf_resolve() -> str | None:
    try:
        from zeroconf import IPVersion, Zeroconf

        zc = Zeroconf(ip_version=IPVersion.V4Only)
        try:
            info = zc.get_service_info(MDNS_SERVICE_TYPE, MDNS_SERVICE_NAME, timeout=ZEROCONF_TIMEOUT_MS)
            addrs = info.parsed_addresses(IPVersion.V4Only) if info else []
            return addrs[0] if addrs else None
        finally:
            zc.close()
    except Exception as exc:  # noqa: BLE001  (discovery must never raise)
        log.debug("zeroconf discovery failed: %s", type(exc).__name__)
        return None


def resolve_camera(host: str, override: str | None) -> str | None:
    """Return an IPv4 address (or the override verbatim) for the camera, or ``None``."""
    if override:
        return override
    return _system_resolve(host) or _zeroconf_resolve()
