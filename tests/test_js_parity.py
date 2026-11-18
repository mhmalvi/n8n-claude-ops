"""Run the generated n8n Code nodes under Node.js and compare them with the Python runner.

Skipped when no ``node`` binary is available (set NODE_BIN to point at one).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from runner.classify import incident_result, lead_result
from runner.claude import text_response
from runner.normalize import normalize_incident, normalize_lead

ROOT = Path(__file__).resolve().parent.parent
NODE = os.environ.get("NODE_BIN") or shutil.which("node")
pytestmark = pytest.mark.skipif(not NODE, reason="node not installed")
HARNESS = """
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const $input = { all: () => input.items.map((json) => ({ json })) };
const $ = (name) => ({ all: () => (input.named[name] || []).map((json) => ({ json })) });
const out = (function () {
%s
})();
process.stdout.write(JSON.stringify(out.map((item) => item.json)));
"""


def code_of(workflow: str, node_name: str) -> str:
    """jsCode of one node in a committed workflow file."""
    data = json.loads((ROOT / "workflows" / workflow).read_text())
    return next(n for n in data["nodes"] if n["name"] == node_name)["parameters"]["jsCode"]


def run_js(code: str, items: list[dict], named: dict | None = None) -> list[dict]:
    """Execute a Code node body the way n8n's runOnceForAllItems mode does."""
    payload = json.dumps({"items": items, "named": named or {}})
    done = subprocess.run([NODE, "-e", HARNESS % code], input=payload, capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout)


def without_time(record: dict) -> dict:
    """Drop the wall-clock field that legitimately differs between the two runs."""
    return {k: v for k, v in record.items() if k != "received_at"}


@pytest.mark.parametrize("fixture", ["error_trigger_item", "alert_body", "real_error_trigger_item"])
def test_incident_normalize_matches_python(fixture, request):
    # Arrange
    raw = request.getfixturevalue(fixture)
    # Act
    js = run_js(code_of("incident-triage.json", "Normalize + enrich"), [raw])[0]
    # Assert
    assert without_time(js) == without_time(normalize_incident(raw, "t"))


def test_lead_normalize_matches_python(lead_body):
    # Arrange / Act
    js = run_js(code_of("lead-triage.json", "Normalize message"), [lead_body])[0]
    # Assert
    assert without_time(js) == without_time(normalize_lead(lead_body, "t"))


@pytest.mark.parametrize("payload", ["good", "not json", "bad enum"])
def test_incident_parse_matches_python(alert_body, good_incident_json, payload):
    # Arrange
    body = {"good": good_incident_json, "not json": "nope",
            "bad enum": good_incident_json.replace("critical", "sev0")}[payload]
    record = normalize_incident(alert_body, "t")
    # Act
    js = run_js(code_of("incident-triage.json", "Parse + validate"), [text_response(body)],
                {"Normalize + enrich": [record]})[0]
    expected = incident_result(record, text_response(body))
    # Assert
    assert {k: js[k] for k in expected} == expected


def test_lead_parse_matches_python(lead_body, good_lead_json):
    # Arrange
    record = normalize_lead(lead_body, "t")
    response = text_response(good_lead_json.replace("87", "250"))
    # Act
    js = run_js(code_of("lead-triage.json", "Parse + validate"), [response], {"Normalize message": [record]})[0]
    expected = lead_result(record, response)
    # Assert
    assert {k: js[k] for k in expected} == expected
