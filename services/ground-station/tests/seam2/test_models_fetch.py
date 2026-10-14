"""Model download: once only, flat layout, checksums recorded (task 13)."""

from bcs_gs.models_fetch import fetch_models
from bcs_gs.models_paths import DEPTH_MODEL_DIR_NAME, DEPTH_MODEL_FILES


def test_fetch_models_downloads_once_and_records_checksums(tmp_path):
    calls = []

    def fake_download(url, path):
        calls.append(url)
        path.write_bytes(b"x")

    fetch_models(tmp_path, fake_download)
    paths = fetch_models(tmp_path, fake_download)
    assert len(calls) == 4 and all("depth-anything-v2-small-ONNX/resolve/main/onnx/" in u for u in calls)
    assert (tmp_path / "depth-anything-v2-small" / "SHA256SUMS").read_text().count("model") == 4
    assert {p.name for p in paths} >= set(DEPTH_MODEL_FILES)
    assert all(p.parent.name == DEPTH_MODEL_DIR_NAME and p.is_file() for p in paths)
    assert not list((tmp_path / DEPTH_MODEL_DIR_NAME).glob("*.part"))
