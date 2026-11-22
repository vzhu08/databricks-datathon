"""Start the handed-off presenter on loopback with live providers disabled."""

import argparse
import ipaddress
import os
from pathlib import Path
import sys


def loopback(host):
    if host in (None, "localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def guard(event, args):
    if event == "socket.connect" and isinstance(args[1], tuple) and not loopback(args[1][0]):
        raise OSError("The local presenter allows loopback connections only")
    if event in ("socket.getaddrinfo", "socket.gethostbyname") and not loopback(args[0]):
        raise OSError("The local presenter allows loopback name lookups only")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", required=True, type=Path)
    parser.add_argument("--port", type=int, default=8501)
    args = parser.parse_args()
    assets = args.assets.resolve(strict=True)
    if not assets.is_dir():
        parser.error("--assets must be an operator asset directory")

    for name in tuple(os.environ):
        if name.startswith(("DATABRICKS_", "TOMTOM_", "PATIENT_", "MGP_")):
            os.environ.pop(name)
    os.environ.update(
        PRESENTER_ASSETS_DIR=str(assets),
        FIND_CARE_DATA="demo",
        TOMTOM_ENABLED="false",
    )
    sys.addaudithook(guard)
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

    from streamlit.web.cli import main as streamlit

    sys.argv = [
        "streamlit", "run", str(Path(__file__).with_name("presenter.py")),
        "--server.address", "127.0.0.1", "--server.port", str(args.port),
        "--server.headless", "true", "--browser.gatherUsageStats", "false",
        "--server.fileWatcherType", "none", "--global.developmentMode", "false",
    ]
    streamlit()


if __name__ == "__main__":
    main()
