#!/usr/bin/env python3
"""Run and aggregate independent longitudinal trajectories."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
import json
import math
import os
from pathlib import Path
import random
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts" / "longitudinal" / "runner.py"


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def wilson(values: list[float]) -> list[float]:
    n = len(values)
    if not n:
        return [0.0, 0.0]
    successes = sum(values)
    z = 1.96
    denominator = 1 + z * z / n
    center = (successes / n + z * z / (2 * n)) / denominator
    margin = z * math.sqrt(
        successes / n * (1 - successes / n) / n + z * z / (4 * n * n)
    ) / denominator
    return [max(0.0, center - margin), min(1.0, center + margin)]


def bootstrap_ci(values: list[float], samples: int = 10000) -> list[float]:
    if not values:
        return [0.0, 0.0]
    mean = sum(values) / len(values)
    if len(values) == 1:
        return [mean, mean]
    generator = random.Random(0)
    means = sorted(
        sum(generator.choice(values) for _ in values) / len(values)
        for _ in range(samples)
    )
    lower = means[int(0.025 * (samples - 1))]
    upper = means[int(0.975 * (samples - 1))]
    return [max(0.0, lower), min(1.0, upper)]


def run_one(args: argparse.Namespace, output: Path, index: int) -> dict[str, Any]:
    trajectory = output / "trajectories" / f"trial-{index:03d}"
    log_path = output / "logs" / f"trial-{index:03d}.log"
    command = [
        sys.executable,
        str(RUNNER),
        "--config",
        str(args.config),
        "--system",
        args.system,
        "--schedule",
        args.schedule,
        "--output",
        str(trajectory),
        "--checkpoints",
        *(str(value) for value in args.checkpoints),
        "--timeline-end-date",
        args.timeline_end_date,
    ]
    if args.model:
        command.extend(("--model", args.model))
    if args.thinking:
        command.extend(("--thinking", args.thinking))
    with log_path.open("w") as log:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=os.environ.copy(),
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )
    manifest = trajectory / "trajectory.json"
    return {
        "trial": index,
        "returncode": completed.returncode,
        "trajectory": str(trajectory),
        "log": str(log_path),
        "manifest": str(manifest) if manifest.is_file() else None,
    }


def aggregate(output: Path, runs: list[dict[str, Any]]) -> dict[str, Any]:
    complete: list[dict[str, Any]] = []
    for run in runs:
        if run["returncode"] != 0 or not run["manifest"]:
            continue
        manifest = json.loads(Path(run["manifest"]).read_text())
        if manifest.get("status") == "complete":
            complete.append(manifest)

    metric_paths = {
        "ISR": ("workspace_scores", "attack_persistence"),
        "CSR": ("workspace_scores", "attack_authority_crossing"),
        "ASR": ("asr",),
        "Utility": ("utility",),
        "FixedRecall": ("fixed_recall",),
        "LongitudinalRecall": ("longitudinal_recall",),
        "Supersession": ("supersession_ok",),
        "DuplicateAction": ("duplicate_action",),
        "FalsePromotion": ("workspace_scores", "false_promotion_rate"),
    }
    binary_metrics = {
        "ISR", "CSR", "ASR", "Utility", "Supersession", "DuplicateAction"
    }
    by_horizon: dict[int, list[dict[str, Any]]] = {}
    for manifest in complete:
        for checkpoint in manifest.get("checkpoint_results", []):
            by_horizon.setdefault(int(checkpoint["horizon"]), []).append(checkpoint)

    checkpoints: dict[str, Any] = {}
    for horizon, rows in sorted(by_horizon.items()):
        metrics: dict[str, Any] = {}
        for name, path in metric_paths.items():
            values: list[float] = []
            for row in rows:
                value: Any = row
                for component in path:
                    value = value.get(component) if isinstance(value, dict) else None
                if value is not None:
                    values.append(float(value))
            if not values:
                metrics[name] = None
                continue
            metrics[name] = {
                "n": len(values),
                "mean": sum(values) / len(values),
                "ci95": wilson(values) if name in binary_metrics else bootstrap_ci(values),
                "method": "Wilson" if name in binary_metrics else "trajectory bootstrap",
            }
        checkpoints[str(horizon)] = {"n": len(rows), "metrics": metrics}

    summary = {
        "requested": len(runs),
        "complete": len(complete),
        "failed": [run for run in runs if run["returncode"] != 0],
        "checkpoints": checkpoints,
    }
    write_json(output / "summary.json", summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--system", required=True)
    parser.add_argument("--schedule", required=True)
    parser.add_argument("-N", type=int, default=3)
    parser.add_argument("-P", type=int, default=1)
    parser.add_argument("--model", default=os.environ.get("MODEL", ""))
    parser.add_argument("--thinking", default=os.environ.get("OPENCLAW_THINKING", ""))
    parser.add_argument(
        "--timeline-end-date",
        default=os.environ.get("TIMELINE_END_DATE", date.today().isoformat()),
    )
    parser.add_argument("--checkpoints", type=int, nargs="+", default=[0, 1, 2, 3, 5, 10])
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.N < 1 or args.P < 1:
        raise SystemExit("N and P must be positive")
    output = args.output or (
        ROOT
        / "runs"
        / (
            datetime.now().strftime("%Y-%m-%d__%H-%M-%S")
            + f"__longitudinal-{args.system}-{args.schedule}"
        )
    )
    output = output.resolve()
    (output / "logs").mkdir(parents=True, exist_ok=False)
    (output / "trajectories").mkdir()
    write_json(
        output / "config.json",
        {
            "config": str(args.config.resolve()),
            "system": args.system,
            "schedule": args.schedule,
            "model": args.model or None,
            "thinking": args.thinking or None,
            "timeline_end_date": args.timeline_end_date,
            "N": args.N,
            "P": args.P,
            "checkpoints": args.checkpoints,
        },
    )

    runs = [run_one(args, output, 1)]
    if runs[0]["returncode"] != 0:
        summary = aggregate(output, runs)
        print(json.dumps(summary, indent=2))
        print(f"First trajectory failed; stopping. See {runs[0]['log']}")
        return 1

    if args.N > 1:
        with ThreadPoolExecutor(max_workers=args.P) as executor:
            futures = {
                executor.submit(run_one, args, output, index): index
                for index in range(2, args.N + 1)
            }
            for future in as_completed(futures):
                runs.append(future.result())
    runs.sort(key=lambda item: item["trial"])
    summary = aggregate(output, runs)
    print(json.dumps(summary, indent=2))
    print(f"Run directory: {output}")
    return 0 if summary["complete"] == args.N else 1


if __name__ == "__main__":
    raise SystemExit(main())
