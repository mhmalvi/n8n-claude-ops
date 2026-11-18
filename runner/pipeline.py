"""Run one payload through the same steps as the n8n workflow: normalize, Claude, parse, route."""
from __future__ import annotations

import time
from datetime import UTC, datetime

from runner.classify import incident_result, lead_result
from runner.claude import ClaudeClient
from runner.normalize import normalize_incident, normalize_lead

STEPS = {
    "incident": (normalize_incident, incident_result),
    "lead": (normalize_lead, lead_result),
}


def now_iso() -> str:
    """Current UTC time as an ISO-8601 string with a Z suffix."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_one(kind: str, payload: dict, client: ClaudeClient, received_at: str | None = None) -> dict:
    """Process one ``incident`` or ``lead`` payload; returns record, result, usage and latency."""
    normalize, decide = STEPS[kind]
    record = normalize(payload, received_at or now_iso())
    started = time.monotonic()
    response = client.send(record["claude_request"])
    latency_ms = int((time.monotonic() - started) * 1000)
    result = decide(record, response)
    usage = response.get("usage") or {}
    return {"record": {k: v for k, v in record.items() if k != "claude_request"}, "result": result,
            "model": response.get("model", ""), "latency_ms": latency_ms,
            "usage": {"input_tokens": usage.get("input_tokens", 0), "output_tokens": usage.get("output_tokens", 0)}}


def meets(expect: dict, result: dict) -> bool:
    """True when the result satisfies a sample's hand-written expectation (``*_in`` lists)."""
    found = {**result["classification"], "branch": result["route"]["branch"]}
    for key, allowed in expect.items():
        if found.get(key.removesuffix("_in")) not in allowed:
            return False
    return True
