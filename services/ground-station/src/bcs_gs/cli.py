"""Command line: ``bcs-gs run | export-openapi | export-event-schemas`` (addendum D4, O1)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_PORT = 8700
HOST = "127.0.0.1"


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bcs-gs", description="Blue Carbon Sentinel Ground Station")
    sub = p.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="start the Ground Station")
    run.add_argument("--port", type=int, default=DEFAULT_PORT, help="0 binds a free port and prints it")
    run.add_argument(
        "--env-file", type=Path, default=None, help="dotenv file (default: <repo>/.env if present)"
    )
    run.add_argument("--data-dir", type=Path, default=None, help="state root (default: the repository)")
    run.add_argument("--broker-port", type=int, default=None)
    run.add_argument(
        "--test-mode", action="store_true", help="mount the test routes and allow the flags below"
    )
    run.add_argument("--ai", choices=["rules"], default=None, help="test mode: rules tier only")
    run.add_argument("--cloud", choices=["fake"], default=None, help="test mode: in-memory cloud target")
    run.add_argument("--clock", choices=["manual"], default=None, help="test mode: clock set by test routes")
    run.add_argument("--no-camera", action="store_true", help="the camera stays offline")

    oa = sub.add_parser("export-openapi", help="write the OpenAPI document")
    oa.add_argument("--out", type=Path, default=REPO_ROOT / "packages" / "api-types" / "openapi.json")
    ev = sub.add_parser("export-event-schemas", help="write the /ws/events JSON Schema")
    ev.add_argument("--out", type=Path, default=REPO_ROOT / "packages" / "api-types" / "events.schema.json")
    bi = sub.add_parser("broker-init", help="render the Mosquitto config and bootstrap dynamic security")
    bi.add_argument("--env-file", type=Path, default=None, help="dotenv file (default: <repo>/.env)")
    bi.add_argument("--data-dir", type=Path, default=None, help="state root (default: the repository)")
    bi.add_argument("--broker-port", type=int, default=None)
    ds = sub.add_parser("devstack", help="start broker, Ground Station and simulator (foreground)")
    ds.add_argument("--test-mode", action="store_true", help="throw-away data dir, fake cloud, manual clock")
    ds.add_argument("--gs-port", type=int, default=DEFAULT_PORT, help="0 binds a free port")
    ds.add_argument("--sim-port", type=int, default=8701, help="0 binds a free port")
    ds.add_argument("--data-dir", type=Path, default=None, help="state root (test mode default: a temp dir)")
    ds.add_argument(
        "--log-dir", type=Path, default=None, help="children's stderr logs (default: <data-dir>/var/logs)"
    )
    hy = sub.add_parser("hydrate", help="pull state from the Cloud Store into the local store (H6)")
    hy.add_argument("--env-file", type=Path, default=None, help="dotenv file (default: <repo>/.env if present)")
    hy.add_argument("--data-dir", type=Path, default=None, help="state root (default: the repository)")
    hy.add_argument("--force", action="store_true", help="pull even when the local store already has history")
    hy.add_argument("--port", type=int, default=DEFAULT_PORT, help="refuse while a Ground Station answers here")
    fm = sub.add_parser("fetch-models", help="download the depth model into var/models (about 250 MB)")
    fm.add_argument("--data-dir", type=Path, default=None, help="state root (default: the repository)")
    pf = sub.add_parser("perf", help="measure a running Ground Station against the section 33 targets")
    pf.add_argument("--seconds", type=float, default=60, help="how long to watch the live surface (default 60)")
    pf.add_argument("--port", type=int, default=DEFAULT_PORT, help="Ground Station port")
    pf.add_argument("--data-dir", type=Path, default=None, help="state root (default: the repository)")
    pf.add_argument("--start-to-ready", type=float, default=None, help="seconds start.ps1 took (a sample)")
    return p


def _write_json(path: Path, doc: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


def build_run_app(args: argparse.Namespace) -> Any:
    from bcs_gs.api.app import Overrides, create_app
    from bcs_gs.core.clock import ManualClock
    from bcs_gs.core.config import load_settings
    from bcs_gs.core.logging import setup_logging
    from bcs_gs.store.cloud import FakeCloudTarget

    test_only = [f for f, v in (("--ai", args.ai), ("--cloud", args.cloud), ("--clock", args.clock)) if v]
    if not args.test_mode and test_only:
        raise SystemExit(f"{', '.join(test_only)} require --test-mode")
    env_file = args.env_file if args.env_file else REPO_ROOT / ".env"
    overrides: dict[str, object] = {}
    if args.data_dir is not None:
        overrides["data_dir"] = args.data_dir
    if args.broker_port is not None:
        overrides["broker_port"] = args.broker_port
    settings = load_settings(REPO_ROOT, env_file=env_file if env_file.is_file() else None, **overrides)
    setup_logging(settings.log_level)
    ov = Overrides(camera_enabled=not args.no_camera, test_mode=args.test_mode)
    if args.clock == "manual":
        ov.clock = ManualClock(datetime.now(UTC))
    if args.cloud == "fake":
        ov.cloud = FakeCloudTarget()
    return create_app(settings, overrides=ov)


async def _serve(args: argparse.Namespace) -> None:
    import uvicorn

    from bcs_gs.core.logging import redact_uvicorn_loggers

    app = build_run_app(args)
    config = uvicorn.Config(app, host=HOST, port=args.port, log_level="info")
    redact_uvicorn_loggers()  # uvicorn just (re)configured its loggers
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    while not server.started and not task.done():
        await asyncio.sleep(0.02)
    if server.started:
        port = server.servers[0].sockets[0].getsockname()[1]
        print(f"READY http://{HOST}:{port}", flush=True)
    await task


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "run":
        try:
            asyncio.run(_serve(args))
        except KeyboardInterrupt:
            pass
        return 0
    if args.command == "export-openapi":
        from bcs_gs.api.app import create_app
        from bcs_gs.core.config import load_settings

        _write_json(args.out, create_app(load_settings(REPO_ROOT, env_file=None)).openapi())
        return 0
    if args.command == "export-event-schemas":
        from bcs_gs.api.events import event_schema

        _write_json(args.out, event_schema())
        return 0
    if args.command == "broker-init":
        return _broker_init(args)
    if args.command == "devstack":
        from bcs_gs.devstack import run_foreground

        data_dir = args.data_dir if args.data_dir else (None if args.test_mode else REPO_ROOT)
        return run_foreground(args.gs_port, args.sim_port, data_dir, args.test_mode, args.log_dir)
    if args.command == "hydrate":
        return _hydrate(args)
    if args.command == "fetch-models":
        from bcs_gs.models_fetch import fetch_models_cli

        return fetch_models_cli(args.data_dir if args.data_dir else REPO_ROOT)
    if args.command == "perf":
        return _perf(args)
    return 2


def _perf(args: argparse.Namespace) -> int:
    from bcs_gs.status.perf import format_table, run_probe

    root = args.data_dir if args.data_dir else REPO_ROOT
    print(f"perf: watching http://{HOST}:{args.port} for {args.seconds:g} s ...", flush=True)
    report = asyncio.run(run_probe(HOST, args.port, args.seconds, root, args.start_to_ready))
    print(format_table(report))
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = root / "var" / "logs" / f"perf-{ts}.json"
    _write_json(out, report.to_dict())
    print(f"perf: wrote {out}")
    return 0 if report.ok else 1


def _gs_answers(port: int) -> bool:
    """True when something answers HTTP on the Ground Station's port (a running station owns the store)."""
    import httpx

    try:
        httpx.get(f"http://{HOST}:{port}/api/v1/system/status", timeout=2)
    except httpx.HTTPError:
        return False
    return True


def _hydrate(args: argparse.Namespace) -> int:
    from bcs_gs.api import app as app_mod
    from bcs_gs.core.clock import RealClock
    from bcs_gs.core.config import load_settings
    from bcs_gs.core.logging import register_secret, setup_logging
    from bcs_gs.store import hydrate as hydrate_mod
    from bcs_gs.store.cloud import CloudError
    from bcs_gs.store.db import Database
    from bcs_gs.store.media import MediaStore
    from bcs_gs.store.repo import Repo

    if _gs_answers(args.port):
        print(
            f"hydrate: a Ground Station is running on port {args.port}; stop it first (scripts\\stop.ps1)",
            file=sys.stderr,
        )
        return 1

    env_file = args.env_file if args.env_file else REPO_ROOT / ".env"
    overrides: dict[str, object] = {}
    if args.data_dir is not None:
        overrides["data_dir"] = args.data_dir
    settings = load_settings(REPO_ROOT, env_file=env_file if env_file.is_file() else None, **overrides)
    for secret in settings.secret_values_except_mapbox():
        register_secret(secret)
    setup_logging(settings.log_level)
    cloud = app_mod.select_cloud(settings)
    if not cloud.enabled:
        print("hydrate: the cloud is not configured (BCS_SUPABASE_URL / service role key)", file=sys.stderr)
        return 1
    root = settings.data_dir or REPO_ROOT
    clock = RealClock()
    db = Database(root / "var" / "bcs.sqlite3", clock)
    db.migrate()
    repo = Repo(db)
    try:
        if not args.force and not hydrate_mod.needs_hydration(repo):
            print(
                "hydrate: the local store already has history; nothing pulled (--force pulls anyway)",
                file=sys.stderr,
            )
            return 1
        print("hydrate: hydrating from cloud...", flush=True)
        report = hydrate_mod.hydrate(repo, MediaStore(root, db), cloud, clock)
    except CloudError as exc:
        print(f"hydrate: the cloud could not be read: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()
    for table, n in report.tables.items():
        print(f"  {table}: {n}")
    chain = {True: "intact", False: "BROKEN", None: "empty"}[report.chain_intact]
    print(f"hydrate: {sum(report.tables.values())} rows, {report.media} media objects, ledger chain {chain}")
    return 0 if report.chain_intact is not False else 1


def _broker_init(args: argparse.Namespace) -> int:
    from bcs_gs.broker import bootstrap
    from bcs_gs.core.config import load_settings

    env_file = args.env_file if args.env_file else REPO_ROOT / ".env"
    overrides: dict[str, object] = {}
    if args.data_dir is not None:
        overrides["data_dir"] = args.data_dir
    if args.broker_port is not None:
        overrides["broker_port"] = args.broker_port
    settings = load_settings(REPO_ROOT, env_file=env_file if env_file.is_file() else None, **overrides)
    if settings.broker_admin_password is None:
        print("BCS_BROKER_ADMIN_PASSWORD is not set (see .env.example)", file=sys.stderr)
        return 1
    var = (settings.data_dir or REPO_ROOT) / "var"
    bootstrap(
        var, settings.broker_admin_user, settings.broker_admin_password.get_secret_value(), settings.broker_port
    )
    print(f"broker-init: wrote {var / 'mosquitto' / 'mosquitto.conf'} and dynamic-security.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
