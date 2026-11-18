"""Read the demo executions back out of the throwaway n8n, scrub them and write the proof files."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import requests

NODE_BIN = os.environ.get("NODE_BIN") or shutil.which("node") or "node"
SHOT_JS = Path(__file__).resolve().parent / "n8n_shot.js"
DROP_KEYS = {"headers", "x-webhook-token", "cookie", "authorization"}
EMAIL = re.compile(r"[\w.+-]+@(?!example\.)[\w-]+(\.[\w-]+)+")


def unflatten(text: str):
    """Decode n8n's ``flatted`` serialisation of execution data into plain JSON."""
    table, done = json.loads(text), {}

    def value(index: int):
        if index in done:
            return done[index]
        item = table[index]
        if isinstance(item, list):
            done[index] = out = []
            out.extend(convert(v) for v in item)
        elif isinstance(item, dict):
            done[index] = out = {}
            out.update({k: convert(v) for k, v in item.items()})
        else:
            done[index] = out = item
        return out

    def convert(raw):
        return value(int(raw)) if isinstance(raw, str) else raw

    return value(0)


def scrub(value):
    """Drop header/auth keys and mask any non-example email address, recursively."""
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items() if k.lower() not in DROP_KEYS}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, str):
        return EMAIL.sub("<email>", value)
    return value


def executions(session: requests.Session, base: str, workflow_id: str) -> list[dict]:
    """Full, decoded executions of one workflow, oldest first."""
    query = {"filter": json.dumps({"workflowId": workflow_id}), "limit": 50}
    listing = session.get(f"{base}/rest/executions", params=query, timeout=30).json()["data"]["results"]
    out = []
    for item in sorted(listing, key=lambda e: int(e["id"])):
        full = session.get(f"{base}/rest/executions/{item['id']}", timeout=30).json()["data"]
        full["data"] = unflatten(full["data"]) if isinstance(full["data"], str) else full["data"]
        out.append(full)
    return out


def node_runs(execution: dict) -> list[dict]:
    """Per node: name, status, time and the first output item (scrubbed, long strings cut)."""
    run_data = execution["data"]["resultData"]["runData"]
    rows = []
    for name, runs in run_data.items():
        last = runs[-1]
        main = (last.get("data") or {}).get("main") or [[]]
        first = next((branch[0]["json"] for branch in main if branch), None)
        status = last.get("executionStatus") or ("error" if last.get("error") else "success")
        rows.append({"node": name, "status": status, "ms": last.get("executionTime"), "first_item": scrub(first)})
    return rows


def output_of(nodes: list[dict], name: str) -> dict:
    """First output item of the named node, or ``{}``."""
    return next((n["first_item"] or {} for n in nodes if n["node"] == name), {})


def summary_row(kind: str, execution: dict, nodes: list[dict]) -> dict:
    """One results-table row for an execution."""
    parsed = output_of(nodes, "Parse + validate")
    found = parsed.get("classification") or {}
    ran = [n["node"] for n in nodes]
    trigger = next((t for t in ("Error Trigger", "Alert webhook", "Inbound message") if t in ran), "")
    subject = parsed.get("workflow_name") if kind == "incident" else parsed.get("subject")
    return {"execution": execution["id"], "flow": kind, "trigger": trigger, "input": subject,
            "claude": found.get("severity") or found.get("intent"), "branch": (parsed.get("route") or {}).get("branch"),
            "classifier_ok": parsed.get("classifier_ok"), "path": " > ".join(ran[ran.index("Parse + validate") + 1:])
            if "Parse + validate" in ran else "", "status": execution["status"]}


def db_rows(table: str) -> list[dict]:
    """All rows of one demo Postgres table (read with psql inside the demo container)."""
    sql = f"SELECT coalesce(json_agg(t ORDER BY id), '[]') FROM {table} t"  # table names are fixed constants
    done = subprocess.run(["docker", "exec", "n8nops-pg", "psql", "-U", "ops", "-d", "ops", "-At", "-c", sql],
                          capture_output=True, text=True, timeout=60, check=True)
    return scrub(json.loads(done.stdout))


def table_md(rows: list[dict]) -> str:
    """Rows as a markdown table."""
    head = list(rows[0])
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    return "\n".join(lines + ["| " + " | ".join(str(r[k]) for k in head) + " |" for r in rows])


def save_all(session, base: str, ids: dict, sent: list, sink_dir: Path, out: Path, claude_url: str) -> list[dict]:
    """Write executions.json, results.md, db-rows.json and sink-log.jsonl; return the table rows."""
    out.mkdir(parents=True, exist_ok=True)
    full, rows = [], []
    for kind in ("incident", "lead", "failing"):
        for execution in executions(session, base, ids[kind]):
            nodes = node_runs(execution)
            full.append({"flow": kind, "id": execution["id"], "status": execution["status"],
                         "startedAt": execution.get("startedAt"), "stoppedAt": execution.get("stoppedAt"),
                         "nodes": nodes})
            if kind != "failing":
                rows.append(summary_row(kind, execution, nodes))
    (out / "executions.json").write_text(json.dumps(full, indent=2) + "\n")
    tables = {t: db_rows(t) for t in ("ops_incidents", "crm_leads", "inbox_triage_log")}
    (out / "db-rows.json").write_text(json.dumps(tables, indent=2) + "\n")
    sink_log = (sink_dir / "sink-log.jsonl").read_text() if (sink_dir / "sink-log.jsonl").exists() else ""
    (out / "sink-log.jsonl").write_text("".join(json.dumps(scrub(json.loads(x))) + "\n" for x in sink_log.splitlines()))
    (out / "sent.json").write_text(json.dumps(sent, indent=2) + "\n")
    (out / "results.md").write_text(results_md(rows, tables, claude_url))
    return rows


def results_md(rows: list[dict], tables: dict, claude_url: str) -> str:
    """The human-readable summary of the demo run."""
    via = "a one-port relay to our self-hosted LiteLLM gateway" if "relay" in claude_url else claude_url
    counts = ", ".join(f"{name}: {len(items)} rows" for name, items in tables.items())
    return (f"# Throwaway n8n 2.4.6 run\n\nClaude reached through {via}. Postgres after the run: {counts}.\n\n"
            + table_md(rows) + "\n")


def screenshots(session, base: str, ids: dict, email: str, password: str, shots: Path) -> list[dict]:
    """Canvas of both production flows plus three demo execution views, via demo/n8n_shot.js."""
    jobs = [{"url": f"/workflow/{ids['incident_prod']}", "out": str(shots / "incident-triage-canvas.png"),
             "mode": "canvas"},
            {"url": f"/workflow/{ids['lead_prod']}", "out": str(shots / "lead-triage-canvas.png"), "mode": "canvas"}]
    for kind, label in (("incident", "critical"), ("lead", "hot"), ("incident", "error-trigger")):
        chosen = pick_execution(session, base, ids[kind], label)
        if chosen:
            jobs.append({"url": f"/workflow/{ids[kind]}/executions/{chosen}", "mode": "execution",
                         "out": str(shots / f"{kind}-execution-{label}.png")})
    shots.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump({"base": base, "jobs": jobs}, fh)
    env = {**os.environ, "N8N_USER": email, "N8N_PASS": password}
    done = subprocess.run([NODE_BIN, str(SHOT_JS), fh.name], env=env, capture_output=True, text=True, timeout=600)
    Path(fh.name).unlink(missing_ok=True)
    results = [json.loads(line) for line in done.stdout.splitlines() if line.startswith("{")]
    return results or [{"ok": False, "error": done.stderr[-500:]}]


def pick_execution(session, base: str, workflow_id: str, label: str) -> str:
    """Id of the first execution whose route branch (or trigger) matches ``label``."""
    for execution in executions(session, base, workflow_id):
        nodes = node_runs(execution)
        ran = {n["node"] for n in nodes}
        if label == "error-trigger" and "Error Trigger" in ran:
            return execution["id"]
        branch = (output_of(nodes, "Parse + validate").get("route") or {}).get("branch")
        if branch == label and "Error Trigger" not in ran:
            return execution["id"]
    return ""
