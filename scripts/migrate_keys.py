"""One-off migration: API_Key_Configuration.md -> gitignored .env (addendum E1).

Prints variable NAMES only, never values.
"""
from __future__ import annotations

import argparse
import re
import secrets
import sys
from collections.abc import Callable
from pathlib import Path

LABELS = {
    "anon api key": "BCS_SUPABASE_ANON_KEY",
    "project url": "BCS_SUPABASE_URL",
    "supabase personal access token": "SUPABASE_ACCESS_TOKEN",
    "database password": "SUPABASE_DB_PASSWORD",
    "supabase_service_role_key": "BCS_SUPABASE_SERVICE_ROLE_KEY",
}
GENERATED = [
    "BCS_BROKER_ADMIN_PASSWORD",
    "BCS_GS_MQTT_PASSWORD",
    "BCS_SIM_SHARED_TOKEN",
    "BCS_CAMERA_TOKEN",
    "BCS_CAMERA_OTA_PASSWORD",
]
DEFAULTS = {
    "BCS_BROKER_ADMIN_USER": "admin",
    "BCS_CAMERA_HOST": "sentinel-cam.local",
    "BCS_DEMO_TIME_SCALE": "on",
    "BCS_LOG_LEVEL": "INFO",
}
OPTIONAL_EMPTY = [
    "BCS_SITE_NW_LAT", "BCS_SITE_NW_LNG", "BCS_MODEL_GEMINI_PRIMARY",
    "BCS_MODEL_GEMINI_SECONDARY", "BCS_MODEL_GEMINI_TREE", "BCS_MODEL_OLLAMA",
    "BCS_MODEL_IMAGE",
]
ORDER = [
    "BCS_GEMINI_API_KEY_1", "BCS_GEMINI_API_KEY_2", "BCS_GEMINI_API_KEY_3",
    "BCS_SUPABASE_URL", "BCS_SUPABASE_SERVICE_ROLE_KEY", "BCS_SUPABASE_ANON_KEY",
    "SUPABASE_DB_PASSWORD", "SUPABASE_ACCESS_TOKEN", "BCS_NVIDIA_API_KEY",
    "BCS_MAPBOX_PUBLIC_TOKEN", "BCS_BROKER_ADMIN_USER", "BCS_BROKER_ADMIN_PASSWORD",
    "BCS_GS_MQTT_PASSWORD", "BCS_SIM_SHARED_TOKEN", "BCS_CAMERA_TOKEN",
    "BCS_CAMERA_OTA_PASSWORD", "BCS_CAMERA_HOST", "BCS_DEMO_TIME_SCALE",
    *OPTIONAL_EMPTY, "BCS_LOG_LEVEL",
]
REQUIRED = [
    "BCS_GEMINI_API_KEY_1", "BCS_SUPABASE_URL", "BCS_SUPABASE_SERVICE_ROLE_KEY",
    "BCS_SUPABASE_ANON_KEY", "SUPABASE_DB_PASSWORD", "SUPABASE_ACCESS_TOKEN",
    "BCS_NVIDIA_API_KEY", "BCS_MAPBOX_PUBLIC_TOKEN",
]


def parse_key_file(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    heading = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            heading = line.lstrip("#").strip().lower()
            continue
        m = re.match(r"^(\d+)[.)]\s+(\S.*)$", line)
        if m and "gemini" in heading and 1 <= int(m.group(1)) <= 3:
            out[f"BCS_GEMINI_API_KEY_{m.group(1)}"] = m.group(2).strip()
            continue
        if line.startswith("nvapi-"):
            out["BCS_NVIDIA_API_KEY"] = line
            continue
        if line.startswith("pk."):
            out["BCS_MAPBOX_PUBLIC_TOKEN"] = line
            continue
        if ":" in line:
            label, _, value = line.partition(":")
            name = LABELS.get(label.strip().lower())
            if name and value.strip():
                out[name] = value.strip()
    url = out.get("BCS_SUPABASE_URL")
    if url:
        out["BCS_SUPABASE_URL"] = re.sub(r"(/rest/v1)?/*$", "", url.strip())
    return out


def _q(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def build_env(parsed: dict[str, str], generate: Callable[[], str]) -> str:
    values: dict[str, str] = {name: "" for name in ORDER}
    values.update(DEFAULTS)
    values.update(parsed)
    for name in GENERATED:
        values[name] = generate()
    # Unset optional overrides stay commented out so empty strings never shadow config/*.yaml.
    return "".join(
        f"# {name}=\n" if name in OPTIONAL_EMPTY and not values[name] else f"{name}={_q(values[name])}\n"
        for name in ORDER
    )


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", default=str(root / "API_Key_Configuration.md"))
    ap.add_argument("--dest", default=str(root / ".env"))
    ap.add_argument("--force", action="store_true", help="overwrite an existing .env")
    args = ap.parse_args(argv)
    dest = Path(args.dest)
    if dest.exists() and not args.force:
        print(f"{dest.name} already exists; not overwriting (use --force).")
        return 1
    parsed = parse_key_file(Path(args.source).read_text(encoding="utf-8"))
    missing = [n for n in REQUIRED if n not in parsed]
    if missing:
        print("Missing from key file: " + ", ".join(missing))
        return 2
    dest.write_text(build_env(parsed, lambda: secrets.token_urlsafe(32)), encoding="utf-8", newline="\n")
    print("Wrote variables: " + ", ".join(ORDER))
    return 0


if __name__ == "__main__":
    sys.exit(main())
