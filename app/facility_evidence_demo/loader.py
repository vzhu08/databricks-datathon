"""Load the frozen judge display edition, or say plainly why it cannot be shown.

The real display.json lives in the team's private Databricks Volume and is never committed. Its location
comes from FACILITY_EVIDENCE_DISPLAY at run time; this module pins the approved bytes by SHA-256 and checks
every key against display_schema.json. Any failure returns an "unavailable" result with a reason. There is no
fallback to other data: a synthetic file is only accepted when the caller passes its own hash (tests do), and
the page then labels it as a test file.
"""
import hashlib
import json
import os
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCHEMA = json.loads((HERE / "display_schema.json").read_text(encoding="utf-8"))
PATH_SETTING = "FACILITY_EVIDENCE_DISPLAY"
# The edition Vincent handed off on #252 (comment 7076440901) and B listed on #239 (comment 7076437052).
REAL_EDITION_SHA256 = "13c7b8736237f43e3461b96e99f58be2233be9db1f7d0154888663a917bfad99"
PINNED_SHA256 = REAL_EDITION_SHA256  # what load() accepts; only tests ever change it
MAX_BYTES = 256 * 1024
URL = re.compile(r"^https://[A-Za-z0-9.-]+\.[A-Za-z]{2,}(/[^\s<>\"']*)?$")


class Unavailable(Exception):
    """The display edition cannot be shown. The message is safe to put on screen."""


def unavailable(reason):
    return {"status": "unavailable", "reason": reason}


def read_bytes(location):
    """Bytes of the edition: a local file, or a Unity Catalog Volume path read through the Databricks SDK."""
    path = Path(location)
    if path.is_file():
        return path.read_bytes()
    if location.startswith("dbfs:/Volumes/"):
        location = location[len("dbfs:"):]
    if not location.startswith("/Volumes/"):
        raise Unavailable("The configured display file does not exist.")
    try:
        from databricks.sdk import WorkspaceClient  # only needed on Databricks
        response = WorkspaceClient().files.download(location)
        return response.contents.read(MAX_BYTES + 1)
    except Exception:  # noqa: BLE001 - any read failure is the same state for a judge
        raise Unavailable("The display file could not be read from the workspace.") from None


TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}


def is_type(value, name):
    if name == "integer":  # whole, non-negative counts; true/false is not a count
        return isinstance(value, int) and not isinstance(value, bool) and value >= 0
    return isinstance(value, TYPES[name])


def check(value, spec, where):
    """The closed JSON Schema subset display_schema.json uses: type, required, properties, items."""
    kinds = spec["type"] if isinstance(spec["type"], list) else [spec["type"]]
    if not any(is_type(value, kind) for kind in kinds):
        raise Unavailable(f"{where} is not {' or '.join(kinds)}.")
    if isinstance(value, dict):
        allowed = spec.get("properties", {})
        extra = sorted(set(value) - set(allowed))
        if extra:
            raise Unavailable(f"{where} has a field this screen is not cleared to show: {extra[0]}.")
        missing = [key for key in spec.get("required", []) if key not in value]
        if missing:
            raise Unavailable(f"{where} is missing {missing[0]}.")
        for key, item in value.items():
            check(item, allowed[key], f"{where}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            check(item, spec["items"], f"{where}[{index}]")
    elif isinstance(value, str) and not value.strip():
        raise Unavailable(f"{where} is empty.")


def is_link(text):
    return isinstance(text, str) and bool(URL.match(text))


def parse(raw, expected_sha256):
    if len(raw) > MAX_BYTES:
        raise Unavailable("The display file is larger than the approved edition.")
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise Unavailable("The display file is not the approved edition (its fingerprint does not match).")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise Unavailable("The display file is not readable JSON.") from None
    check(data, SCHEMA, "display")
    trace = data["vf_trace_case"]
    if sum(trace["same_osm_by_service"].values()) != trace["exact_shared_osm_object_keys"]:
        raise Unavailable("The trace counts by service do not add up to the total.")
    if trace["exact_shared_osm_object_keys"] > trace["campus_located_lead_keys"]:
        raise Unavailable("The trace has more matched keys than located keys.")
    if data["decision"]["point_rank"]["eligible_destinations_in_cases"] != 0:
        # This screen has no way to show a destination: scores, ranks and travel are absent by design.
        raise Unavailable("This edition lists destinations, which this walkthrough is not built to show.")
    return data


def load(environ=None, expected_sha256=None):
    """{"status": "ok", "data": ...} or {"status": "unavailable", "reason": ...}. Never raises."""
    environ = os.environ if environ is None else environ
    expected_sha256 = expected_sha256 or PINNED_SHA256
    location = (environ.get(PATH_SETTING) or "").strip()
    if not location:
        return unavailable(f"No display file is configured ({PATH_SETTING} is not set).")
    try:
        raw = read_bytes(location)
        data = parse(raw, expected_sha256)
    except Unavailable as problem:
        return unavailable(str(problem))
    except OSError:
        return unavailable("The display file could not be read.")
    # Anything other than the real edition's bytes is labelled on screen as a test file.
    return {"status": "ok", "data": data, "synthetic": hashlib.sha256(raw).hexdigest() != REAL_EDITION_SHA256}
