"""Run acceptance probes with only the Databricks Apps source tree."""

import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory


APP = Path(__file__).resolve().parents[2] / "app"

# Keep enough process settings to run Python and Streamlit, without inheriting
# warehouse/provider credentials, proxy configuration, or PYTHONPATH.
_PROCESS_SETTINGS = ("PATH", "SYSTEMROOT", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR")
_BASE_SETTINGS = {
    "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false",
    "STREAMLIT_SERVER_HEADLESS": "true",
}
_ENTRY = """\
from pathlib import Path
import sys
sys.path.insert(0, str(Path.cwd()))
"""
_OFFLINE = """\
socket_attempts = []
network_events = {
    "socket.connect", "socket.sendto", "socket.sendmsg", "socket.getaddrinfo",
    "socket.getnameinfo", "socket.gethostbyname", "socket.gethostbyaddr",
}

def offline_only(event, args):
    if event in network_events:
        socket_attempts.append(event)
        raise AssertionError("Outbound network is forbidden during the app-only probe")

sys.addaudithook(offline_only)
try:
    exec(compile(sys.argv[1], "<app-only probe>", "exec"), {})
finally:
    if socket_attempts:
        raise AssertionError(f"Unexpected socket events: {socket_attempts}")
"""


@contextmanager
def staged_app():
    """Keep the checkout's root, contracts and tests outside the staged source."""
    with TemporaryDirectory(prefix="patient-intake-app-") as folder:
        yield shutil.copytree(APP, Path(folder) / "source",
                              ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))


def offline_probe(source, script, *, settings=None, timeout=30):
    """Run Python in the staged app, with isolated imports and no network calls."""
    env = {name: os.environ[name] for name in _PROCESS_SETTINGS if name in os.environ}
    env.update(_BASE_SETTINGS)
    env.update(settings or {})
    return subprocess.run(
        [sys.executable, "-I", "-B", "-c", _ENTRY + _OFFLINE, script],
        cwd=source, env=env, capture_output=True, text=True, timeout=timeout,
    )
