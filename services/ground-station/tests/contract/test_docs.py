"""Task 6 (M7): the documentation set covers the sections design 35 requires and leaks no secret values."""
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[4]


def test_docs_cover_required_sections():
    req = {"README.md": ["Requirements", "Setup", "Start", "Troubleshooting"],
           "docs/swap-guide.md": ["Real Sentinel Nodes", "Trained models", "Sentinel-2"],
           "docs/runbook.md": ["2.4 GHz", "high-performance GPU", "Demo Director", "Key rotation"],
           "docs/methodology.md": ["NDVI-proxy", "VM0033", "Donato", "buffer"]}
    for path, heads in req.items():
        text = (ROOT / path).read_text(encoding="utf-8")
        for h in heads:
            assert h in text, (path, h)


def test_no_secret_values_in_docs():
    env_file = ROOT / ".env"
    env = dotenv_values(env_file) if env_file.exists() else {}
    # Only secret-class variables: BCS_CAMERA_HOST and BCS_SUPABASE_URL are public identifiers that the
    # docs legitimately name (mDNS host, project URL), so they are not secret values.
    env = {k: v for k, v in env.items() if any(w in k for w in ("KEY", "TOKEN", "PASSWORD", "SECRET"))}
    for p in (ROOT / "docs").rglob("*.md"):
        t = p.read_text(encoding="utf-8")
        for v in env.values():
            if v and len(v) > 12:
                assert v not in t, p
