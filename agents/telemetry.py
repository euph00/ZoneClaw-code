"""Shared measurement wrapper for user-triggered and heartbeat tasks."""

import json
import logging
import math
import os
import shlex
import time
from functools import wraps
from pathlib import Path


def measurement_metadata():
    metadata = {"expected_helpers": [], "prices": {}}
    if os.environ.get("BENCH_RAW_API_CAPTURE") == "alibaba":
        metadata["raw_api_provider"] = "alibaba"
    config_path = os.environ.get("BENCH_OPENCLAW_CONFIG_FILE")
    if config_path:
        config = json.loads(Path(config_path).read_text())
        plugins = config.get("plugins", {})
        if plugins.get("enabled", True):
            metadata["expected_helpers"] = [
                name for name, entry in plugins.get("entries", {}).items()
                if name in ("memory-write-auditor", "melon-runtime") and entry.get("enabled", True)
            ]
    prices_path = os.environ.get("BENCH_TOKEN_PRICES_FILE")
    if prices_path:
        prices = json.loads(Path(prices_path).read_text())
        for model, entry in prices.items():
            if "/" not in model or not entry.get("source"):
                raise ValueError("Prices require provider/model keys and a source")
            rates = {}
            for key in ("input", "output", "cacheRead", "cacheWrite"):
                value = float(entry[key])
                if not math.isfinite(value) or value < 0:
                    raise ValueError(f"Invalid {key} price for {model}")
                rates[key] = value
            metadata["prices"][model] = {**rates, "source": str(entry["source"])}
    return metadata


def measured_run(run):
    @wraps(run)
    async def measured(self, instruction, environment, context):
        metadata = measurement_metadata()
        script = Path(__file__).with_name("telemetry_capture.py").read_text()
        errors = []
        measurement_seconds = 0.0
        completed = False

        async def archive(mode):
            nonlocal measurement_seconds
            started = time.monotonic()
            try:
                command = f"python3 -c {shlex.quote(script)} {mode}"
                payload = metadata if mode == "begin" else {"agent_completed": completed}
                command += " --metadata " + shlex.quote(json.dumps(payload))
                result = await environment.exec(command, timeout_sec=30)
                if result.return_code:
                    errors.append(f"{mode} capture exited {result.return_code}")
            except Exception as exc:
                errors.append(f"{mode} capture: {type(exc).__name__}")
            finally:
                measurement_seconds += time.monotonic() - started

        await archive("begin")
        try:
            result = await run(self, instruction, environment, context)
            completed = True
            return result
        finally:
            # Runs after the heartbeat follow-up, and on agent failure/timeout.
            await archive("end")
            if context.metadata is None:
                context.metadata = {}
            context.metadata["telemetry_capture_seconds"] = round(measurement_seconds, 3)
            context.metadata["telemetry_capture_errors"] = errors
            if errors:
                logging.getLogger(__name__).warning("Telemetry capture incomplete: %s", errors)
    return measured
