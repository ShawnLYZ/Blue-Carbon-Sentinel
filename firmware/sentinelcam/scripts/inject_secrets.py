# PlatformIO extra script (addendum L7). Registered twice in platformio.ini:
#   pre:  read BCS_CAMERA_TOKEN / BCS_CAMERA_OTA_PASSWORD (environment, else the repo .env) and
#         pass them to the compiler as string macros; exit 1 if either is missing.
#   post: for espota uploads only, add --auth=<password> to the uploader flags.
# Values are never printed. BCS_ENV_FILE overrides the .env path (used to test the missing-secret path).
import os
import re

Import("env")  # noqa: F821  (provided by SCons/PlatformIO)

NAMES = ("BCS_CAMERA_TOKEN", "BCS_CAMERA_OTA_PASSWORD")


def read_dotenv(path, name):
    """Last assignment of NAME wins; same dialect as scripts/dotenv.ps1."""
    if not os.path.isfile(path):
        return None
    found = None
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            t = line.strip()
            if not t or t.startswith("#"):
                continue
            if t.startswith("export "):
                t = t[7:].lstrip()
            k, sep, v = t.partition("=")
            if not sep or k.strip() != name:
                continue
            v = v.strip()
            if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
                v = re.sub(r'\\(["\\])', r"\1", v[1:-1])
            elif len(v) >= 2 and v[0] == "'" and v[-1] == "'":
                v = v[1:-1]
            else:
                i = v.find(" #")
                if i >= 0:
                    v = v[:i].rstrip()
            found = v
    return found


def env_file():
    override = os.environ.get("BCS_ENV_FILE")
    if override is not None:
        return override
    # firmware/sentinelcam -> repo root. realpath resolves the C:\bcs-fw junction.
    project = os.path.realpath(env["PROJECT_DIR"])  # noqa: F821
    return os.path.join(project, "..", "..", ".env")


def load_secrets():
    path = env_file()
    values, missing = {}, []
    for name in NAMES:
        v = os.environ.get(name) or read_dotenv(path, name)
        if v:
            values[name] = v
        else:
            missing.append(name)
    return values, missing


values, missing = load_secrets()
if missing:
    absent = ", ".join(missing)
    print(f"missing BCS_CAMERA_TOKEN/BCS_CAMERA_OTA_PASSWORD: not set in the environment or .env (absent: {absent})")
    env.Exit(1)  # noqa: F821

if "UPLOADCMD" not in env:  # noqa: F821  pre phase: the platform script has not run yet
    env.Append(CPPDEFINES=[(n, env.StringifyMacro(values[n])) for n in NAMES])  # noqa: F821
elif env.get("UPLOAD_PROTOCOL") == "espota" or env.subst("$UPLOAD_PROTOCOL") == "espota":  # noqa: F821
    secret = values["BCS_CAMERA_OTA_PASSWORD"]
    # espota --debug dumps its options, password included, so drop it before adding --auth.
    env.Replace(UPLOADERFLAGS=[f for f in env["UPLOADERFLAGS"] if f != "--debug"] + ["--auth=" + secret])  # noqa: F821
    # Keep the password out of any echoed command line (e.g. pio run -v).
    previous = env.get("PRINT_CMD_LINE_FUNC")  # noqa: F821

    def redacted(s, target, source, env_):
        s = s.replace(secret, "***")
        if previous:
            previous(s, target, source, env_)
        else:
            print(s)

    env.Replace(PRINT_CMD_LINE_FUNC=redacted)  # noqa: F821
