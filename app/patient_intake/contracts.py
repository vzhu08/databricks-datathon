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
