"""Generate the importable n8n workflow JSON files from ``runner/spec.py`` + ``builder/js``.

    python -m builder.build_workflows          # rewrites workflows/*.json and demo/*.json

``demo_variant()`` makes the clearly labelled test copy used in the throwaway-n8n demo: only the
Telegram / Slack / Email nodes (and the helpdesk URL) are pointed at a local HTTP sink.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from builder.nodes import claude_call, code_node, node, ops_config, postgres_query, switch, webhook

ROOT = Path(__file__).resolve().parent.parent
PARSED = "$('Parse + validate').item.json"
CONFIG = "$('Ops config').first().json"
NOTIFY_TYPES = {"n8n-nodes-base.telegram": "telegram", "n8n-nodes-base.slack": "slack",
                "n8n-nodes-base.emailSend": "email"}

INCIDENT_LOG_SQL = (
    "INSERT INTO ops_incidents (fingerprint, source, workflow_name, failed_node, severity, category, "
    "summary, fix_note, classifier_ok, received_at) SELECT r->>'fingerprint', r->>'source', "
    "r->>'workflow_name', r->>'failed_node', r->>'severity', r->>'category', r->>'summary', "
    "r->>'fix_note', (r->>'classifier_ok')::boolean, (r->>'received_at')::timestamptz "
    "FROM (SELECT $1::jsonb AS r) AS input RETURNING id;"
)
CRM_UPSERT_SQL = (
    "INSERT INTO crm_leads (email, name, company, intent, priority, lead_score, last_summary, reply_draft) "
    "SELECT r->>'email', r->>'name', r->>'company', r->>'intent', r->>'priority', (r->>'lead_score')::int, "
    "r->>'summary', r->>'reply_draft' FROM (SELECT $1::jsonb AS r) AS input "
    "ON CONFLICT (email) DO UPDATE SET intent = EXCLUDED.intent, priority = EXCLUDED.priority, "
    "lead_score = EXCLUDED.lead_score, last_summary = EXCLUDED.last_summary, "
    "reply_draft = EXCLUDED.reply_draft, updated_at = now() RETURNING id;"
)
TRIAGE_LOG_SQL = (
    "INSERT INTO inbox_triage_log (from_email, channel, subject, intent, priority, lead_score, summary, "
    "classifier_ok, received_at) SELECT r->>'from_email', r->>'channel', r->>'subject', r->>'intent', "
    "r->>'priority', (r->>'lead_score')::int, r->>'summary', (r->>'classifier_ok')::boolean, "
    "(r->>'received_at')::timestamptz FROM (SELECT $1::jsonb AS r) AS input RETURNING id;"
)


def telegram(name: str, position: tuple[int, int]) -> dict:
    """Telegram sendMessage to the chat id from Ops config (credential ``Ops Telegram Bot``)."""
    params = {"chatId": "={{ " + CONFIG + ".telegram_chat_id }}", "text": "={{ " + PARSED + ".notify_text }}",
              "additionalFields": {"appendAttribution": False}}
    return node(name, "telegram", 1.2, position, params, {"telegramApi": "Ops Telegram Bot"})


def slack(name: str, position: tuple[int, int]) -> dict:
    """Slack message to the channel from Ops config (credential ``Ops Slack``)."""
    params = {"select": "channel",
              "channelId": {"__rl": True, "value": "={{ " + CONFIG + ".slack_channel }}", "mode": "name"},
              "text": "={{ " + PARSED + ".notify_text }}", "otherOptions": {}}
    return node(name, "slack", 2.3, position, params, {"slackApi": "Ops Slack"})


def email(name: str, position: tuple[int, int]) -> dict:
    """Plain-text email to the on-call address from Ops config (credential ``Ops SMTP``)."""
    params = {"fromEmail": "={{ " + CONFIG + ".email_from }}", "toEmail": "={{ " + CONFIG + ".email_to }}",
              "subject": "={{ '[' + " + PARSED + ".classification.severity.toUpperCase() + '] ' + "
                         + PARSED + ".workflow_name }}",
              "emailFormat": "text", "text": "={{ " + PARSED + ".notify_text }}", "options": {}}
    return node(name, "emailSend", 2.1, position, params, {"smtp": "Ops SMTP"})


def connect(pairs: list[tuple[str, str, int]]) -> dict:
    """n8n ``connections`` from (source, target, source output index) triples."""
    out: dict = {}
    for source, target, index in pairs:
        outputs = out.setdefault(source, {"main": []})["main"]
        while len(outputs) <= index:
            outputs.append([])
        outputs[index].append({"node": target, "type": "main", "index": 0})
    return out


def workflow(name: str, nodes: list[dict], pairs: list[tuple[str, str, int]]) -> dict:
    """A complete importable workflow (inactive, v1 execution order)."""
    return {"name": name, "nodes": nodes, "connections": connect(pairs), "active": False,
            "settings": {"executionOrder": "v1", "saveManualExecutions": True}, "pinData": {}}


def incident_triage() -> dict:
    """Error Trigger / alert webhook -> enrich -> Claude -> validate -> route -> notify -> log."""
    config = {"telegram_chat_id": "REPLACE_WITH_OPS_CHAT_ID", "slack_channel": "#ops-incidents",
              "email_to": "oncall@example.com", "email_from": "n8n-alerts@example.com"}
    nodes = [
        node("Error Trigger", "errorTrigger", 1, (0, 0), {}),
        webhook("Alert webhook", "ops/incident", (0, 220)),
        ops_config(config, (240, 110)), code_node("Normalize + enrich", "normalize_incident.js", (480, 110)),
        claude_call("Claude classify", (720, 110)), code_node("Parse + validate", "parse_incident.js", (960, 110)),
        switch("Route by severity", "$json.route.branch", ["critical", "high", "medium"], (1200, 110)),
        email("Email on-call", (1460, -120)), telegram("Page on-call (Telegram)", (1700, 0)),
        slack("Post to Slack", (1460, 240)),
        postgres_query("Log incident", INCIDENT_LOG_SQL, PARSED + ".log_row", (1960, 110)),
    ]
    pairs = [("Error Trigger", "Ops config", 0), ("Alert webhook", "Ops config", 0),
             ("Ops config", "Normalize + enrich", 0), ("Normalize + enrich", "Claude classify", 0),
             ("Claude classify", "Parse + validate", 0), ("Parse + validate", "Route by severity", 0),
             ("Route by severity", "Email on-call", 0), ("Email on-call", "Page on-call (Telegram)", 0),
             ("Route by severity", "Page on-call (Telegram)", 1), ("Route by severity", "Post to Slack", 2),
             ("Route by severity", "Log incident", 3), ("Page on-call (Telegram)", "Log incident", 0),
             ("Post to Slack", "Log incident", 0)]
    return workflow("Ops - Incident triage (Claude)", nodes, pairs)


def helpdesk(name: str, position: tuple[int, int]) -> dict:
    """POST a ticket to the helpdesk URL from Ops config (credential ``Helpdesk API``)."""
    body = ("={{ JSON.stringify({ subject: " + PARSED + ".subject, requester: " + PARSED + ".from_email, "
            "priority: " + PARSED + ".classification.priority, description: " + PARSED + ".notify_text }) }}")
    params = {"method": "POST", "url": "={{ " + CONFIG + ".helpdesk_url }}",
              "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth",
              "sendBody": True, "specifyBody": "json", "jsonBody": body, "options": {}}
    return node(name, "httpRequest", 4.2, position, params, {"httpHeaderAuth": "Helpdesk API"})


def crm_row() -> str:
    """Expression building the CRM upsert row from the parsed item."""
    return ("({ email: " + PARSED + ".from_email, name: " + PARSED + ".from_name, company: " + PARSED
            + ".classification.company, intent: " + PARSED + ".classification.intent, priority: " + PARSED
            + ".classification.priority, lead_score: " + PARSED + ".classification.lead_score, summary: "
            + PARSED + ".classification.summary, reply_draft: " + PARSED + ".classification.reply_draft })")


def lead_triage() -> dict:
    """Inbound message -> Claude intent/score/reply draft -> sales alert, CRM, helpdesk or drop -> log."""
    config = {"telegram_chat_id": "REPLACE_WITH_SALES_CHAT_ID",
              "helpdesk_url": "https://helpdesk.example.com/api/v2/tickets"}
    nodes = [
        webhook("Inbound message", "ops/lead", (0, 120)), ops_config(config, (240, 120)),
        code_node("Normalize message", "normalize_lead.js", (480, 120)), claude_call("Claude triage", (720, 120)),
        code_node("Parse + validate", "parse_lead.js", (960, 120)),
        switch("Route by intent", "$json.route.branch", ["hot", "warm", "ticket", "spam"], (1200, 120)),
        telegram("Alert sales (Telegram)", (1460, -140)),
        postgres_query("Upsert CRM lead", CRM_UPSERT_SQL, crm_row(), (1700, -40)),
        helpdesk("Open helpdesk ticket", (1460, 200)), node("Drop spam", "noOp", 1, (1460, 360), {}),
        postgres_query("Log triage", TRIAGE_LOG_SQL, PARSED + ".log_row", (1960, 120)),
    ]
    pairs = [("Inbound message", "Ops config", 0), ("Ops config", "Normalize message", 0),
             ("Normalize message", "Claude triage", 0), ("Claude triage", "Parse + validate", 0),
             ("Parse + validate", "Route by intent", 0), ("Route by intent", "Alert sales (Telegram)", 0),
             ("Alert sales (Telegram)", "Upsert CRM lead", 0), ("Route by intent", "Upsert CRM lead", 1),
             ("Route by intent", "Open helpdesk ticket", 2), ("Route by intent", "Drop spam", 3),
             ("Route by intent", "Log triage", 4), ("Upsert CRM lead", "Log triage", 0),
             ("Open helpdesk ticket", "Log triage", 0), ("Drop spam", "Log triage", 0)]
    return workflow("Ops - Inbox and lead triage (Claude)", nodes, pairs)


def failing_job(upstream_url: str = "http://n8nops-sink:8080/upstream/orders") -> dict:
    """DEMO ONLY: a webhook job whose upstream call fails, so n8n fires the Error Trigger flow."""
    note = "DEMO: the upstream is the demo sink, which always answers 503, so this job always fails."
    nodes = [node("Start nightly sync", "webhook", 2, (0, 0),
                  {"httpMethod": "POST", "path": "demo/nightly-sync", "options": {}}, webhookId="demo-nightly-sync"),
             node("Fetch upstream orders", "httpRequest", 4.2, (260, 0), {"url": upstream_url, "options": {}},
                  notes=note)]
    return workflow("Nightly order sync", nodes, [("Start nightly sync", "Fetch upstream orders", 0)])


def sink_node(original: dict, channel: str, sink: str) -> dict:
    """HTTP Request that POSTs what the notification node would have sent to the demo sink."""
    to = {"telegram": CONFIG + ".telegram_chat_id", "slack": CONFIG + ".slack_channel", "email": CONFIG + ".email_to"}
    body = ("={{ JSON.stringify({ channel: '" + channel + "', to: " + to[channel]
            + ", text: " + PARSED + ".notify_text }) }}")
    params = {"method": "POST", "url": f"{sink}/notify/{channel}", "sendBody": True,
              "specifyBody": "json", "jsonBody": body, "options": {}}
    return {**{k: original[k] for k in ("id", "name", "position")}, "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2, "parameters": params, "notes": f"DEMO: stands in for the {channel} node"}


def demo_variant(production: dict, sink: str) -> dict:
    """Test copy: notification nodes -> sink, helpdesk URL -> sink; everything else unchanged."""
    out = copy.deepcopy(production)
    out["name"] = "[DEMO] " + out["name"]
    for index, item in enumerate(out["nodes"]):
        if item["type"] in NOTIFY_TYPES:
            out["nodes"][index] = sink_node(item, NOTIFY_TYPES[item["type"]], sink)
        if item["name"] == "Ops config":
            for row in item["parameters"]["assignments"]["assignments"]:
                if row["name"] == "helpdesk_url":
                    row["value"] = f"{sink}/helpdesk/tickets"
    return out


def write(path: Path, data: dict) -> None:
    """Write pretty JSON with a trailing newline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def main() -> None:
    """Regenerate every workflow file."""
    write(ROOT / "workflows/incident-triage.json", incident_triage())
    write(ROOT / "workflows/lead-triage.json", lead_triage())
    write(ROOT / "demo/failing-nightly-sync.json", failing_job())


if __name__ == "__main__":
    main()
