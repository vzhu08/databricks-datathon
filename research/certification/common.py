import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FAMILY = "nhsrc_nqas"
VERSION = "nqas-reference-1.0.0"


class SourceError(ValueError):
    pass


def require(test, reason):
    if not test:
        raise SourceError(reason)


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def identity(namespace, *parts):
    return namespace + ":" + sha(canonical(parts))


def save(path, value):
    Path(path).write_bytes(canonical(value) + b"\n")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))
