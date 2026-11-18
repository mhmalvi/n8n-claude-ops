"""Validate Claude's structured output, pick the route and build the notification + log row.

Mirrors ``builder/js/parse_*.js``. Anything Claude returns that fails validation is replaced by
the fallback classification from ``runner.spec`` (incidents escalate, leads go to manual review).
"""
from __future__ import annotations

import json
from typing import Any

from runner import spec


def response_text(response: dict) -> str:
    """Text of the first ``text`` content block of a Messages API response, or ``""``."""
    for block in response.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            return str(block.get("text") or "")
    return ""


def check_fields(data: Any, schema: dict) -> str:
    """Return ``""`` when ``data`` satisfies the flat schema, else the first problem found."""
    if not isinstance(data, dict):
        return "output is not an object"
    for key in schema["required"]:
        rule = schema["properties"][key]
        value = data.get(key)
        if value is None:
            return f"missing {key}"
        if rule["type"] == "string" and not isinstance(value, str):
            return f"{key} is not a string"
        if rule["type"] == "boolean" and not isinstance(value, bool):
            return f"{key} is not a boolean"
        if rule["type"] == "integer" and (isinstance(value, bool) or not isinstance(value, int)):
            return f"{key} is not an integer"
        if "enum" in rule and value not in rule["enum"]:
            return f"{key} not in enum"
    return ""


def parse_classification(response: dict, schema: dict, fallback: dict) -> tuple[dict, bool, str]:
    """(classification, ok, reason) from a raw API response; the fallback when anything is off."""
    if response.get("type") == "error" or response.get("error"):
        return dict(fallback), False, "api error"
    if response.get("stop_reason") not in ("end_turn", None):
        return dict(fallback), False, f"stop_reason {response.get('stop_reason')}"
    try:
        data = json.loads(response_text(response))
    except ValueError:
        return dict(fallback), False, "output is not JSON"
    problem = check_fields(data, schema)
    if problem:
        return dict(fallback), False, problem
    return {key: data[key] for key in schema["required"]}, True, ""


def incident_result(record: dict, response: dict) -> dict:
    """Classification, route, notification text and log row for one incident."""
    found, ok, reason = parse_classification(response, spec.INCIDENT_SCHEMA, spec.INCIDENT_FALLBACK_CLASSIFICATION)
    branch = spec.INCIDENT_BRANCHES.get(found["severity"], spec.INCIDENT_FALLBACK)
    where = record["execution_url"] or record["execution_id"] or "n/a"
    notify = (f"[{found['severity'].upper()}] {record['workflow_name']}: {found['summary']}\n"
              f"Cause: {found['probable_cause']}\nFix: {found['fix_note']}\nExecution: {where}")
    log_row = {
        "fingerprint": record["fingerprint"], "source": record["source"],
        "workflow_name": record["workflow_name"], "failed_node": record["failed_node"],
        "severity": found["severity"], "category": found["category"], "summary": found["summary"],
        "fix_note": found["fix_note"], "classifier_ok": ok, "received_at": record["received_at"],
    }
    route = {"branch": branch, "channels": spec.INCIDENT_CHANNELS[branch]}
    return {"classification": found, "classifier_ok": ok, "classifier_error": reason,
            "route": route, "notify_text": notify, "log_row": log_row}


def lead_result(record: dict, response: dict) -> dict:
    """Classification, route, alert text and log row for one inbound message."""
    found, ok, reason = parse_classification(response, spec.LEAD_SCHEMA, spec.LEAD_FALLBACK_CLASSIFICATION)
    found["lead_score"] = max(0, min(100, found["lead_score"]))
    branch = spec.LEAD_BRANCHES.get(found["intent"], spec.LEAD_FALLBACK)
    notify = (f"[{found['intent']} {found['priority']} score {found['lead_score']}] "
              f"{record['from_name']} ({record['sender_domain'] or 'unknown domain'}): {found['summary']}")
    log_row = {
        "from_email": record["from_email"], "channel": record["channel"], "subject": record["subject"],
        "intent": found["intent"], "priority": found["priority"], "lead_score": found["lead_score"],
        "summary": found["summary"], "classifier_ok": ok, "received_at": record["received_at"],
    }
    route = {"branch": branch, "channels": spec.LEAD_CHANNELS[branch]}
    return {"classification": found, "classifier_ok": ok, "classifier_error": reason,
            "route": route, "notify_text": notify, "log_row": log_row}
