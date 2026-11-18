"""Turn raw trigger payloads into flat records and Claude request bodies.

Mirrors ``builder/js/helpers.js`` + ``normalize_*.js`` line for line; ``tests/test_js_parity.py``
runs both on the same fixtures and compares the results.
"""
from __future__ import annotations

import re
from typing import Any

from runner import spec

HTTP_STATUS = re.compile(r"\b([45]\d{2})\b", re.ASCII)


def text(value: Any) -> str:
    """Return ``value`` as a string, with ``None`` as the empty string."""
    return "" if value is None else str(value)


def fnv1a(value: str) -> str:
    """32-bit FNV-1a over UTF-16 code units, as 8 hex chars (matches JS ``charCodeAt``)."""
    data = value.encode("utf-16-le")
    digest = 0x811C9DC5
    for i in range(0, len(data), 2):
        digest ^= data[i] | (data[i + 1] << 8)
        digest = (digest * 0x01000193) & 0xFFFFFFFF
    return f"{digest:08x}"


def http_status_of(explicit: Any, message: str) -> str:
    """The HTTP status given explicitly, else the first 4xx/5xx number in the message."""
    if text(explicit):
        return text(explicit)
    match = HTTP_STATUS.search(message)
    return match.group(1) if match else ""


def from_error_trigger(raw: dict) -> dict:
    """Fields from an n8n Error Trigger item (``execution`` + ``workflow``)."""
    execution = raw.get("execution") or {}
    error = execution.get("error") or {}
    node = error.get("node") or {}
    detail = [text(error.get("description")), text((error.get("messages") or [""])[0])]
    return {
        "source": "n8n-error-trigger",
        "workflow_name": text((raw.get("workflow") or {}).get("name")),
        "execution_id": text(execution.get("id")),
        "execution_url": text(execution.get("url")),
        "failed_node": text(execution.get("lastNodeExecuted") or node.get("name")),
        "error_message": text(error.get("message"))[:1000],
        "error_detail": " | ".join(part for part in detail if part)[:500],
        "error_stack": text(error.get("stack"))[: spec.STACK_LIMIT],
        "mode": text(execution.get("mode")),
        "occurred_at": "",
        "explicit_status": text(error.get("httpCode")),
    }


def from_alert_webhook(raw: dict) -> dict:
    """Fields from a generic JSON alert POSTed to the incident webhook."""
    body = raw.get("body") if isinstance(raw.get("body"), dict) else raw
    return {
        "source": text(body.get("source") or "webhook"),
        "workflow_name": text(body.get("service") or body.get("workflow") or "unknown"),
        "execution_id": text(body.get("id")),
        "execution_url": text(body.get("url")),
        "failed_node": text(body.get("component")),
        "error_message": text(body.get("error_message") or body.get("message"))[:1000],
        "error_detail": text(body.get("detail"))[:500],
        "error_stack": text(body.get("stack"))[: spec.STACK_LIMIT],
        "mode": text(body.get("environment")),
        "occurred_at": text(body.get("occurred_at")),
        "explicit_status": text(body.get("http_status")),
    }


def render_user(fields: list[tuple[str, str]], record: dict, tail_label: str, tail: str) -> str:
    """The user message: one ``Label: value`` line per non-empty field, then a labelled tail."""
    lines = [f"{label}: {record[key]}" for label, key in fields if record[key]]
    if tail:
        lines.append(f"{tail_label}:\n{tail}")
    return "\n".join(lines)


def build_request(system: str, schema: dict, user_text: str) -> dict:
    """A Messages API request body with a JSON-schema structured output."""
    return {
        "model": spec.MODEL,
        "max_tokens": spec.MAX_TOKENS,
        "system": system,
        "messages": [{"role": "user", "content": user_text}],
        "output_config": {"effort": spec.EFFORT, "format": {"type": "json_schema", "schema": schema}},
    }


def normalize_incident(raw: dict, received_at: str) -> dict:
    """Flat incident record (with fingerprint, HTTP status and the Claude request) from either trigger."""
    is_error_trigger = isinstance(raw.get("execution"), dict) and isinstance(raw.get("workflow"), dict)
    record = from_error_trigger(raw) if is_error_trigger else from_alert_webhook(raw)
    record["http_status"] = http_status_of(record.pop("explicit_status"), record["error_message"])
    shape = re.sub(r"[0-9]", "#", record["error_message"])
    record["fingerprint"] = fnv1a(f"{record['workflow_name']}|{record['failed_node']}|{shape}")
    record["received_at"] = received_at
    user_text = render_user(spec.INCIDENT_FIELDS, record, "Stack (truncated)", record["error_stack"])
    record["claude_request"] = build_request(spec.INCIDENT_SYSTEM, spec.INCIDENT_SCHEMA, user_text)
    return record


def normalize_lead(raw: dict, received_at: str) -> dict:
    """Flat inbound-message record; only the sender's domain (not the address) goes to Claude."""
    body = raw.get("body") if isinstance(raw.get("body"), dict) else raw
    email = text(body.get("from_email")).strip().lower()
    record = {
        "channel": text(body.get("channel") or "email"),
        "from_name": text(body.get("from_name")),
        "from_email": email,
        "sender_domain": email.split("@")[-1] if "@" in email else "",
        "subject": text(body.get("subject"))[:300],
        "body": text(body.get("body") or body.get("text"))[: spec.BODY_LIMIT],
        "received_at": received_at,
    }
    user_text = render_user(spec.LEAD_FIELDS, record, "Message", record["body"])
    record["claude_request"] = build_request(spec.LEAD_SYSTEM, spec.LEAD_SCHEMA, user_text)
    return record
