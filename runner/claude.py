"""Claude clients for the local runner: the real API and a scripted fake for offline tests.

Both take the exact request body the n8n HTTP Request node sends and return the raw response
JSON, so the parsing code downstream is identical for n8n and for the runner.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Protocol


class ClaudeClient(Protocol):
    """Anything that turns a Messages API request body into a response dict."""

    def send(self, request: dict) -> dict:
        """Send one request body and return the raw response JSON as a dict."""
        ...


class AnthropicClient:
    """Live client on the official SDK; the key comes from ``ANTHROPIC_API_KEY`` in the env."""

    def __init__(self, sdk_client: object | None = None, model_override: str = "") -> None:
        """Create the SDK client (honours ``ANTHROPIC_BASE_URL``); optionally force another model id.

        ``model_override`` exists for Anthropic-compatible gateways (e.g. a LiteLLM proxy) that
        expose Claude under their own alias; the request body is otherwise sent unchanged.
        """
        if sdk_client is None:
            import anthropic

            sdk_client = anthropic.Anthropic(max_retries=3)
        self._sdk = sdk_client
        self.model_override = model_override

    def send(self, request: dict) -> dict:
        """Call ``messages.create``; API failures come back as an error dict, like n8n's neverError."""
        import anthropic

        try:
            body = {**request, "model": self.model_override} if self.model_override else request
            return self._sdk.messages.create(**body).to_dict()
        except anthropic.APIStatusError as exc:
            return {"type": "error", "error": {"status": exc.status_code, "message": str(exc.message)[:300]}}
        except anthropic.APIConnectionError:
            return {"type": "error", "error": {"status": 0, "message": "connection error"}}


class FakeClient:
    """Offline client: answers each request with ``responder(request)`` and records the requests."""

    def __init__(self, responder: Callable[[dict], dict]) -> None:
        """Keep the responder and an empty request log."""
        self.responder = responder
        self.requests: list[dict] = []

    def send(self, request: dict) -> dict:
        """Record the request and return the scripted response."""
        self.requests.append(request)
        return self.responder(request)


def text_response(payload: str, stop_reason: str = "end_turn") -> dict:
    """A minimal Messages API response whose only text block is ``payload``."""
    return {"type": "message", "stop_reason": stop_reason, "content": [{"type": "text", "text": payload}],
            "usage": {"input_tokens": 0, "output_tokens": 0}}
