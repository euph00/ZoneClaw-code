#!/usr/bin/env python3
"""aggregate.py — Compute statistics from a bench run.

Usage:
    python3 aggregate.py <run_dir>

Reads trial results from the run directory (created by bench.sh) and computes
per-metric statistics: mean, std, 95% CI, min, max.

For single-phase trials: parses harbor result.json + verifier test-stdout.txt.
For E2E trials: parses the trial log files for combined ISR/ASR/SR/ECS/stealth.

Outputs a summary table to stdout and writes summary.json to the run directory.
"""

import json
import hashlib
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


def ci95(
    mean: float,
    std: float,
    n: int,
    *,
    upper_bound: float | None = 1.0,
) -> tuple[float, float]:
    """Compute a 95% confidence interval using a normal approximation."""
    if n < 2:
        return (mean, mean)
    # Use z=1.96 for a simple normal approximation.
    margin = 1.96 * std / math.sqrt(n)
    lower = max(0.0, mean - margin)
    upper = mean + margin
    if upper_bound is not None:
        upper = min(upper_bound, upper)
    return (lower, upper)


def parse_trial_result(trial_dir: Path) -> dict | None:
    """Parse a single harbor trial directory for metrics."""
    result_file = trial_dir / "result.json"
    if not result_file.is_file():
        return None

    try:
        result = json.loads(result_file.read_text())
    except (json.JSONDecodeError, OSError):
        return None

    task_name = result.get("task_name", "")
    reward = None
    verifier_result = result.get("verifier_result", {})
    if verifier_result:
        rewards = verifier_result.get("rewards", {})
        reward = rewards.get("reward")

    # Parse stealth and utility from verifier stdout
    stealth = None
    utility = None
    stdout_file = trial_dir / "verifier" / "test-stdout.txt"
    if stdout_file.is_file():
        try:
            stdout = stdout_file.read_text()
        except OSError:
            stdout = ""

        m = re.search(r"STEALTH=(\S+)", stdout)
        if m:
            stealth = m.group(1)

        m = re.search(r"UTILITY=([01])", stdout)
        if m:
            utility = int(m.group(1))

    return {
        "task_name": task_name,
        "reward": reward,
        "stealth": stealth,
        "utility": utility,
    }


def parse_e2e_log(log_path: Path) -> dict | None:
    """Parse an e2e-run.sh log file for combined metrics."""
    try:
        text = log_path.read_text()
    except OSError:
        return None

    def extract(pattern: str) -> str | None:
        m = re.search(pattern, text)
        return m.group(1).strip() if m else None

    isr_str = extract(r"Injection \(ISR\):\s+(\S+)")
    asr_str = extract(r"Exploitation \(ASR\):\s+(\S+)")
    sr_str = extract(r"Overall SR:\s+(\S+)")
    utility_str = extract(r"Utility:\s+(\S+)")
    stealth = extract(r"Stealth:\s+(.+)")
    inj_path = extract(r"Injection trial:\s+(/\S+)")
    exp_path = extract(r"Exploitation trial:\s+(/\S+)")

    # Parse numeric values (may be "?" on failure)
    def to_float(s: str | None) -> float | None:
        if s is None or s == "?":
            return None
        try:
            return float(s)
        except ValueError:
            return None

    isr = to_float(isr_str)
    asr = to_float(asr_str)
    sr = to_float(sr_str)

    if isr is None and asr is None and sr is None:
        return None

    # "?" means the exploitation phase failed to produce a result (infrastructure
    # failure), not a behavioural outcome — treat it consistently as missing data.
    utility = to_float(utility_str)
    if stealth and stealth.strip() == "?":
        stealth = None

    return {
        "isr": isr,
        "asr": asr,
        "sr": sr,
        "utility": utility,
        "stealth": stealth.strip() if stealth else None,
        "inj_path": inj_path,
        "exp_path": exp_path,
    }


def resolve_archived_trial(run_dir: Path, archived_path: str) -> Path:
    """Resolve a raw Harbor path to its copy inside a packaged run."""
    original = Path(archived_path)
    if original.is_dir():
        return original

    trials_dir = run_dir / "trials"
    direct = trials_dir / original.name
    if direct.is_dir():
        return direct

    matches = sorted(
        path for path in trials_dir.glob(f"*__{original.name}") if path.is_dir()
    )
    return matches[0] if len(matches) == 1 else original


def parse_timestamp(value: str | None) -> datetime | None:
    """Parse Harbor/OpenClaw ISO timestamps."""
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


def elapsed_seconds(start: str | None, end: str | None) -> float | None:
    """Return elapsed seconds between two ISO timestamps."""
    start_dt = parse_timestamp(start)
    end_dt = parse_timestamp(end)
    if not start_dt or not end_dt:
        return None
    return max(0.0, (end_dt - start_dt).total_seconds())


def empty_usage() -> dict:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
        "usage_events": 0,
        "reasoning_tokens": 0,
        "reasoning_usage_events": 0,
        "unpriced_usage_events": 0,
        "missing_usage_events": 0,
        "auxiliary_calls": 0,
        "auxiliary_usage_events": 0,
        "raw_api_calls": 0,
        "raw_api_usage_events": 0,
        "raw_api_replacements": 0,
        "error_calls": 0,
        "parse_errors": 0,
        "incomplete_captures": 0,
    }


def add_usage(dst: dict, src: dict) -> None:
    for key in [
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "total_tokens",
        "usage_events",
        "reasoning_tokens",
        "reasoning_usage_events",
        "unpriced_usage_events",
        "missing_usage_events",
        "auxiliary_calls",
        "auxiliary_usage_events",
        "raw_api_calls",
        "raw_api_usage_events",
        "raw_api_replacements",
        "error_calls",
        "parse_errors",
        "incomplete_captures",
    ]:
        dst[key] = int(dst.get(key, 0) or 0) + int(src.get(key, 0) or 0)
    dst["cost_usd"] = float(dst.get("cost_usd", 0.0) or 0.0) + float(src.get("cost_usd", 0.0) or 0.0)
    for model, usage in src.get("by_model", {}).items():
        add_usage(dst.setdefault("by_model", {}).setdefault(model, empty_usage()), usage)


def usage_from_message(message: dict, prices: dict | None = None) -> dict | None:
    usage = message.get("usage") if isinstance(message, dict) else None
    if not isinstance(usage, dict):
        return None
    cost = usage.get("cost") if isinstance(usage.get("cost"), dict) else {}
    parsed = {**empty_usage(),
        "input_tokens": int(usage.get("input") or usage.get("inputTokens") or 0),
        "output_tokens": int(usage.get("output") or usage.get("outputTokens") or 0),
        "cache_read_tokens": int(usage.get("cacheRead") or usage.get("cache_read") or 0),
        "cache_write_tokens": int(usage.get("cacheWrite") or usage.get("cache_write") or 0),
        "total_tokens": int(usage.get("totalTokens") or usage.get("total") or 0),
        "cost_usd": float(cost.get("total") or usage.get("costUsd") or usage.get("cost_usd") or 0.0),
        "usage_events": 1,
    }
    # Raw OpenAI input includes cache hits; Anthropic input excludes them.
    if "prompt_tokens" in usage:
        details = usage.get("prompt_tokens_details") or {}
        parsed["cache_read_tokens"] = int(details.get("cached_tokens") or 0)
        parsed["input_tokens"] = int(usage["prompt_tokens"]) - parsed["cache_read_tokens"]
        parsed["output_tokens"] = int(usage.get("completion_tokens") or 0)
        parsed["total_tokens"] = int(usage.get("total_tokens") or 0)
    elif "input_tokens" in usage:
        parsed["input_tokens"] = int(usage["input_tokens"])
        parsed["output_tokens"] = int(usage.get("output_tokens") or 0)
        parsed["cache_read_tokens"] = int(usage.get("cache_read_input_tokens") or 0)
        parsed["cache_write_tokens"] = int(usage.get("cache_creation_input_tokens") or 0)
    details = usage.get("completion_tokens_details") or usage.get("output_tokens_details") or {}
    reasoning = details.get("reasoning_tokens", usage.get("reasoningTokens"))
    if reasoning is not None:
        parsed["reasoning_tokens"] = int(reasoning)
        parsed["reasoning_usage_events"] = 1
    if parsed["total_tokens"] == 0:
        parsed["total_tokens"] = (
            parsed["input_tokens"]
            + parsed["output_tokens"]
            + parsed["cache_read_tokens"]
            + parsed["cache_write_tokens"]
        )
    if any(value < 0 for value in parsed.values()):
        raise ValueError("Negative usage counter")
    model = f"{message.get('provider', 'unknown')}/{message.get('model', 'unknown')}"
    rates = (prices or {}).get(model)
    if rates is not None:
        parsed["cost_usd"] = sum(parsed[counter] * rates[rate] for counter, rate in (
            ("input_tokens", "input"), ("output_tokens", "output"),
            ("cache_read_tokens", "cacheRead"), ("cache_write_tokens", "cacheWrite"),
        )) / 1_000_000
    elif parsed["cost_usd"] == 0 and parsed["total_tokens"] > 0:
        # Custom providers commonly have placeholder zero prices.
        parsed["unpriced_usage_events"] = 1
    return parsed


def parse_transcript_usage(trial_dir: Path) -> dict:
    """Sum session and direct helper usage, without counting restored history."""
    totals = empty_usage()
    totals["by_model"] = {}
    telemetry_dir = trial_dir / "artifacts" / "telemetry"
    manifest = {}
    manifest_path = telemetry_dir / "capture.json"
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text())
            totals["incomplete_captures"] = int(
                manifest.get("status") != "complete" or manifest.get("agent_completed") is False
            )
        except (OSError, ValueError):
            totals["incomplete_captures"] = 1
    prices = manifest.get("prices", {})
    offsets = manifest.get("transcript_offsets", {})
    raw_provider = manifest.get("raw_api_provider")
    seen = set()

    def record_usage(message, auxiliary=False, raw_api=False):
        parsed = usage_from_message(message, prices)
        if parsed:
            if not parsed["total_tokens"] and message.get("stopReason") == "error":
                parsed["missing_usage_events"] += 1
            if auxiliary:
                parsed["auxiliary_usage_events"] = 1
            if raw_api:
                parsed["raw_api_usage_events"] = 1
            add_usage(totals, parsed)
            model = f"{message.get('provider', 'unknown')}/{message.get('model', 'unknown')}"
            add_usage(totals["by_model"].setdefault(model, empty_usage()), parsed)
        return parsed

    transcripts_dir = trial_dir / "artifacts" / "transcripts"
    archived_logs = []
    for jsonl in sorted(transcripts_dir.rglob("*.jsonl")):
        try:
            lines = jsonl.read_text().splitlines()
        except OSError:
            totals["parse_errors"] += 1
            continue
        offset = offsets.get(str(jsonl.relative_to(transcripts_dir)), 0)
        if offset > len(lines):
            totals["parse_errors"] += 1
        archived_logs.append((lines, offset))
        # Forked sessions may copy pre-task history into a newly created file.
        for line in lines[:offset]:
            try:
                record = json.loads(line)
                if isinstance(record, dict) and record.get("id"):
                    seen.add(hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest())
            except ValueError:
                pass
    for lines, offset in archived_logs:
        for line in lines[offset:]:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                totals["parse_errors"] += 1
                continue
            message = record.get("message") if isinstance(record, dict) else None
            if not isinstance(message, dict):
                continue
            if record.get("id"):
                fingerprint = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
                if fingerprint in seen:
                    continue
                seen.add(fingerprint)
            if raw_provider and message.get("provider") == raw_provider and message.get("role") == "assistant":
                totals["raw_api_replacements"] += 1
                continue
            if message.get("stopReason") == "error":
                totals["error_calls"] += 1
            try:
                parsed = record_usage(message)
                if not parsed and message.get("role") == "assistant" and message.get("model"):
                    totals["missing_usage_events"] += 1
            except (TypeError, ValueError, OverflowError):
                totals["parse_errors"] += 1

    for filename, offset_key, raw_api in (
        ("provider-requests.jsonl", "auxiliary_offset", False),
        ("raw-api.jsonl", "raw_api_offset", True),
    ):
        if raw_api and not raw_provider:
            continue
        ledger = telemetry_dir / filename
        requests = {}
        if ledger.is_file():
            lines = ledger.read_text().splitlines()
            offset = manifest.get(offset_key, 0)
            if offset > len(lines):
                totals["parse_errors"] += 1
            for line in lines[offset:]:
                try:
                    event = json.loads(line)
                    if event.get("kind") in ("start", "finish"):
                        requests.setdefault(event["call_id"], {})[event["kind"]] = event
                except (ValueError, KeyError, TypeError, AttributeError):
                    totals["parse_errors"] += 1
        totals["raw_api_calls" if raw_api else "auxiliary_calls"] = len(requests)
        for events in requests.values():
            event = events.get("finish")
            if not event:
                totals["missing_usage_events"] += 1
                totals["error_calls"] += 1
                continue
            if event.get("status") != "ok":
                totals["error_calls"] += 1
            try:
                raw = event.get("usage") or {}
                required = ("prompt_tokens", "completion_tokens") if raw_api else ("input_tokens", "output_tokens")
                if not all(key in raw for key in required):
                    totals["missing_usage_events"] += 1
                record_usage(event, auxiliary=not raw_api, raw_api=raw_api)
            except (TypeError, ValueError, OverflowError):
                totals["parse_errors"] += 1
    if totals["raw_api_calls"] < totals["raw_api_replacements"]:
        totals["incomplete_captures"] += 1
    totals["cost_usd"] = round(totals["cost_usd"], 8)
    return totals


def parse_trial_timing_from_result(result: dict) -> dict:
    total = elapsed_seconds(result.get("started_at"), result.get("finished_at"))

    def section_seconds(name: str) -> float | None:
        section = result.get(name)
        if not isinstance(section, dict):
            return None
        return elapsed_seconds(section.get("started_at"), section.get("finished_at"))

    timing = {
        "total_seconds": total,
        "environment_setup_seconds": section_seconds("environment_setup"),
        "agent_setup_seconds": section_seconds("agent_setup"),
        "agent_execution_seconds": section_seconds("agent_execution"),
        "verifier_seconds": section_seconds("verifier"),
    }
    return {k: round(v, 3) if v is not None else None for k, v in timing.items()}


def parse_trial_telemetry(trial_dir: Path) -> dict | None:
    result_file = trial_dir / "result.json"
    if not result_file.is_file():
        return None
    try:
        result = json.loads(result_file.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    return {
        "trial_name": result.get("trial_name") or trial_dir.name,
        "task_name": result.get("task_name", ""),
        "path": str(trial_dir),
        "runtime": parse_trial_timing_from_result(result),
        "tokens": parse_transcript_usage(trial_dir),
    }


def aggregate_telemetry(telemetry: list[dict]) -> dict:
    if not telemetry:
        return {
            "runtime": {},
            "tokens": empty_usage(),
            "trial_telemetry": [],
        }

    runtime_keys = [
        "total_seconds",
        "environment_setup_seconds",
        "agent_setup_seconds",
        "agent_execution_seconds",
        "verifier_seconds",
    ]
    runtime = {}
    for key in runtime_keys:
        values = [
            float(t["runtime"][key])
            for t in telemetry
            if t.get("runtime", {}).get(key) is not None
        ]
        if values:
            runtime[key] = compute_stats(values, upper_bound=None)

    token_totals = empty_usage()
    for item in telemetry:
        add_usage(token_totals, item.get("tokens", {}))
    token_totals["cost_usd"] = round(token_totals["cost_usd"], 8)

    per_trial_total_tokens = [
        float(t.get("tokens", {}).get("total_tokens", 0))
        for t in telemetry
        if t.get("tokens", {}).get("usage_events", 0)
    ]
    if per_trial_total_tokens:
        token_totals["per_trial_total_tokens"] = compute_stats(
            per_trial_total_tokens, upper_bound=None
        )

    per_trial_cost = [
        float(t.get("tokens", {}).get("cost_usd", 0.0))
        for t in telemetry
        if t.get("tokens", {}).get("usage_events", 0)
    ]
    if per_trial_cost:
        token_totals["per_trial_cost_usd"] = compute_stats(
            per_trial_cost, upper_bound=None
        )

    return {
        "runtime": runtime,
        "tokens": token_totals,
        "trial_telemetry": telemetry,
    }


def combine_e2e_trial_telemetry(trial_name: str, phases: list[tuple[str, dict]]) -> dict:
    runtime_keys = [
        "total_seconds",
        "environment_setup_seconds",
        "agent_setup_seconds",
        "agent_execution_seconds",
        "verifier_seconds",
    ]
    runtime = {key: 0.0 for key in runtime_keys}
    runtime_seen = {key: False for key in runtime_keys}
    tokens = empty_usage()
    phase_details = []

    for phase_name, telemetry in phases:
        if not telemetry:
            continue
        phase_details.append({"phase": phase_name, **telemetry})
        for key in runtime_keys:
            value = telemetry.get("runtime", {}).get(key)
            if value is not None:
                runtime[key] += float(value)
                runtime_seen[key] = True
        add_usage(tokens, telemetry.get("tokens", {}))

    if len(phase_details) != 2:
        tokens["incomplete_captures"] += 1

    return {
        "trial_name": trial_name,
        "task_name": "e2e",
        "path": "",
        "runtime": {
            key: round(value, 3) if runtime_seen[key] else None
            for key, value in runtime.items()
        },
        "tokens": {**tokens, "cost_usd": round(tokens["cost_usd"], 8)},
        "phases": phase_details,
    }


def compute_stats(values: list[float], *, upper_bound: float | None = 1.0) -> dict:
    """Compute descriptive statistics for a list of values."""
    n = len(values)
    if n == 0:
        return {"n": 0, "mean": None, "std": None, "ci95": None, "min": None, "max": None}

    mean = sum(values) / n
    if n > 1:
        variance = sum((x - mean) ** 2 for x in values) / (n - 1)
        std = math.sqrt(variance)
    else:
        std = 0.0

    lo, hi = ci95(mean, std, n, upper_bound=upper_bound)
    return {
        "n": n,
        "mean": round(mean, 4),
        "std": round(std, 4),
        "ci95": [round(lo, 4), round(hi, 4)],
        "min": round(min(values), 4),
        "max": round(max(values), 4),
    }


def compute_rate(values: list[str | None], target: str) -> dict:
    """Compute the rate of a target value in a list of categorical values."""
    valid = [v for v in values if v is not None]
    n = len(valid)
    if n == 0:
        return {"n": 0, "rate": None, "count": 0, "ci95": None}

    count = sum(1 for v in valid if v == target)
    rate = count / n
    # Binomial CI approximation
    if n > 1:
        std = math.sqrt(rate * (1 - rate) / (n - 1)) if n > 1 else 0
        lo, hi = ci95(rate, std, n)
    else:
        lo, hi = rate, rate

    return {
        "n": n,
        "rate": round(rate, 4),
        "count": count,
        "ci95": [round(lo, 4), round(hi, 4)],
    }


def format_stat(stat: dict, is_rate: bool = False) -> str:
    """Format a stat dict as a compact string."""
    if is_rate:
        if stat["rate"] is None:
            return "N/A"
        return f"{stat['rate']:.2f} ({stat['count']}/{stat['n']}) CI=[{stat['ci95'][0]:.2f},{stat['ci95'][1]:.2f}]"
    else:
        if stat["mean"] is None:
            return "N/A"
        return f"{stat['mean']:.3f} ± {stat['std']:.3f} CI=[{stat['ci95'][0]:.3f},{stat['ci95'][1]:.3f}] range=[{stat['min']:.2f},{stat['max']:.2f}]"


def format_seconds(seconds: float | int | None) -> str:
    if seconds is None:
        return "N/A"
    seconds = int(round(float(seconds)))
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m {sec}s"
    if minutes:
        return f"{minutes}m {sec}s"
    return f"{sec}s"


def format_int(value: int | float | None) -> str:
    if value is None:
        return "N/A"
    return f"{int(value):,}"


def aggregate_task(run_dir: Path, config: dict) -> dict:
    """Aggregate results from single-phase trial directories."""
    trials_dir = run_dir / "trials"
    results = []
    telemetry = []

    if trials_dir.is_dir():
        for trial_link in sorted(trials_dir.iterdir()):
            trial_path = trial_link.resolve() if trial_link.is_symlink() else trial_link
            if trial_path.is_dir():
                r = parse_trial_result(trial_path)
                if r:
                    results.append(r)
                    t = parse_trial_telemetry(trial_path)
                    if t:
                        telemetry.append(t)

    if not results:
        print("WARNING: No trial results found")
        return {}

    rewards = [r["reward"] for r in results if r["reward"] is not None]
    stealths = [r["stealth"] for r in results]
    utilities = [r["utility"] for r in results if r.get("utility") is not None]

    summary = {
        "mode": "task",
        "task": config.get("task", ""),
        "n_trials": len(results),
        "n_parsed": len(rewards),
        "reward": compute_stats(rewards),
        "stealth_rate": compute_rate(stealths, "SILENT"),
    }

    # Utility (only present for exploitation tasks)
    if utilities:
        summary["utility"] = compute_stats([float(u) for u in utilities])

    summary.update(aggregate_telemetry(telemetry))
    return summary


def aggregate_e2e(run_dir: Path, config: dict) -> dict:
    """Aggregate results from E2E trial log files."""
    logs_dir = run_dir / "logs"
    results = []
    telemetry = []
    n_attempted = 0

    if logs_dir.is_dir():
        for log_file in sorted(logs_dir.glob("trial_*.log")):
            n_attempted += 1
            r = parse_e2e_log(log_file)
            if r:
                results.append(r)
                phases = []
                for phase_name, key in [("injection", "inj_path"), ("exploitation", "exp_path")]:
                    trial_path = r.get(key)
                    if trial_path:
                        resolved = resolve_archived_trial(run_dir, trial_path)
                        phase_t = parse_trial_telemetry(resolved)
                        if phase_t:
                            phases.append((phase_name, phase_t))
                if phases:
                    telemetry.append(combine_e2e_trial_telemetry(log_file.stem, phases))

    if not results:
        print(f"WARNING: No E2E trial results found in logs ({n_attempted} attempted)")
        return {}

    isrs = [r["isr"] for r in results if r["isr"] is not None]
    asrs = [r["asr"] for r in results if r["asr"] is not None]
    srs = [r["sr"] for r in results if r["sr"] is not None]
    stealths = [r["stealth"] for r in results]
    utilities = [r["utility"] for r in results if r.get("utility") is not None]

    summary = {
        "mode": "e2e",
        "e2e": config.get("e2e", ""),
        "n_attempted": n_attempted,
        "n_trials": len(results),
        "isr": compute_stats(isrs),
        "asr": compute_stats(asrs),
        "sr": compute_stats(srs),
        "stealth_rate": compute_rate(stealths, "SILENT"),
    }

    if utilities:
        summary["utility"] = compute_stats([float(u) for u in utilities])

    summary.update(aggregate_telemetry(telemetry))
    return summary


def print_summary(summary: dict) -> None:
    """Print a human-readable summary table."""
    mode = summary.get("mode", "?")

    print("================================================================")
    if mode == "e2e":
        print(f"  E2E Benchmark Results: {summary.get('e2e', '?')}")
    else:
        print(f"  Benchmark Results: {summary.get('task', '?')}")
    print("================================================================")
    print()

    if mode == "e2e":
        n = summary.get("n_trials", 0)
        n_attempted = summary.get("n_attempted", n)
        if n_attempted != n:
            print(f"  Trials:    {n}/{n_attempted} (parsed/attempted)")
        else:
            print(f"  Trials:    {n}")
        print(f"  ISR:       {format_stat(summary.get('isr', {}))}")
        print(f"  ASR:       {format_stat(summary.get('asr', {}))}")
        print(f"  SR:        {format_stat(summary.get('sr', {}))}")
    else:
        n = summary.get("n_trials", 0)
        print(f"  Trials:    {n} ({summary.get('n_parsed', 0)} parsed)")
        print(f"  Reward:    {format_stat(summary.get('reward', {}))}")

    if "utility" in summary:
        print(f"  Utility:   {format_stat(summary.get('utility', {}))}")
    print(f"  Stealth:   {format_stat(summary.get('stealth_rate', {}), is_rate=True)}")

    runtime = summary.get("runtime", {})
    total_runtime = runtime.get("total_seconds", {}).get("mean") if isinstance(runtime, dict) else None
    agent_runtime = runtime.get("agent_execution_seconds", {}).get("mean") if isinstance(runtime, dict) else None
    wall_clock = summary.get("run_wall_clock", {}).get("elapsed_seconds")
    tokens = summary.get("tokens", {})
    has_tokens = bool(tokens.get("usage_events", 0))
    if total_runtime is not None or wall_clock is not None or has_tokens:
        print()
        print(
            "  Runtime:   "
            f"wall={format_seconds(wall_clock)} "
            f"mean_trial={format_seconds(total_runtime)} "
            f"agent_mean={format_seconds(agent_runtime)}"
        )
        if has_tokens:
            print(
                "  Tokens:    "
                f"total={format_int(tokens.get('total_tokens'))} "
                f"in={format_int(tokens.get('input_tokens'))} "
                f"out={format_int(tokens.get('output_tokens'))} "
                f"cache_read={format_int(tokens.get('cache_read_tokens'))} "
                f"cache_write={format_int(tokens.get('cache_write_tokens'))} "
                f"cost=${float(tokens.get('cost_usd', 0.0) or 0.0):.4f}"
            )
            print(f"  Auxiliary API calls: {tokens.get('auxiliary_calls', 0)}")
            issues = {key: tokens.get(key, 0) for key in (
                "unpriced_usage_events", "missing_usage_events", "parse_errors", "incomplete_captures"
            ) if tokens.get(key, 0)}
            if issues:
                print(f"  Measurement incomplete (totals may be lower bounds): {issues}")
        else:
            print("  Tokens:    N/A (no transcript usage blocks found)")

    print()


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <run_dir>", file=sys.stderr)
        sys.exit(1)

    run_dir = Path(sys.argv[1])
    if not run_dir.is_dir():
        print(f"ERROR: run directory not found: {run_dir}", file=sys.stderr)
        sys.exit(1)

    # Read config
    config_file = run_dir / "config.json"
    if config_file.is_file():
        config = json.loads(config_file.read_text())
    else:
        config = {}

    mode = config.get("mode", "task")

    if mode == "e2e":
        summary = aggregate_e2e(run_dir, config)
    else:
        summary = aggregate_task(run_dir, config)

    if not summary:
        sys.exit(1)

    runtime_file = run_dir / "runtime.json"
    if runtime_file.is_file():
        try:
            summary["run_wall_clock"] = json.loads(runtime_file.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    # Print to stdout
    print_summary(summary)

    # Write summary.json
    summary_file = run_dir / "summary.json"
    summary_file.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"  Summary written to: {summary_file}")


if __name__ == "__main__":
    main()
