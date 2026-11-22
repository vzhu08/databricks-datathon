"""Transport-neutral validation at the patient runtime boundary."""

import math


class InvalidRecord(ValueError):
    """Safe to report without disclosing a submitted value or field name."""


def _snapshot(value):
    """Detach a JSON record without invoking caller serialization hooks.

    Caps bound the work before allocating a copy. This validates transport
    shape only. Each consumer still has to check its own fields and enums.
    """
    remaining_nodes = 4096
    remaining_characters = 65536

    def copy(item, depth):
        nonlocal remaining_nodes, remaining_characters
        remaining_nodes -= 1
        if remaining_nodes < 0 or depth > 16:
            raise InvalidRecord("Record exceeds structural limits")
        kind = type(item)
        if kind is str:
            remaining_characters -= len(item)
            if remaining_characters < 0:
                raise InvalidRecord("Record exceeds text limit")
            return item
        if item is None or kind is bool:
            return item
        if kind is int and item.bit_length() <= 64:
            return item
        if kind is float and math.isfinite(item):
            return item
        if kind is list:
            return [copy(child, depth + 1) for child in item]
        if kind is dict:
            result = {}
            for key, child in item.items():
                if type(key) is not str:
                    raise InvalidRecord("Object fields must have string keys")
                result[copy(key, depth + 1)] = copy(child, depth + 1)
            return result
        raise InvalidRecord("Unsupported record value")

    if type(value) is not dict:
        raise InvalidRecord("Expected an object")
    return copy(value, 0)


POLICY_VERSION = "patient-runtime.v1"
_FAILURES = {"unsupported", "unavailable", "timeout", "rate_limited", "budget_exhausted",
             "invalid_response", "unauthorized", "unsupported_correction"}


def _text(value, limit=2048):
    return type(value) is str and 0 < len(value) <= limit and bool(value.strip())


def _provider_reply(raw, identity):
    reply = _snapshot(raw)
    base = {"state", "provider_id", "provider_version"}
    if (reply.get("provider_id"), reply.get("provider_version")) != identity:
        raise InvalidRecord("invalid_response")
    state = reply.get("state")
    if state in ("provider_unavailable", "unsupported"):
        if set(reply) - (base | {"reason"}) or reply.get("reason", "unavailable") not in _FAILURES:
            raise InvalidRecord("invalid_response")
    elif state == "awaiting_clarification":
        if (set(reply) - (base | {"question", "continuation"}) or type(reply.get("question")) is not dict
                or (reply.get("continuation") is not None and not _text(reply["continuation"], 1024))):
            raise InvalidRecord("invalid_response")
    elif state in ("completed", "urgent"):
        if set(reply) != base | {"guidance", "urgency", "uncertainty", "possible_causes", "next_step"}:
            raise InvalidRecord("invalid_response")
        if not all(_text(reply[k]) for k in ("guidance", "urgency", "uncertainty")):
            raise InvalidRecord("invalid_response")
        causes = reply["possible_causes"]
        if type(causes) is not list or len(causes) > 32 or not all(_text(x, 256) for x in causes):
            raise InvalidRecord("invalid_response")
        step = reply["next_step"]
        if step is not None and (type(step) is not dict or set(step) != {"kind", "specialty_code"}
                or step["kind"] != "consultation" or state == "urgent"
                or (step["specialty_code"] is not None and not _text(step["specialty_code"], 96))):
            raise InvalidRecord("invalid_response")
    else:
        raise InvalidRecord("invalid_response")
    return reply
