"""Normalization of both incident trigger shapes and inbound messages."""
from __future__ import annotations

from runner import spec
from runner.normalize import fnv1a, http_status_of, normalize_incident, normalize_lead


def test_error_trigger_item_becomes_flat_record(error_trigger_item):
    # Arrange
    received = "2026-11-18T00:00:00Z"
    # Act
    record = normalize_incident(error_trigger_item, received)
    # Assert
    assert record["source"] == "n8n-error-trigger"
    assert record["workflow_name"] == "Invoice sync (prod)"
    assert record["failed_node"] == "Create invoice"
    assert record["http_status"] == "401"
    assert record["received_at"] == received


def test_webhook_alert_uses_explicit_status_and_body(alert_body):
    # Arrange / Act
    record = normalize_incident(alert_body, "t")
    # Assert
    assert record["source"] == "uptime-monitor"
    assert record["workflow_name"] == "checkout-api"
    assert record["http_status"] == "503"
    assert record["mode"] == "production"


def test_request_body_carries_schema_and_model(error_trigger_item):
    # Arrange / Act
    request = normalize_incident(error_trigger_item, "t")["claude_request"]
    # Assert
    assert request["model"] == spec.MODEL
    assert request["output_config"]["format"]["schema"] == spec.INCIDENT_SCHEMA
    assert "Failed node: Create invoice" in request["messages"][0]["content"]


def test_fingerprint_ignores_digits_so_repeats_group(error_trigger_item):
    # Arrange
    other = {**error_trigger_item, "execution": {**error_trigger_item["execution"],
             "error": {"message": error_trigger_item["execution"]["error"]["message"].replace("401", "402")}}}
    # Act
    first = normalize_incident(error_trigger_item, "t")["fingerprint"]
    second = normalize_incident(other, "t")["fingerprint"]
    # Assert
    assert first == second and len(first) == 8


def test_stack_is_truncated():
    # Arrange
    raw = {"service": "x", "error_message": "boom", "stack": "s" * 5000}
    # Act
    record = normalize_incident(raw, "t")
    # Assert
    assert len(record["error_stack"]) == spec.STACK_LIMIT


def test_http_status_falls_back_to_message_and_ignores_other_numbers():
    # Arrange / Act / Assert
    assert http_status_of("", "upstream said 502 Bad Gateway") == "502"
    assert http_status_of("", "retry 3 of 300000 ms") == ""
    assert http_status_of(418, "whatever") == "418"


def test_fnv1a_known_vector():
    # Arrange / Act / Assert: FNV-1a 32 of "a" (one UTF-16 unit 0x61) is e40c292c
    assert fnv1a("a") == "e40c292c"


def test_lead_sends_only_sender_domain_to_claude(lead_body):
    # Arrange / Act
    record = normalize_lead(lead_body, "t")
    content = record["claude_request"]["messages"][0]["content"]
    # Assert
    assert record["sender_domain"] == "example.org"
    assert record["from_email"] not in content
    assert "Sender domain: example.org" in content


def test_lead_without_email_has_empty_domain():
    # Arrange / Act
    record = normalize_lead({"text": "hi"}, "t")
    # Assert
    assert record["sender_domain"] == "" and record["body"] == "hi" and record["channel"] == "email"


def test_real_error_trigger_item_yields_http_code_and_upstream_detail(real_error_trigger_item):
    # Arrange / Act
    record = normalize_incident(real_error_trigger_item, "t")
    # Assert
    assert record["http_status"] == "503"
    assert record["failed_node"] == "Fetch upstream orders"
    assert record["error_detail"].startswith("Service Unavailable | 503")
    assert "Detail: Service Unavailable" in record["claude_request"]["messages"][0]["content"]
