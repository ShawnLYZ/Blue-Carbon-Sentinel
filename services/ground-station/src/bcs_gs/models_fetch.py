"""Download the depth model from Hugging Face (addendum D, task 13).

Files are saved flat under ``<dest>/depth-anything-v2-small/`` (the repository keeps them under
``onnx/``; the local names drop that prefix, matching ``models_paths``).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

from bcs_gs.models_paths import DEPTH_MODEL_DIR_NAME, DEPTH_MODEL_FILES

HF_BASE = "https://huggingface.co/onnx-community/depth-anything-v2-small-ONNX/resolve/main/onnx"
MODEL_FILES: tuple[str, ...] = (
    *DEPTH_MODEL_FILES,
    *(f"{name}_data" for name in DEPTH_MODEL_FILES),
)
CHUNK = 1024 * 1024

Downloader = Callable[[str, Path], None]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def fetch_models(dest: Path, download: Downloader) -> list[Path]:
    """Fetch any missing model file into ``dest/depth-anything-v2-small``; return all four paths.

    A file is downloaded to ``<name>.part`` and renamed, so an interrupted run never leaves a
    truncated model that later runs would skip. ``SHA256SUMS`` is written after the first
    download (and whenever it is missing).
    """
    out_dir = dest / DEPTH_MODEL_DIR_NAME
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    downloaded = False
    for name in MODEL_FILES:
        target = out_dir / name
        paths.append(target)
        if target.is_file():
            continue
        part = out_dir / f"{name}.part"
        download(f"{HF_BASE}/{name}", part)
        part.replace(target)
        downloaded = True
    sums = out_dir / "SHA256SUMS"
    if downloaded or not sums.is_file():
        lines = [f"{_sha256(p)}  {p.name}\n" for p in paths]
        sums.write_text("".join(lines), encoding="utf-8", newline="\n")
    return paths


def http_download(url: str, path: Path) -> None:
    """Stream ``url`` to ``path`` (follows Hugging Face redirects)."""
    import httpx

    with httpx.stream("GET", url, follow_redirects=True, timeout=httpx.Timeout(30, read=120)) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        done = 0
        last = -1
        with path.open("wb") as fh:
            for chunk in r.iter_bytes(CHUNK):
                fh.write(chunk)
                done += len(chunk)
                pct = int(done * 100 / total) // 10 * 10 if total else -1
                if pct != last and pct >= 0:
                    last = pct
                    print(f"  {path.name.removesuffix('.part')}: {pct}%", flush=True)


def fetch_models_cli(data_dir: Path) -> int:
    dest = data_dir / "var" / "models"
    paths = fetch_models(dest, http_download)
    print(f"models ready in {dest / DEPTH_MODEL_DIR_NAME} ({len(paths)} files)")
    return 0
