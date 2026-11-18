"""Local runner CLI.

    python -m runner.cli --dry-run            # print the Claude requests, no API call
    python -m runner.cli --live --out docs/results/local-runner   # real Claude calls

``--live`` needs ANTHROPIC_API_KEY in the environment (and ANTHROPIC_BASE_URL + ``--model`` when
you go through an Anthropic-compatible gateway instead of api.anthropic.com). Samples live in ``samples/`` and are
synthetic; each carries a hand-written expectation that the results table checks.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from runner import spec
from runner.claude import AnthropicClient, ClaudeClient
from runner.pipeline import meets, now_iso, run_one

ROOT = Path(__file__).resolve().parent.parent


def load_samples(folder: Path) -> list[dict]:
    """Every ``samples/<kind>s/*.json`` file, sorted by kind then name."""
    found = []
    for kind in ("incident", "lead"):
        for path in sorted((folder / f"{kind}s").glob("*.json")):
            found.append({"kind": kind, "file": path.name, **json.loads(path.read_text())})
    return found


def row_of(sample: dict, run: dict) -> dict:
    """One results-table row for a sample run."""
    found = run["result"]["classification"]
    label = found.get("severity") or found.get("intent")
    return {"sample": sample["file"], "kind": sample["kind"], "label": label,
            "branch": run["result"]["route"]["branch"], "classifier_ok": run["result"]["classifier_ok"],
            "expected": meets(sample["expect"], run["result"]), "latency_ms": run["latency_ms"],
            "tokens_in": run["usage"]["input_tokens"], "tokens_out": run["usage"]["output_tokens"]}


def markdown_table(rows: list[dict]) -> str:
    """Rows as a GitHub-flavoured markdown table."""
    head = list(rows[0])
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    lines += ["| " + " | ".join(str(row[key]) for key in head) + " |" for row in rows]
    return "\n".join(lines)


def run_all(samples: list[dict], client: ClaudeClient) -> tuple[list[dict], list[dict]]:
    """Run every sample; returns (full runs, table rows)."""
    runs, rows = [], []
    for sample in samples:
        run = run_one(sample["kind"], sample["payload"], client)
        runs.append({"sample": sample["file"], "expect": sample["expect"], **run})
        rows.append(row_of(sample, run))
    return runs, rows


def write_outputs(out: Path, runs: list[dict], rows: list[dict], note: str = "") -> None:
    """Write ``<out>.json`` (full runs) and ``<out>.md`` (summary table, with an optional route note)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    meta = {"model": spec.MODEL, "route": note, "ran_at": now_iso()}
    out.with_suffix(".json").write_text(json.dumps({**meta, "runs": runs}, indent=2) + "\n")
    passed = sum(row["expected"] for row in rows)
    summary = f"Model `{spec.MODEL}`, {passed}/{len(rows)} samples met their expectation. {note}\n\n"
    out.with_suffix(".md").write_text(summary + markdown_table(rows) + "\n")


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and run the samples in dry-run or live mode."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--live", action="store_true", help="call the real Claude API")
    parser.add_argument("--dry-run", action="store_true", help="print the request bodies only")
    parser.add_argument("--model", default="", help="model id override for an Anthropic-compatible gateway")
    parser.add_argument("--note", default="", help="free-text note on how the model was reached")
    parser.add_argument("--samples", type=Path, default=ROOT / "samples")
    parser.add_argument("--out", type=Path, default=ROOT / "docs/results/local-runner")
    args = parser.parse_args(argv)
    samples = load_samples(args.samples)
    if args.dry_run or not args.live:
        from runner.normalize import normalize_incident, normalize_lead
        steps = {"incident": normalize_incident, "lead": normalize_lead}
        for sample in samples:
            print(json.dumps(steps[sample["kind"]](sample["payload"], "dry-run")["claude_request"], indent=2))
        return 0
    runs, rows = run_all(samples, AnthropicClient(model_override=args.model))
    write_outputs(args.out, runs, rows, args.note)
    print(markdown_table(rows))
    return 0 if all(row["expected"] for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
