"""One operator-only GPT-OSS baseline request containing a fixed invented input."""

import argparse
import json
from dataclasses import replace
from time import monotonic

from .databricks_chat import _assistant_text
from .databricks_config import _WorkspaceExchange
from .transport import Budget, Transport, _decode, _unique_dict


_ERROR_BODY_LIMIT = 4096
_CODES = {
    400: ("BAD_REQUEST", "INVALID_PARAMETER_VALUE", "INVALID_ARGUMENT"),
    401: ("UNAUTHENTICATED", "UNAUTHORIZED"),
    403: ("PERMISSION_DENIED", "FORBIDDEN"),
    404: ("NOT_FOUND", "ENDPOINT_NOT_FOUND", "RESOURCE_DOES_NOT_EXIST"),
    429: ("RESOURCE_EXHAUSTED", "TOO_MANY_REQUESTS"),
    500: ("INTERNAL_ERROR",),
    503: ("TEMPORARILY_UNAVAILABLE", "UNAVAILABLE"),
}
_REQUEST_FIELDS = ("messages", "model", "max_tokens", "stream", "reasoning_effort", "response_format")
_BASELINE = {
    "messages": [{"role": "user", "content": "Reply with the single invented label SAMPLE."}],
    "max_tokens": 256,
}
_TEST_ATTEMPT = Budget(1)


def _known_field(field):
    if type(field) is not str:
        return None
    if field in _REQUEST_FIELDS:
        return field
    if field.startswith(("messages[", "messages.")):
        # Report only the fixed field family. The remaining text is untrusted.
        return "messages"
    return None


def _error_metadata(raw, media, status):
    if media != "application/json" or not 0 < len(raw) <= _ERROR_BODY_LIMIT:
        return None, ()
    try:
        data = json.loads(raw, object_pairs_hook=_unique_dict)
    except (ValueError, RecursionError):
        return None, ()
    if type(data) is not dict:
        return None, ()
    code = data.get("error_code")
    code = code if type(code) is str and code in _CODES.get(status, ()) else None
    fields = set()
    details = data.get("details")
    if type(details) is list:
        for detail in details:
            if type(detail) is not dict or detail.get("@type") != "type.googleapis.com/google.rpc.BadRequest":
                continue
            violations = detail.get("field_violations")
            if type(violations) is list:
                for violation in violations:
                    if type(violation) is dict:
                        field = _known_field(violation.get("field"))
                        if field:
                            fields.add(field)
    return code, tuple(sorted(fields))


class _DiagnosticTransport(Transport):
    @staticmethod
    def _decode_response(status, media, raw, rate):
        if 400 <= status <= 599:
            code, fields = _error_metadata(raw, media, status)
            return replace(_decode(status, media, b"", rate), http_status=status, error_code=code, error_fields=fields)
        return replace(_decode(status, media, raw, rate), http_status=status)


def run_gpt_oss_protocol_diagnostic():
    """Send the single remaining approved diagnostic attempt and return safe metadata."""
    transport = _DiagnosticTransport(host=None, headers={}, attempts=1,
                                     exchange=_WorkspaceExchange(error_body_limit=_ERROR_BODY_LIMIT))
    start = monotonic()
    result = transport.request("POST", "/serving-endpoints/databricks-gpt-oss-20b/invocations",
                               payload=_BASELINE, encounter=_TEST_ATTEMPT, timeout=10)
    receipt = {
        "status": result.status,
        "http_status": result.http_status,
        "error_code": result.error_code,
        "error_fields": result.error_fields,
        "elapsed_seconds": round(monotonic() - start, 3),
    }
    if result.status == "received":
        receipt["assistant_text_received"] = _assistant_text(result.data) is not None
        usage = result.data.get("usage")
        if type(usage) is dict:
            receipt["usage"] = {
                key: usage[key] for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                if type(usage.get(key)) is int and 0 <= usage[key] <= 1_000_000
            }
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-one-invented-request", action="store_true", required=True)
    parser.parse_args()
    print(json.dumps(run_gpt_oss_protocol_diagnostic(), sort_keys=True))
