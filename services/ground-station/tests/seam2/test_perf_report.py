from bcs_gs.status.perf import PerfSamples, perf_report


def test_perf_report_flags_targets():
    r = perf_report(PerfSamples(live_fps=[9, 8, 10], latency_ms=[300, 420], capture_s=[1.1], telemetry_to_ui_s=[0.4], ack_s=[1.2],
                                ai_s=[3.0, 9.0], sync_lag_s=[1.0], start_to_ready_s=[48]))
    assert all(row.ok for row in r.rows)
    r2 = perf_report(PerfSamples(live_fps=[4], latency_ms=[700], capture_s=[1.1], telemetry_to_ui_s=[0.4], ack_s=[1.2], ai_s=[3], sync_lag_s=[1], start_to_ready_s=[48]))
    assert {row.metric for row in r2.rows if not row.ok} == {"live_fps", "frame_to_screen_ms"}


def test_metrics_without_samples_are_listed_not_failed():
    r = perf_report(PerfSamples(live_fps=[9]))
    assert [row.metric for row in r.rows] == ["live_fps"]
    assert r.ok
    assert "frame_to_screen_ms" in r.no_samples and "flux_s" in r.no_samples


def test_optional_lists_are_judged_with_their_targets():
    r = perf_report(PerfSamples(flux_s=[75.0], forecast_cached_s=[0.4], forecast_fresh_s=[12.0], render_fps=[45.0], change_capture_s=[4.0]))
    assert {row.metric for row in r.rows if not row.ok} == {"flux_s"}
    assert not r.ok


def test_collect_store_reads_fresh_forecast_elapsed_and_notes_missing_tables(tmp_path, capsys):
    import json
    import sqlite3
    from datetime import UTC, datetime

    from bcs_gs.status.perf import collect_store
    from bcs_protocol.timefmt import to_iso

    now = datetime.now(UTC)
    db = tmp_path / "var" / "bcs.sqlite3"
    db.parent.mkdir()
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE forecasts (id TEXT, created_at TEXT, status TEXT, summary TEXT)")
    con.execute("INSERT INTO forecasts VALUES ('a', ?, 'ready', ?)", (to_iso(now), json.dumps({"elapsed_ms": 12500.0})))
    con.execute("INSERT INTO forecasts VALUES ('b', ?, 'ready', ?)", (to_iso(now), json.dumps({"years": 5})))
    con.commit()
    con.close()
    samples = PerfSamples()
    collect_store(db, now, samples)
    assert samples.forecast_fresh_s == [12.5]
    assert "perf: telemetry not read" in capsys.readouterr().err  # missing tables are noted, not silent


def _status(state, queue, lag_s, failures):
    return {
        "sync": {"state": state, "queue": queue, "media_queue": 0, "lag_s": lag_s, "last_success_at": None},
        "components": [{"id": "sync", "status": "ok", "summary": "", "details": {"queue": queue, "failures": failures}}],
    }


def test_sync_lag_is_sampled_whenever_no_pass_has_failed():
    """Final review M8: lag_s is only set while rows wait (state "buffering"), so requiring "online" never
    sampled. Buffering without failures is healthy; an empty queue is zero lag; a failing cloud is not sampled."""
    from bcs_gs.status.perf import sync_lag_sample

    assert sync_lag_sample(_status("buffering", 3, 0.8, 0)) == 0.8
    assert sync_lag_sample(_status("online", 0, None, 0)) == 0.0
    assert sync_lag_sample(_status("buffering", 3, 5.0, 1)) is None
    assert sync_lag_sample(_status("offline", 3, 30.0, 3)) is None
