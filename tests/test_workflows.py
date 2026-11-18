"""Structural checks on the importable workflow JSON: types, wiring, credentials, secrets."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from builder import build_workflows as bw
from builder.nodes import spec_constants

ROOT = Path(__file__).resolve().parent.parent
FILES = sorted((ROOT / "workflows").glob("*.json"))
TRIGGERS = {"n8n-nodes-base.errorTrigger", "n8n-nodes-base.webhook"}
# Node type -> the typeVersion n8n 2.4.6 expects for the parameter shapes used here.
VERSIONS = {
    "n8n-nodes-base.errorTrigger": 1, "n8n-nodes-base.webhook": 2, "n8n-nodes-base.set": 3.4,
    "n8n-nodes-base.code": 2, "n8n-nodes-base.httpRequest": 4.2, "n8n-nodes-base.switch": 3,
    "n8n-nodes-base.telegram": 1.2, "n8n-nodes-base.slack": 2.3, "n8n-nodes-base.emailSend": 2.1,
    "n8n-nodes-base.postgres": 2.5, "n8n-nodes-base.noOp": 1,
}
SECRET_PATTERNS = [r"sk-" r"ant-", r"ghp_", r"AKIA[0-9A-Z]{12}", r"xox[bp]-", r"\b\d{8,10}:[A-Za-z0-9_-]{30,}",
                   r"\b(?:10|127|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}(?:\.\d{1,3})?\b"]
EMAIL = re.compile(r"[\w.+-]+@([\w-]+\.)+[a-z]{2,}", re.I)


def strings(value):
    """Every string anywhere inside a JSON value."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def load(path: Path) -> dict:
    """Parse one workflow file."""
    return json.loads(path.read_text())


def test_there_are_two_workflows():
    # Arrange / Act / Assert
    assert [p.name for p in FILES] == ["incident-triage.json", "lead-triage.json"]


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_node_types_and_versions_are_known(path):
    # Arrange
    nodes = load(path)["nodes"]
    # Act
    wrong = [(n["name"], n["type"], n["typeVersion"]) for n in nodes if VERSIONS.get(n["type"]) != n["typeVersion"]]
    # Assert
    assert wrong == []


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_names_and_ids_are_unique(path):
    # Arrange
    nodes = load(path)["nodes"]
    # Act
    names, ids = [n["name"] for n in nodes], [n["id"] for n in nodes]
    # Assert
    assert len(set(names)) == len(names) and len(set(ids)) == len(ids)


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_connections_point_at_real_nodes_and_nothing_is_orphaned(path):
    # Arrange
    workflow = load(path)
    names = {n["name"] for n in workflow["nodes"]}
    # Act
    targets = {link["node"] for out in workflow["connections"].values() for branch in out["main"] for link in branch}
    sources = set(workflow["connections"])
    untriggered = {n["name"] for n in workflow["nodes"] if n["type"] not in TRIGGERS} - targets
    # Assert
    assert targets <= names and sources <= names
    assert untriggered == set()
    assert {n["name"] for n in workflow["nodes"] if n["type"] in TRIGGERS} <= sources


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_switch_has_one_output_per_rule_plus_fallback(path):
    # Arrange
    workflow = load(path)
    # Act
    switches = [n for n in workflow["nodes"] if n["type"] == "n8n-nodes-base.switch"]
    # Assert
    for item in switches:
        rules = item["parameters"]["rules"]["values"]
        assert item["parameters"]["options"]["fallbackOutput"] == "extra"
        assert len(workflow["connections"][item["name"]]["main"]) == len(rules) + 1


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_credentials_are_referenced_by_name_only(path):
    # Arrange
    nodes = load(path)["nodes"]
    # Act
    refs = [ref for n in nodes for ref in n.get("credentials", {}).values()]
    # Assert
    assert refs and all(set(ref) == {"name"} and ref["name"] for ref in refs)


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_no_secrets_ips_or_real_emails_in_any_string(path):
    # Arrange
    text_values = list(strings(load(path)))
    # Act
    secret_hits = [p for p in SECRET_PATTERNS for s in text_values if re.search(p, s)]
    emails = {m.group(0) for s in text_values for m in EMAIL.finditer(s)}
    # Assert
    assert secret_hits == []
    assert all(e.endswith("@example.com") for e in emails)


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_webhooks_require_a_header_token_and_workflow_is_inactive(path):
    # Arrange
    workflow = load(path)
    # Act
    hooks = [n for n in workflow["nodes"] if n["type"] == "n8n-nodes-base.webhook"]
    # Assert
    assert workflow["active"] is False
    assert hooks and all(h["parameters"]["authentication"] == "headerAuth" for h in hooks)


def test_committed_files_match_the_builder():
    # Arrange
    expected = {"incident-triage.json": bw.incident_triage(), "lead-triage.json": bw.lead_triage()}
    # Act
    committed = {p.name: load(p) for p in FILES}
    # Assert
    assert committed == expected, "run: python -m builder.build_workflows"


def test_code_nodes_embed_the_runner_spec():
    # Arrange
    spec_json = json.dumps(spec_constants())
    # Act
    codes = [n["parameters"]["jsCode"] for p in FILES for n in load(p)["nodes"] if n["type"] == "n8n-nodes-base.code"]
    # Assert
    assert len(codes) == 4 and all(f"const SPEC = {spec_json};" in code for code in codes)


def test_demo_variant_swaps_only_notification_nodes():
    # Arrange
    production = bw.incident_triage()
    # Act
    demo = bw.demo_variant(production, "http://sink:8080")
    changed = [a["name"] for a, b in zip(production["nodes"], demo["nodes"], strict=True) if a != b]
    # Assert
    assert changed == ["Email on-call", "Page on-call (Telegram)", "Post to Slack"]
    assert demo["connections"] == production["connections"]
    assert not {n["type"] for n in demo["nodes"]} & set(bw.NOTIFY_TYPES)


def test_demo_variant_points_helpdesk_at_the_sink():
    # Arrange / Act
    demo = bw.demo_variant(bw.lead_triage(), "http://sink:8080")
    config = next(n for n in demo["nodes"] if n["name"] == "Ops config")
    urls = [r["value"] for r in config["parameters"]["assignments"]["assignments"] if r["name"] == "helpdesk_url"]
    # Assert
    assert urls == ["http://sink:8080/helpdesk/tickets"]
