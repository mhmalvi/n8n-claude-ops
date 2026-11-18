"""Shared fixtures: sample payloads and scripted Claude responses."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load_sample(kind: str, name: str) -> dict:
    """The ``payload`` of ``samples/<kind>s/<name>.json``."""
    return json.loads((ROOT / "samples" / f"{kind}s" / f"{name}.json").read_text())["payload"]


@pytest.fixture
def error_trigger_item() -> dict:
    """A synthetic n8n Error Trigger item."""
    return load_sample("incident", "01-invoice-auth-401")


@pytest.fixture
def alert_body() -> dict:
    """A synthetic webhook alert, wrapped the way the n8n Webhook node outputs it."""
    return {"headers": {"x-webhook-token": "redacted"}, "body": load_sample("incident", "03-checkout-down-503")}


@pytest.fixture
def lead_body() -> dict:
    """A synthetic inbound lead, wrapped like the Webhook node output."""
    return {"body": load_sample("lead", "01-hot-clinic-reminders")}


@pytest.fixture
def good_incident_json() -> str:
    """A schema-valid incident classification as Claude would return it."""
    return json.dumps({"severity": "critical", "category": "external_api", "summary": "Checkout down",
                       "probable_cause": "Upstream 503", "fix_note": "Check the upstream status page.",
                       "needs_human_now": True})


@pytest.fixture
def good_lead_json() -> str:
    """A schema-valid lead classification."""
    return json.dumps({"intent": "hot_lead", "priority": "p1", "lead_score": 87, "company": "",
                       "summary": "Wants reminders built", "reply_draft": "Thanks - Thursday works."})


@pytest.fixture
def real_error_trigger_item() -> dict:
    """An Error Trigger item captured from a real n8n 2.4.6 execution (see tests/fixtures)."""
    return json.loads((ROOT / "tests/fixtures/error-trigger-item-n8n-2.4.6.json").read_text())["item"]
