"""Mosquitto configuration and dynamic-security bootstrap (addendum D1, G6, R)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
TEMPLATE = REPO_ROOT / "infra" / "mosquitto" / "mosquitto.conf.template"
WINDOWS_DIR = Path(r"C:\Program Files\mosquitto")
MIN_DYNSEC_PASSWORD = 12  # Mosquitto refuses a shorter MOSQUITTO_DYNSEC_PASSWORD


def find_mosquitto() -> str | None:
    """Path of the ``mosquitto`` binary (PATH first, then the Windows install), or None."""
    found = shutil.which("mosquitto")
    if found:
        return found
    candidate = WINDOWS_DIR / "mosquitto.exe"
    return str(candidate) if candidate.is_file() else None


def find_mosquitto_ctrl() -> str | None:
    found = shutil.which("mosquitto_ctrl")
    if found:
        return found
    candidate = WINDOWS_DIR / "mosquitto_ctrl.exe"
    return str(candidate) if candidate.is_file() else None


def plugin_path() -> str:
    """Location of the dynamic-security plugin."""
    if sys.platform == "win32":
        return str(WINDOWS_DIR / "mosquitto_dynamic_security.dll")
    try:
        out = subprocess.run(
            ["dpkg", "-L", "mosquitto"], capture_output=True, text=True, timeout=10, check=False
        ).stdout
        for line in out.splitlines():
            if line.endswith("mosquitto_dynamic_security.so"):
                return line.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return "/usr/lib/x86_64-linux-gnu/mosquitto_dynamic_security.so"


def render_config(data_dir: Path, port: int, bind: str = "0.0.0.0") -> str:
    """Render the template. ``data_dir`` is the ``var`` directory.

    Mosquitto takes the rest of the line as the value and does not understand quotes, so a path
    with spaces ("Blue Carbon Sentinel") is written verbatim (Review Focus 5).
    """
    text = TEMPLATE.read_text(encoding="utf-8")
    values = {
        "{port}": str(port),
        "{bind}": bind,
        "{persistence_dir}": str(data_dir / "mosquitto" / "data") + os.sep,
        "{log_file}": str(data_dir / "logs" / "mosquitto.log"),
        "{dynsec_file}": str(data_dir / "mosquitto" / "dynamic-security.json"),
        "{plugin_path}": plugin_path(),
    }
    for key, value in values.items():
        text = text.replace(key, value)
    return text


def bootstrap(data_dir: Path, admin_user: str, admin_password: str, port: int) -> None:
    """Write ``<data_dir>/mosquitto/mosquitto.conf`` and the dynamic-security JSON with the admin.

    The admin keeps one role, ``dynsec-admin`` (the dynamic-security control topic only, G6).
    An existing dynamic-security file is left untouched, so clients survive a re-run.

    Addendum R, in order of preference:
    1. First start with ``MOSQUITTO_DYNSEC_PASSWORD``: the plugin generates the file, hashed in
       its own format, with a user called ``admin``; the user name is then renamed in the JSON.
       WORKED on this machine (Windows 11, Mosquitto 2.1.2). The password must have at least 12
       characters. It travels in the child's environment only.
    2. ``mosquitto_ctrl dynsec init <file> <user> <password>`` (tried only if 1 produces no file;
       the password is briefly visible in that child's arguments).
    """
    mosq = data_dir / "mosquitto"
    for sub in (mosq / "data", data_dir / "logs"):
        sub.mkdir(parents=True, exist_ok=True)
    conf = mosq / "mosquitto.conf"
    conf.write_text(render_config(data_dir, port), encoding="utf-8", newline="\n")
    dynsec = mosq / "dynamic-security.json"
    first_start_ok = (
        not dynsec.exists()
        and len(admin_password) >= MIN_DYNSEC_PASSWORD
        and _first_start(conf, dynsec, admin_password)
    )
    if not dynsec.exists() and not first_start_ok:
        _ctrl_init(dynsec, admin_user, admin_password)
    _finish_admin(dynsec, admin_user)


def _first_start(conf: Path, dynsec: Path, password: str) -> bool:
    exe = find_mosquitto()
    if exe is None:
        return False
    env = {**os.environ, "MOSQUITTO_DYNSEC_PASSWORD": password}
    proc = subprocess.Popen(
        [exe, "-c", str(conf)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if dynsec.exists() and dynsec.stat().st_size > 0:
                time.sleep(0.2)  # let the plugin finish writing
                return True
            if proc.poll() is not None:
                break
            time.sleep(0.05)
        return dynsec.exists() and dynsec.stat().st_size > 0
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


def _ctrl_init(dynsec: Path, admin_user: str, admin_password: str) -> None:
    exe = find_mosquitto_ctrl()
    if exe is None:
        raise RuntimeError("dynamic-security bootstrap failed: neither first-start nor mosquitto_ctrl worked")
    result = subprocess.run(
        [exe, "dynsec", "init", str(dynsec), admin_user, admin_password],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0 or not dynsec.exists():
        raise RuntimeError("mosquitto_ctrl dynsec init failed")


_CONTROL_ACLS = [
    {"acltype": t, "topic": "$CONTROL/dynamic-security/#", "priority": 0, "allow": True}
    for t in ("publishClientSend", "publishClientReceive", "subscribePattern", "unsubscribePattern")
]


def _finish_admin(dynsec: Path, admin_user: str) -> None:
    """Name the admin as configured and limit it to the dynamic-security control topic (G6).

    Both bootstrap paths end here: ``dynsec init`` makes a wider role called ``admin``, so the
    admin gets a ``dynsec-admin`` role with the control-topic ACLs only, and the generated
    ``admin`` role is dropped unless another client still uses it.
    """
    doc = json.loads(dynsec.read_text(encoding="utf-8"))
    clients = doc.get("clients", [])
    admin = next((c for c in clients if c["username"] == admin_user), None) or next(
        (c for c in clients if c["username"] == "admin"), None
    )
    if admin is None:
        raise RuntimeError("dynamic-security file has no admin client")
    if admin["username"] != admin_user and any(c["username"] == admin_user for c in clients):
        raise RuntimeError("admin user name collides with an existing client")
    admin["username"] = admin_user
    admin["roles"] = [{"rolename": "dynsec-admin"}]
    roles = [r for r in doc.get("roles", []) if r["rolename"] != "dynsec-admin"]
    roles.append(
        {
            "rolename": "dynsec-admin",
            "textdescription": "Dynamic-security control topic only.",
            "acls": _CONTROL_ACLS,
        }
    )
    used = {r["rolename"] for c in clients for r in c.get("roles", [])}
    used |= {r["rolename"] for g in doc.get("groups", []) for r in g.get("roles", [])}
    doc["roles"] = [r for r in roles if r["rolename"] != "admin" or "admin" in used]
    dynsec.write_text(json.dumps(doc, indent=2) + chr(10), encoding="utf-8", newline=chr(10))
