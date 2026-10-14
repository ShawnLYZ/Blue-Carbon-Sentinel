import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "scripts"))

from migrate_keys import build_env, parse_key_file

FAKE = """# Gemini API Key\n\n1. AQ.fake1\n2. AQ.fake2\n3. AQ.fake3\n\n# Supabase Configuration\n\nAnon API Key: anon.fake\n\nProject URL: https://abc.supabase.co/rest/v1/\n\nSupabase personal access token: sbp_fake\n\nDatabase Password: pw fake\n\nSUPABASE_SERVICE_ROLE_KEY: srk.fake\n\n# Nvidia Builder API Key - Generate AI Image only\n\nnvapi-fake\n\n(model: NVIDIA FLUX.2 Klein)\n\n# Mapbox GL JS Access Token\n\npk.fake\n"""


def test_parse_key_file_maps_every_secret():
    p = parse_key_file(FAKE)
    assert p["BCS_GEMINI_API_KEY_1"] == "AQ.fake1" and p["BCS_GEMINI_API_KEY_3"] == "AQ.fake3"
    assert p["BCS_SUPABASE_URL"] == "https://abc.supabase.co"  # /rest/v1/ stripped
    assert p["SUPABASE_ACCESS_TOKEN"] == "sbp_fake"
    assert p["SUPABASE_DB_PASSWORD"] == "pw fake"
    assert p["BCS_SUPABASE_SERVICE_ROLE_KEY"] == "srk.fake"
    assert p["BCS_SUPABASE_ANON_KEY"] == "anon.fake"
    assert p["BCS_NVIDIA_API_KEY"] == "nvapi-fake"
    assert p["BCS_MAPBOX_PUBLIC_TOKEN"] == "pk.fake"


def test_build_env_generates_local_secrets_and_quotes_values():
    env = build_env(parse_key_file(FAKE), generate=lambda: "GEN")
    for name in ["BCS_BROKER_ADMIN_PASSWORD", "BCS_GS_MQTT_PASSWORD", "BCS_SIM_SHARED_TOKEN",
                 "BCS_CAMERA_TOKEN", "BCS_CAMERA_OTA_PASSWORD"]:
        assert f'{name}="GEN"' in env
    assert 'SUPABASE_DB_PASSWORD="pw fake"' in env
    assert 'BCS_BROKER_ADMIN_USER="admin"' in env and 'BCS_DEMO_TIME_SCALE="on"' in env
