"""CLI: export commands and ``run --port 0`` in test mode (addendum D4, O1)."""

import json
import subprocess
import sys

import httpx
from bcs_gs.cli import main


def test_export_openapi_lists_every_route(tmp_path):
    out = tmp_path / "openapi.json"
    assert main(["export-openapi", "--out", str(out)]) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert "/api/v1/system/status" in doc["paths"] and "/api/v1/test/reset" not in doc["paths"]
    assert "SystemStatus" in doc["components"]["schemas"]


def test_export_event_schemas(tmp_path):
    out = tmp_path / "events.schema.json"
    assert main(["export-event-schemas", "--out", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    assert "system.status" in text and "hello" in text and "ledger.verified" in text


def test_run_test_mode_port_zero_prints_ready_and_serves(tmp_path):
    proc = subprocess.Popen(
        [sys.executable, "-m", "bcs_gs.cli", "run", "--test-mode", "--port", "0", "--cloud", "fake",
         "--clock", "manual", "--no-camera", "--ai", "rules", "--data-dir", str(tmp_path)],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
    )  # fmt: skip
    try:
        line = proc.stdout.readline().strip()
        assert line.startswith("READY http://127.0.0.1:")
        base = line.split(" ", 1)[1]
        assert httpx.get(f"{base}/api/v1/system/status").status_code == 200
        assert httpx.post(f"{base}/api/v1/test/clock/advance", json={"seconds": 1}).status_code == 200
    finally:
        proc.terminate()
        proc.wait(timeout=15)


def _hydrate_args(tmp_path, *extra):
    # a missing env file: the developer's .env (real cloud keys) is never read by these tests
    return ["hydrate", "--env-file", str(tmp_path / "no.env"), "--data-dir", str(tmp_path), "--port", "1", *extra]


def test_hydrate_refuses_a_store_with_history_unless_forced(tmp_path, monkeypatch, capsys):
    """Final review M10: a manual hydrate only runs on a store that needs it, or with --force."""
    import bcs_gs.api.app as app_mod
    import bcs_gs.store.hydrate as hydrate_mod
    from bcs_gs.store.cloud import FakeCloudTarget

    cloud = FakeCloudTarget()
    monkeypatch.setattr(app_mod, "select_cloud", lambda _s: cloud)
    monkeypatch.setattr(hydrate_mod, "needs_hydration", lambda _repo: False)
    pulled: list[bool] = []
    real = hydrate_mod.hydrate
    monkeypatch.setattr(hydrate_mod, "hydrate", lambda *a, **kw: (pulled.append(True), real(*a, **kw))[1])
    assert main(_hydrate_args(tmp_path)) == 1
    assert "--force" in capsys.readouterr().err and not pulled
    assert main(_hydrate_args(tmp_path, "--force")) == 0
    assert pulled == [True]


def test_hydrate_refuses_while_a_ground_station_answers(tmp_path, monkeypatch, capsys):
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    import bcs_gs.api.app as app_mod
    from bcs_gs.store.cloud import FakeCloudTarget

    class Status(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *_a):
            pass

    server = HTTPServer(("127.0.0.1", 0), Status)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    cloud = FakeCloudTarget(failing=True)  # never reached: the refusal comes first
    monkeypatch.setattr(app_mod, "select_cloud", lambda _s: cloud)
    try:
        args = _hydrate_args(tmp_path, "--force")
        args[args.index("--port") + 1] = str(server.server_address[1])
        assert main(args) == 1
        assert "Ground Station is running" in capsys.readouterr().err
    finally:
        server.shutdown()
        server.server_close()
