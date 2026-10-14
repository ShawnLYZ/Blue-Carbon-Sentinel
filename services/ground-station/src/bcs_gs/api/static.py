"""Static hosting of the two web apps (addendum I5)."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

REPO_ROOT = Path(__file__).resolve().parents[5]

APPS = (
    # (mount path, dist directory, name)
    ("/console", REPO_ROOT / "apps" / "sim-console" / "dist", "Simulator Console"),
    ("/", REPO_ROOT / "apps" / "mission-control" / "dist", "Mission Control"),
)

_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{name} - not built</title>
<style>body{{font-family:system-ui,sans-serif;max-width:36rem;margin:15vh auto;padding:0 1rem;line-height:1.5}}
code{{background:#8882;padding:.15em .4em;border-radius:4px}}</style></head>
<body><h1>{name} is not built yet</h1>
<p>Build the web apps with <code>pnpm build</code> from the repository root, then reload this page.</p></body></html>"""


def mount_static(app: FastAPI) -> None:
    for mount, dist, name in APPS:
        if (dist / "index.html").is_file():
            app.mount(mount, StaticFiles(directory=dist, html=True), name=name)
            continue
        page = HTMLResponse(_PAGE.format(name=name))
        paths = ["/console", "/console/"] if mount == "/console" else ["/"]
        for path in paths:
            app.add_api_route(
                path,
                lambda page=page: page,
                methods=["GET"],
                include_in_schema=False,
                response_class=HTMLResponse,
            )
