"""Validation of Claude's structured output, fallbacks and routing."""
from __future__ import annotations

import json

from runner import spec
from runner.classify import incident_result, lead_result, parse_classification
from runner.claude import text_response
from runner.normalize import normalize_incident, normalize_lead


def test_valid_incident_routes_by_severity(alert_body, good_incident_json):
    # Arrange
    record = normalize_incident(alert_body, "t")
    # Act
    result = incident_result(record, text_response(good_incident_json))
    # Assert
    assert result["classifier_ok"] is True
    assert result["route"] == {"branch": "critical", "channels": ["email", "telegram", "log"]}
    assert result["notify_text"].startswith("[CRITICAL] checkout-api: Checkout down")


def test_low_severity_goes_to_log_only(alert_body, good_incident_json):
    # Arrange
    record = normalize_incident(alert_body, "t")
    low = json.dumps({**json.loads(good_incident_json), "severity": "low"})
    # Act
    result = incident_result(record, text_response(low))
    # Assert
    assert result["route"] == {"branch": "low", "channels": ["log"]}


def test_bad_enum_falls_back_and_escalates(alert_body, good_incident_json):
    # Arrange
    record = normalize_incident(alert_body, "t")
    bad = json.dumps({**json.loads(good_incident_json), "severity": "sev0"})
    # Act
    result = incident_result(record, text_response(bad))
    # Assert
    assert result["classifier_ok"] is False
    assert result["classifier_error"] == "severity not in enum"
    assert result["route"]["branch"] == "high"


def test_api_error_and_non_json_and_truncation_all_fall_back():
    # Arrange
    cases = [({"type": "error", "error": {"status": 401}}, "api error"),
             (text_response("not json"), "output is not JSON"),
             (text_response("{}", stop_reason="max_tokens"), "stop_reason max_tokens"),
             (text_response("[1]"), "output is not an object")]
    # Act
    reasons = [parse_classification(resp, spec.INCIDENT_SCHEMA, spec.INCIDENT_FALLBACK_CLASSIFICATION)[2]
               for resp, _ in cases]
    # Assert
    assert reasons == [reason for _, reason in cases]


def test_fallback_is_a_copy_not_the_shared_constant():
    # Arrange
    found, _, _ = parse_classification({"type": "error"}, spec.LEAD_SCHEMA, spec.LEAD_FALLBACK_CLASSIFICATION)
    # Act
    found["intent"] = "spam"
    # Assert
    assert spec.LEAD_FALLBACK_CLASSIFICATION["intent"] == "other"


def test_extra_keys_are_dropped(good_lead_json):
    # Arrange
    payload = json.dumps({**json.loads(good_lead_json), "admin": True})
    # Act
    found, ok, _ = parse_classification(text_response(payload), spec.LEAD_SCHEMA, spec.LEAD_FALLBACK_CLASSIFICATION)
    # Assert
    assert ok and "admin" not in found


def test_lead_score_is_clamped_and_billing_opens_ticket(lead_body, good_lead_json):
    # Arrange
    record = normalize_lead(lead_body, "t")
    payload = json.dumps({**json.loads(good_lead_json), "intent": "billing", "lead_score": 250})
    # Act
    result = lead_result(record, text_response(payload))
    # Assert
    assert result["classification"]["lead_score"] == 100
    assert result["route"] == {"branch": "ticket", "channels": ["helpdesk", "log"]}


def test_boolean_is_not_accepted_as_integer(good_lead_json):
    # Arrange
    payload = json.dumps({**json.loads(good_lead_json), "lead_score": True})
    # Act
    _, ok, reason = parse_classification(text_response(payload), spec.LEAD_SCHEMA, spec.LEAD_FALLBACK_CLASSIFICATION)
    # Assert
    assert not ok and reason == "lead_score is not an integer"
