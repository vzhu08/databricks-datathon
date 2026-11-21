"""Read the Datathon message board from main without checking it out."""

import argparse
from datetime import datetime
import os
from pathlib import Path
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
BOARD = "docs/implementation/OWNERSHIP.md"
REMOTE_MAIN = "refs/remotes/origin/main"
INTERVAL_SECONDS = 5 * 60


def git(*args):
    environment = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        env=environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=True,
        timeout=45,
    )
    return result.stdout


def read_board():
    git("fetch", "--quiet", "--no-tags", "--no-write-fetch-head", "--no-recurse-submodules",
        "origin", "refs/heads/main:" + REMOTE_MAIN)
    return git("show", REMOTE_MAIN + ":" + BOARD)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="check access and print the board once")
    once = parser.parse_args().once
    previous = None

    try:
        while True:
            started = time.monotonic()
            checked_at = datetime.now().astimezone().isoformat(timespec="seconds")
            try:
                current = read_board()
            except (OSError, subprocess.SubprocessError) as error:
                detail = getattr(error, "stderr", None) or str(error)
                print(f"[{checked_at}] Board check failed: {detail.strip()}",
                      file=sys.stderr, flush=True)
                if once:
                    return 1
            else:
                if current != previous:
                    print(f"[{checked_at}] Board from origin/main\n{current.rstrip()}\n",
                          flush=True)
                    previous = current
                if once:
                    return 0

            time.sleep(max(0, INTERVAL_SECONDS - (time.monotonic() - started)))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
