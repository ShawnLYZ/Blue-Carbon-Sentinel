"""Command line: ``bcs-sim run [--port 8701] [--gs-url ...]`` (addendum D1, D4)."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

from bcs_sim import __version__
from bcs_sim.config import REPO_ROOT

DEFAULT_PORT = 8701
DEFAULT_GS_URL = "http://127.0.0.1:8700"
HOST = "127.0.0.1"


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bcs-sim", description="Blue Carbon Sentinel Simulator")
    p.add_argument("--version", action="version", version=f"bcs-sim {__version__}")
    sub = p.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="start the Sentinel Simulator")
    run.add_argument("--port", type=int, default=DEFAULT_PORT, help="0 binds a free port and prints it")
    run.add_argument("--gs-url", default=DEFAULT_GS_URL, help="Ground Station base URL")
    run.add_argument("--env-file", type=Path, default=None, help="dotenv file (default: <repo>/.env)")
    run.add_argument("--seed", type=int, default=0, help="random seed of the simulated world")
    run.add_argument("--no-runtime", action="store_true", help="serve the API only, simulate no nodes")
    sc = sub.add_parser("scenario", help="run a scenario script headless (addendum K4)")
    sc.add_argument("file", type=Path, help="scenario YAML")
    sc.add_argument("--seed", type=int, default=None, help="random seed (default: the script's seed)")
    sc.add_argument(
        "--broker-port", type=int, default=None, help="MQTT broker port (default: BCS_BROKER_PORT)"
    )
    sc.add_argument("--gs-url", default=DEFAULT_GS_URL, help="Ground Station base URL")
    sc.add_argument("--env-file", type=Path, default=None, help="dotenv file (default: <repo>/.env)")
    sc.add_argument(
        "--realtime", action="store_true", help="run on the wall clock instead of fast-forwarding"
    )
    sc.add_argument(
        "--log", type=Path, default=None, help="run log JSON (default: var/runs/<name>-<seed>.json)"
    )
    return p


def build_run_app(args: argparse.Namespace) -> Any:
    from bcs_sim.app import create_sim_app
    from bcs_sim.config import load_sim_settings

    env_file = args.env_file if args.env_file else REPO_ROOT / ".env"
    settings = load_sim_settings(env_file if env_file.is_file() else None, gs_url=args.gs_url)
    app = create_sim_app(settings)
    app.state.runtime_supervisor = (
        None if getattr(args, "no_runtime", False) else build_supervisor(settings, getattr(args, "seed", 0))
    )
    return app


def build_supervisor(settings: Any, seed: int) -> Any:
    """The node runtime of ``bcs-sim run``: starts once the Ground Station answers, then steps every 200 ms."""
    from bcs_sim.clock import SystemClock
    from bcs_sim.config import load_sim_config
    from bcs_sim.gs_client import GsClient
    from bcs_sim.runtime import Runtime, RuntimeSupervisor

    token = settings.sim_shared_token.get_secret_value() if settings.sim_shared_token else None
    gs = GsClient(settings.gs_url, token, site_id=settings.site_id)
    cfg = load_sim_config()

    def factory() -> Runtime:
        return Runtime(
            cfg,
            gs,
            SystemClock(),
            seed,
            broker_host=settings.broker_host,
            broker_port=settings.broker_port,
            demo_time_scale=settings.demo_time_scale == "on",
        )

    return RuntimeSupervisor(factory)


async def _serve(args: argparse.Namespace) -> None:
    import uvicorn

    app = build_run_app(args)
    server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=args.port, log_level="info"))
    task = asyncio.create_task(server.serve())
    while not server.started and not task.done():
        await asyncio.sleep(0.02)
    supervisor = app.state.runtime_supervisor
    if server.started:
        port = server.servers[0].sockets[0].getsockname()[1]
        print(f"READY http://{HOST}:{port}", flush=True)
        if supervisor is not None:
            supervisor.start()
    try:
        await task
    finally:
        if supervisor is not None:
            await asyncio.to_thread(supervisor.stop)


def _fail(message: str) -> int:
    print(f"bcs-sim scenario: {message}", file=sys.stderr)
    return 1


def run_scenario(args: argparse.Namespace) -> int:
    """Run a script against the Ground Station and broker. Exit 0 when the run log has no errors, else 1."""
    import json
    from datetime import UTC, datetime

    from bcs_sim.clock import ManualClock, SystemClock
    from bcs_sim.config import load_sim_config, load_sim_settings
    from bcs_sim.gs_client import GsClient, GsError
    from bcs_sim.runner import ScriptError, load_script, run_script
    from bcs_sim.runtime import Runtime

    try:
        script = load_script(args.file.read_text(encoding="utf-8"))
    except OSError as exc:
        return _fail(f"cannot read {args.file}: {exc.strerror or exc}")
    except ScriptError as exc:
        return _fail(f"{args.file}: line {exc.line}: {exc.message}")
    seed = script.seed if args.seed is None else args.seed
    env_file = args.env_file if args.env_file else REPO_ROOT / ".env"
    settings = load_sim_settings(env_file if env_file.is_file() else None, gs_url=args.gs_url)
    port = args.broker_port or settings.broker_port
    token = settings.sim_shared_token.get_secret_value() if settings.sim_shared_token else None
    gs = GsClient(settings.gs_url, token, site_id=settings.site_id)
    clock = SystemClock() if args.realtime else ManualClock(datetime.now(UTC))
    runtime = Runtime(
        load_sim_config(),
        gs,
        clock,
        seed,
        broker_host=settings.broker_host,
        broker_port=port,
        demo_time_scale=script.demo_time_scale,
        watch_registry=False,
        connect_timeout_s=5.0,
    )
    try:
        try:
            runtime.start()
        except GsError as exc:
            return _fail(f"the Ground Station at {settings.gs_url} is not reachable: {exc}")
        down = sorted(n for n, nr in runtime.nodes.items() if not nr.link.connected)
        if not runtime.nodes:
            return _fail("the Ground Station registry has no nodes to simulate")
        if down:
            return _fail(
                f"no MQTT broker reachable at {settings.broker_host}:{port} ({', '.join(down)} not connected)"
            )
        log = run_script(script, runtime, clock, realtime=args.realtime)
    finally:
        runtime.stop()
        gs.close()
    path = args.log or REPO_ROOT / "var" / "runs" / f"{script.name}-seed{seed}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"script": script.name, "seed": seed, "realtime": args.realtime, **log.to_dict()}
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    print(
        f"{script.name}: {len(log.steps)} steps, {log.published_count} messages, "
        f"{len(log.errors)} errors, digest {log.published_digest[:16]}; log {path}"
    )
    for e in log.errors:
        print(f"  error: {e}", file=sys.stderr)
    return 1 if log.errors else 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "scenario":
        return run_scenario(args)
    if args.command == "run":
        try:
            asyncio.run(_serve(args))
        except KeyboardInterrupt:
            pass
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
