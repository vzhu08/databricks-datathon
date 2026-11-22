"""Experimental Databricks chat-completions transport for isolated synthetic probes."""

import re

from .transport import Reply

_ENDPOINT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,62}")


class DatabricksChatProbe:
    """The server configures the endpoint, authenticated transport and shared budgets."""

    def __init__(self, *, endpoint, transport, budget, enabled=False, output_limit_field="max_tokens",
                 output_tokens=256, timeout=5):
        if type(endpoint) is not str or not _ENDPOINT.fullmatch(endpoint):
            raise ValueError("invalid endpoint name")
        if output_limit_field not in ("max_tokens", "max_completion_tokens"):
            raise ValueError("invalid token limit field")
        if endpoint in ("databricks-gpt-oss-20b", "databricks-gpt-oss-120b") and output_limit_field != "max_tokens":
            raise ValueError("unsupported GPT-OSS token limit field")
        if type(output_tokens) is not int or not 1 <= output_tokens <= 1024:
            raise ValueError("invalid output token cap")
        if type(timeout) not in (int, float) or not 0 < timeout <= 10:
            raise ValueError("invalid physical timeout")
        self._timeout = timeout
        self._path = f"/serving-endpoints/{endpoint}/invocations"
        self._transport = transport
        self._budget = budget
        self._enabled = enabled is True
        self._output_limit_field = output_limit_field
        self._output_tokens = output_tokens

    def exchange(self, instruction, synthetic_input):
        if not self._enabled:
            return Reply("unavailable")
        if not all(type(v) is str and v.strip() and len(v) <= limit
                   for v, limit in ((instruction, 1000), (synthetic_input, 6000))):
            return Reply("invalid_request")
        payload = {
            "messages": [
                {"role": "system", "content": instruction},
                {"role": "user", "content": synthetic_input},
            ],
            self._output_limit_field: self._output_tokens,
        }
        reply = self._transport.request("POST", self._path, encounter=self._budget, payload=payload,
                                        timeout=self._timeout)
        if reply.status != "received":
            return reply
        content = _assistant_text(reply.data)
        if content is None:
            return Reply("invalid_response")
        # Untrusted text. Never return a patient assessment or navigation receipt here.
        return Reply("received", {"content": content})


def _assistant_text(data):
    """Project one completed assistant text answer from a Databricks reply."""
    if type(data) is not dict:
        return None
    choices = data.get("choices")
    if type(choices) is not list or len(choices) != 1 or type(choices[0]) is not dict:
        return None
    choice = choices[0]
    message = choice.get("message")
    if (choice.get("finish_reason") != "stop" or type(message) is not dict
            or message.get("role") != "assistant" or message.get("refusal")
            or message.get("tool_calls") or message.get("function_call")):
        return None
    content = message.get("content")
    if type(content) is list:
        parts = []
        if not 1 <= len(content) <= 8:
            return None
        for block in content:
            if type(block) is not dict:
                return None
            if block.get("type") == "reasoning":
                # Only a top-level text block is an answer. Never retain reasoning.
                if set(block) - {"type", "summary", "signature", "id", "encrypted_content"}:
                    return None
                continue
            if set(block) != {"type", "text"} or block["type"] != "text" or type(block["text"]) is not str:
                return None
            if parts:
                return None
            parts.append(block["text"])
        content = "".join(parts)
    if type(content) is not str or not content.strip() or len(content) > 4096:
        return None
    return content
