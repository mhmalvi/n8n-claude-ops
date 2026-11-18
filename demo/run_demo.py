"""Run both workflows for real inside a THROWAWAY n8n (same image as production) and capture proof.

    DEMO_CLAUDE_KEY=... python -m demo.run_demo [--keep]

What it does, all on a private Docker network that is deleted at the end:
1. starts Postgres (schema from db/schema.sql), the demo sink (stands in for Telegram / Slack /
   SMTP / helpdesk / a failing upstream API) and n8nio/n8n on 127.0.0.1:5711 with no volume;
2. creates a throwaway owner and the credentials the workflows reference by name;
3. imports the DEMO variants (see builder.build_workflows.demo_variant) plus a job that fails on
   purpose and names the incident flow as its error workflow, then activates them;
4. POSTs the synthetic samples to the webhooks and triggers the failing job (real Error Trigger);
5. reads every execution back, the rows written to Postgres and the sink log, and writes them to
   docs/results/n8n-demo/; screenshots the canvases and executions with headless Chromium.

Secrets come from the environment only and are never printed or written to disk:
DEMO_CLAUDE_KEY (required), DEMO_CLAUDE_URL (default https://api.anthropic.com/v1/messages),
DEMO_CLAUDE_MODEL (model id override for a gateway), DEMO_RELAY_NETWORK + DEMO_RELAY_TARGET
(optional: reach a gateway on another Docker network through a one-port relay).
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import requests

from builder import build_workflows as bw
from demo import collect

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs/results/n8n-demo"
SHOTS = ROOT / "docs/screens"
IMAGE = "n8nio/n8n:2.4.6"
NET = "n8nops-demo"
PORT = 5711
BASE = f"http://127.0.0.1:{PORT}"
SINK = "http://n8nops-sink:8080"
NAMES = ["n8nops-n8n", "n8nops-pg", "n8nops-sink", "n8nops-relay"]


def docker(*args: str, check: bool = True) -> str:
    """Run a docker command and return stdout."""
    done = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=300)
    if check and done.returncode:
        raise RuntimeError(f"docker {args[0]} failed: {done.stderr.strip()[:300]}")
    return done.stdout.strip()


def start_support(pg_password: str, sink_dir: Path) -> None:
    """Network, Postgres with the schema, and the sink."""
    docker("network", "create", NET)
    docker("run", "-d", "--rm", "--name", "n8nops-pg", "--network", NET, "-e", "POSTGRES_USER=ops",
           "-e", f"POSTGRES_PASSWORD={pg_password}", "-e", "POSTGRES_DB=ops",
           "-v", f"{ROOT / 'db/schema.sql'}:/docker-entrypoint-initdb.d/schema.sql:ro", "postgres:16-alpine")
    docker("run", "-d", "--rm", "--name", "n8nops-sink", "--network", NET, "-v", f"{ROOT / 'demo'}:/app:ro",
           "-v", f"{sink_dir}:/out", "python:3.12-slim", "python", "/app/sink.py")


def start_relay() -> str:
    """Optional one-port relay to a gateway on another network; returns the URL n8n should call."""
    network, target = os.environ.get("DEMO_RELAY_NETWORK", ""), os.environ.get("DEMO_RELAY_TARGET", "")
    if not (network and target):
        return os.environ.get("DEMO_CLAUDE_URL", "https://api.anthropic.com/v1/messages")
    host, port = target.split(":")
    docker("run", "-d", "--rm", "--name", "n8nops-relay", "--network", NET, "-v", f"{ROOT / 'demo'}:/app:ro",
           "python:3.12-slim", "python", "/app/relay.py", "4000", host, port)
    docker("network", "connect", network, "n8nops-relay")
    return "http://n8nops-relay:4000/v1/messages"


def start_n8n() -> None:
    """The throwaway n8n: same image as production, loopback port, no volume."""
    docker("run", "-d", "--rm", "--name", "n8nops-n8n", "--network", NET, "-p", f"127.0.0.1:{PORT}:5678",
           "-e", "N8N_SECURE_COOKIE=false", "-e", "N8N_DIAGNOSTICS_ENABLED=false",
           "-e", "N8N_PERSONALIZATION_ENABLED=false", "-e", "GENERIC_TIMEZONE=UTC",
           "-e", f"WEBHOOK_URL=http://localhost:{PORT}/", IMAGE)
    for _ in range(90):
        try:
            resp = requests.get(f"{BASE}/rest/settings", timeout=3)
            if resp.ok and resp.headers.get("content-type", "").startswith("application/json"):
                return
        except requests.RequestException:
            pass
        time.sleep(2)
    raise TimeoutError("demo n8n never came up")


def stop_all() -> None:
    """Remove every demo container and the network (nothing has a volume)."""
    for name in NAMES:
        docker("rm", "-f", name, check=False)
    docker("network", "rm", NET, check=False)


def owner_session(email: str, password: str) -> requests.Session:
    """Create the throwaway owner and return a logged-in session."""
    session = requests.Session()
    body = {"email": email, "firstName": "Demo", "lastName": "Owner", "password": password}
    session.post(f"{BASE}/rest/owner/setup", json=body, timeout=30).raise_for_status()
    return session


def create_credentials(session: requests.Session, claude_key: str, webhook_token: str, pg_password: str) -> dict:
    """Create the credentials the workflows reference by name (only inside the throwaway); name -> id."""
    creds = [
        ("Anthropic API", "httpHeaderAuth", {"name": "x-api-key", "value": claude_key}),
        ("Ops Webhook Token", "httpHeaderAuth", {"name": "X-Webhook-Token", "value": webhook_token}),
        ("Helpdesk API", "httpHeaderAuth", {"name": "Authorization", "value": "Bearer demo-only"}),
        # Placeholders so the production copies (imported inactive, only for canvas screenshots) bind; never used.
        ("Ops Telegram Bot", "telegramApi", {"accessToken": "placeholder-not-used"}),
        ("Ops Slack", "slackApi", {"accessToken": "placeholder-not-used"}),
        ("Ops SMTP", "smtp", {"user": "placeholder", "password": "placeholder", "host": "smtp.example.com",
                              "port": 587, "secure": False}),
        ("Ops Postgres", "postgres", {"host": "n8nops-pg", "port": 5432, "database": "ops", "user": "ops",
                                      "password": pg_password, "ssl": "disable"}),
    ]
    made = {}
    for name, ctype, data in creds:
        resp = session.post(f"{BASE}/rest/credentials", json={"name": name, "type": ctype, "data": data}, timeout=30)
        resp.raise_for_status()
        made[name] = resp.json()["data"]["id"]
    return made


def bind_credentials(workflow: dict, credential_ids: dict) -> dict:
    """Add the throwaway credential id next to each by-name reference (n8n would otherwise bind by type)."""
    for item in workflow["nodes"]:
        for ref in item.get("credentials", {}).values():
            if ref["name"] in credential_ids:
                ref["id"] = credential_ids[ref["name"]]
    return workflow


def demo_workflow(production: dict, claude_url: str, credential_ids: dict) -> dict:
    """Demo variant plus the Claude endpoint/model swap for this run (documented in the output)."""
    workflow = bw.demo_variant(production, SINK)
    model = os.environ.get("DEMO_CLAUDE_MODEL", "")
    for item in workflow["nodes"]:
        if item["name"].startswith("Claude "):
            item["parameters"]["url"] = claude_url
            if model:
                item["parameters"]["jsonBody"] = (
                    "={{ JSON.stringify({ ...$json.claude_request, model: '" + model + "' }) }}")
    return bind_credentials(workflow, credential_ids)


def import_only(session: requests.Session, workflow: dict) -> dict:
    """Import one workflow (inactive) and return n8n's record of it."""
    resp = session.post(f"{BASE}/rest/workflows", json=workflow, timeout=30)
    resp.raise_for_status()
    return resp.json()["data"]


def import_and_activate(session: requests.Session, workflow: dict) -> str:
    """Import one workflow, activate it, and return its id in the throwaway."""
    data = import_only(session, workflow)
    body = {"versionId": data.get("versionId")}
    activated = session.post(f"{BASE}/rest/workflows/{data['id']}/activate", json=body, timeout=30)
    if activated.status_code == 404:
        activated = session.patch(f"{BASE}/rest/workflows/{data['id']}", json={**body, "active": True}, timeout=30)
    activated.raise_for_status()
    return data["id"]


def fire_events(webhook_token: str) -> list[dict]:
    """POST every webhook-shaped sample, then trigger the failing job once."""
    sent = []
    headers = {"X-Webhook-Token": webhook_token}
    for kind, path in (("incident", "ops/incident"), ("lead", "ops/lead")):
        for sample in sorted((ROOT / "samples" / f"{kind}s").glob("*.json")):
            payload = json.loads(sample.read_text())["payload"]
            if kind == "incident" and "execution" in payload:
                continue  # Error Trigger shapes cannot be POSTed; the failing job produces a real one.
            resp = requests.post(f"{BASE}/webhook/{path}", json=payload, headers=headers, timeout=30)
            sent.append({"sample": sample.name, "webhook": path, "status": resp.status_code})
            time.sleep(1.5)
    resp = requests.post(f"{BASE}/webhook/demo/nightly-sync", json={}, timeout=30)
    sent.append({"sample": "failing job -> Error Trigger", "webhook": "demo/nightly-sync", "status": resp.status_code})
    return sent


def run(keep: bool) -> None:
    """Whole demo; containers are removed at the end unless ``keep``."""
    claude_key = os.environ["DEMO_CLAUDE_KEY"]
    pg_password, webhook_token = secrets.token_urlsafe(18), secrets.token_urlsafe(24)
    email, password = "demo-owner@example.com", secrets.token_urlsafe(18) + "A1"
    sink_dir = Path(tempfile.mkdtemp(prefix="n8nops-sink-"))
    sink_dir.chmod(0o777)
    stop_all()
    try:
        start_support(pg_password, sink_dir)
        claude_url = start_relay()
        start_n8n()
        session = owner_session(email, password)
        creds = create_credentials(session, claude_key, webhook_token, pg_password)
        ids = {"incident": import_and_activate(session, demo_workflow(bw.incident_triage(), claude_url, creds)),
               "lead": import_and_activate(session, demo_workflow(bw.lead_triage(), claude_url, creds))}
        failing = bw.failing_job(f"{SINK}/upstream/orders")
        failing["settings"]["errorWorkflow"] = ids["incident"]
        ids["failing"] = import_and_activate(session, failing)
        for kind, production in (("incident_prod", bw.incident_triage()), ("lead_prod", bw.lead_triage())):
            ids[kind] = import_only(session, bind_credentials(production, creds))["id"]
        sent = fire_events(webhook_token)
        time.sleep(25)
        collect.save_all(session, BASE, ids, sent, sink_dir, OUT, claude_url)
        for shot in collect.screenshots(session, BASE, ids, email, password, SHOTS):
            print(json.dumps(shot))
    finally:
        if not keep:
            stop_all()
        shutil.rmtree(sink_dir, ignore_errors=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the workflows in a throwaway n8n and capture proof.")
    parser.add_argument("--keep", action="store_true", help="leave the containers running for inspection")
    run(parser.parse_args().keep)
