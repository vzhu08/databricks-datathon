"""Compile reviewed local CGHS extractions into unlinked identity references."""
import argparse
from pathlib import Path

from research.acquisition.common import canonical
from .collector import run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path, help="new private output directory; no uploads")
    args = parser.parse_args()
    print(canonical(run(args.manifest, args.out)).decode())


if __name__ == "__main__":
    main()
