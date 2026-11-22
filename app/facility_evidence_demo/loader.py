"""Load the frozen judge display edition, or say plainly why it cannot be shown.

The real display.json lives in the team's private Databricks Volume and is never committed. Its location
comes from FACILITY_EVIDENCE_DISPLAY at run time; this module pins the approved bytes by SHA-256 and checks
every key against display_schema.json. Any failure returns an "unavailable" result with a reason. There is no
fallback to other data: a synthetic file is only accepted when the caller passes its own hash (tests do).
"""
import hashlib
import json
import os
import re
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCHEMA = json.loads((HERE / "display_schema.json").read_text(encoding="utf-8"))
PATH_SETTING = "FACILITY_EVIDENCE_DISPLAY"
# The edition Vincent handed off on #252 (comment 7076440901) and B listed on #239 (comment 7076437052).
PINNED_SHA256 = "13c7b8736237f43e3461b96e99f58be2233be9db1f7d0154888663a917bfad99"
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


def check(value, spec, where):
    kind = spec["type"]
    if kind == "object":
        if not isinstance(value, dict):
            raise Unavailable(f"{where} is not an object.")
        allowed = spec["properties"]
        extra = sorted(set(value) - set(allowed))
        if extra:
            raise Unavailable(f"{where} has a field this screen is not cleared to show: {extra[0]}.")
        missing = [key for key in spec.get("required", []) if key not in value]
        if missing:
            raise Unavailable(f"{where} is missing {missing[0]}.")
        for key, item in value.items():
            check(item, allowed[key], f"{where}.{key}")
    elif kind == "list":
        if not isinstance(value, list):
            raise Unavailable(f"{where} is not a list.")
        for index, item in enumerate(value):
            check(item, spec["items"], f"{where}[{index}]")
    elif kind == "count":
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise Unavailable(f"{where} is not a whole count.")
    elif kind == "count_map":
        if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, int)
                                                  and not isinstance(v, bool) and v >= 0 for k, v in value.items()):
            raise Unavailable(f"{where} is not a set of named counts.")
    elif kind == "date":
        try:
            date.fromisoformat(value)
        except (TypeError, ValueError):
            raise Unavailable(f"{where} is not a date.") from None
    elif kind == "url":
        if not isinstance(value, str) or not URL.match(value):
            raise Unavailable(f"{where} is not a public https link.")
    elif kind == "string":
        if not isinstance(value, str) or not value.strip():
            raise Unavailable(f"{where} is empty.")
    elif kind == "boolean":
        if not isinstance(value, bool):
            raise Unavailable(f"{where} is not true or false.")
    else:  # a schema mistake is still a refusal, never a pass
        raise Unavailable(f"{where} has an unknown type.")


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
    trace = data["vf_trace"]
    if sum(trace["same_object_by_service"].values()) != trace["same_object_keys"]:
        raise Unavailable("The trace counts by service do not add up to the total.")
    if data["result"]["eligible_destinations"] != 0:
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
        data = parse(read_bytes(location), expected_sha256)
    except Unavailable as problem:
        return unavailable(str(problem))
    except OSError:
        return unavailable("The display file could not be read.")
    return {"status": "ok", "data": data, "synthetic": bool(data.get("synthetic"))}
