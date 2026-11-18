"""End-to-end runner behaviour with a fake Claude client, plus the CLI output helpers."""
from __future__ import annotations

import json

from runner.claude import AnthropicClient, FakeClient, text_response
from runner.cli import load_samples, markdown_table, write_outputs
from runner.pipeline import meets, run_one


def test_run_one_sends_the_built_request_and_returns_route(alert_body, good_incident_json):
    # Arrange
    client = FakeClient(lambda request: text_response(good_incident_json))
    # Act
    run = run_one("incident", alert_body, client, received_at="t")
    # Assert
    assert client.requests[0]["output_config"]["format"]["type"] == "json_schema"
    assert run["result"]["route"]["branch"] == "critical"
    assert "claude_request" not in run["record"]


def test_meets_checks_every_expectation(alert_body, good_incident_json):
    # Arrange
    run = run_one("incident", alert_body, FakeClient(lambda r: text_response(good_incident_json)), "t")
    # Act / Assert
    assert meets({"severity_in": ["critical"], "branch_in": ["critical"]}, run["result"])
    assert not meets({"category_in": ["credentials"]}, run["result"])


def test_every_sample_is_synthetic_and_has_an_expectation():
    # Arrange / Act
    samples = load_samples(__import__("runner.cli", fromlist=["ROOT"]).ROOT / "samples")
    # Assert
    assert len(samples) == 12
    assert all(s["note"].startswith("SYNTHETIC") and s["expect"] for s in samples)


def test_write_outputs_writes_json_and_markdown(tmp_path):
    # Arrange
    rows = [{"sample": "a", "expected": True}, {"sample": "b", "expected": False}]
    # Act
    write_outputs(tmp_path / "out", [{"x": 1}], rows, "note here")
    # Assert
    assert json.loads((tmp_path / "out.json").read_text())["route"] == "note here"
    assert "1/2 samples" in (tmp_path / "out.md").read_text()
    assert markdown_table(rows).splitlines()[1] == "|---|---|"


def test_model_override_replaces_model_only():
    # Arrange
    class Sdk:
        """Stands in for anthropic.Anthropic and records the create() kwargs."""

        def __init__(self):
            self.messages = self
            self.seen = {}

        def create(self, **kwargs):
            self.seen = kwargs
            return type("R", (), {"to_dict": lambda s: {"content": []}})()

    sdk = Sdk()
    # Act
    AnthropicClient(sdk_client=sdk, model_override="gateway-alias").send({"model": "m", "max_tokens": 5})
    # Assert
    assert sdk.seen == {"model": "gateway-alias", "max_tokens": 5}
