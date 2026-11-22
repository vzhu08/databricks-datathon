"""Server-only assessment orchestration primitives."""

import hashlib
import hmac
import json
import secrets


class _Confirmation:
    """An opaque receipt for one reviewed result in one server encounter."""

    __slots__ = ("_tag",)

    def __init__(self, tag):
        self._tag = tag

    def __reduce__(self):
        raise TypeError("Keep assessment confirmations in the server session")


def _result_secret():
    """Generate independently for each newly committed completed result."""
    return secrets.token_hex(32)


def _confirmation_tag(secret, revision, policy_version, provider_id, provider_version):
    # The secret is unique to a result and never appears in a display record.
    binding = json.dumps([revision, policy_version, provider_id, provider_version],
                         separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return hmac.digest(bytes.fromhex(secret), binding, hashlib.sha256)


def _matches_confirmation(receipt, tag):
    return (type(receipt) is _Confirmation and type(receipt._tag) is bytes
            and hmac.compare_digest(receipt._tag, tag))
