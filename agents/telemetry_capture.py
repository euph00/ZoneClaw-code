"""Controller-side archival; reads state without changing the agent workspace."""

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


def line_count(path):
    with path.open("rb") as handle:
        return sum(1 for _ in handle)


def capture(state, artifacts, mode, metadata=None):
    destination = artifacts / "telemetry"
    destination.mkdir(parents=True, exist_ok=True)
    manifest_path = destination / "capture.json"
    ledger = state / "telemetry" / "provider-requests.jsonl"
    raw_api = state / "telemetry" / "raw-api.jsonl"
    now = datetime.now(timezone.utc).isoformat()
    if mode == "begin":
        manifest = {
            "schema_version": 1, "started_at": now, "status": "started",
            "transcript_offsets": {}, "auxiliary_offset": 0,
            "errors": [], **(metadata or {}),
        }
        for source in sorted((state / "agents").rglob("*.jsonl")):
            manifest["transcript_offsets"][str(source.relative_to(state))] = line_count(source)
        if ledger.is_file():
            manifest["auxiliary_offset"] = line_count(ledger)
        manifest["raw_api_offset"] = line_count(raw_api) if raw_api.is_file() else 0
    else:
        manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {
            "schema_version": 1, "errors": ["begin capture missing"],
        }
        manifest["finished_at"] = now
        if metadata and "agent_completed" in metadata:
            manifest["agent_completed"] = metadata["agent_completed"]
        manifest["transcript_files"] = 0
        manifest["helper_components"] = []
        for source in sorted((state / "agents").rglob("*.jsonl")):
            target = artifacts / "transcripts" / source.relative_to(state)
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                manifest["transcript_files"] += 1
            except OSError as exc:
                manifest["errors"].append(f"transcript copy: {type(exc).__name__}")
        if ledger.is_file():
            shutil.copyfile(ledger, destination / "provider-requests.jsonl")
            components = set()
            for line in ledger.read_text().splitlines():
                try:
                    event = json.loads(line)
                    if event.get("kind") == "init":
                        components.add(event["component"])
                except (ValueError, KeyError):
                    manifest["errors"].append("invalid auxiliary ledger entry")
            manifest["helper_components"] = sorted(components)
        missing = set(manifest.get("expected_helpers", [])) - set(manifest["helper_components"])
        if missing:
            manifest["errors"].append("missing helper instrumentation: " + ", ".join(sorted(missing)))
        if raw_api.is_file():
            shutil.copyfile(raw_api, destination / "raw-api.jsonl")
        elif manifest.get("raw_api_provider"):
            manifest["errors"].append("missing raw API instrumentation")
        if not manifest["transcript_files"]:
            manifest["errors"].append("no session transcripts")
        manifest["status"] = "incomplete" if manifest["errors"] else "complete"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("begin", "end"))
    parser.add_argument("--state", type=Path, default=Path("/tmp/openclaw-state"))
    parser.add_argument("--artifacts", type=Path, default=Path("/logs/artifacts"))
    parser.add_argument("--metadata", default="{}")
    args = parser.parse_args()
    capture(args.state, args.artifacts, args.mode, json.loads(args.metadata))
