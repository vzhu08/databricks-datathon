"""Experimental Databricks chat-completions transport for isolated synthetic probes."""

import re

from .transport import Reply

_ENDPOINT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,62}")


class DatabricksChatProbe:
    """The server configures the endpoint, authenticated transport and shared budgets."""

    def __init__(self, *, endpoint, transport, budget, enabled=False, output_limit_field="max_tokens"):
        if type(endpoint) is not str or not _ENDPOINT.fullmatch(endpoint):
            raise ValueError("invalid endpoint name")
        if output_limit_field not in ("max_tokens", "max_completion_tokens"):
            raise ValueError("invalid token limit field")
        self._path = f"/serving-endpoints/{endpoint}/invocations"
        self._transport = transport
        self._budget = budget
        self._enabled = enabled is True
        self._output_limit_field = output_limit_field

    def exchange(self, instruction, synthetic_input):
        if not self._enabled:
            return Reply("unavailable")
        if not all(type(v) is str and v.strip() and len(v) <= limit
                   for v, limit in ((instruction, 1000), (synthetic_input, 2000))):
            return Reply("invalid_request")
        payload = {
            "messages": [
                {"role": "system", "content": instruction},
                {"role": "user", "content": synthetic_input},
            ],
            self._output_limit_field: 256,
            "stream": False,
        }
        reply = self._transport.request("POST", self._path, encounter=self._budget, payload=payload)
        if reply.status != "received":
            return reply
        choices = reply.data.get("choices")
        if type(choices) is not list or len(choices) != 1 or type(choices[0]) is not dict:
            return Reply("invalid_response")
        choice = choices[0]
        message = choice.get("message")
        if (choice.get("finish_reason") != "stop" or type(message) is not dict
                or message.get("role") != "assistant" or message.get("refusal")
                or message.get("tool_calls") or message.get("function_call")):
            return Reply("invalid_response")
        content = message.get("content")
        if type(content) is not str or not content.strip() or len(content) > 4096:
            return Reply("invalid_response")
        # Untrusted text. Never return a patient assessment or navigation receipt here.
        return Reply("received", {"content": content})
