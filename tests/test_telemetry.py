import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from aggregate import (
    aggregate_telemetry, combine_e2e_trial_telemetry, empty_usage,
    parse_transcript_usage, parse_trial_telemetry, resolve_archived_trial,
    usage_from_message,
)
from agents.telemetry import measured_run, measurement_metadata
from agents.telemetry_capture import capture


RATES = {"input": 2, "output": 4, "cacheRead": 0.5, "cacheWrite": 2.5, "source": "test fixture"}


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record) + "\n" for record in records))


def model_record(identifier="m1", provider="test", model="model"):
    return {"id": identifier, "message": {
        "role": "assistant", "provider": provider, "model": model,
        "usage": {"input": 80, "output": 20, "cacheRead": 10, "cacheWrite": 5},
    }}


class NormalizationTests(unittest.TestCase):
    def test_canonical_cache_and_prices(self):
        usage = usage_from_message(model_record()["message"], {"test/model": RATES})
        self.assertEqual(usage["total_tokens"], 115)
        self.assertAlmostEqual(usage["cost_usd"], 0.0002575)
        self.assertEqual(usage["unpriced_usage_events"], 0)

    def test_openai_cache_and_reasoning_are_not_added_twice(self):
        usage = usage_from_message({"usage": {
            "prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120,
            "prompt_tokens_details": {"cached_tokens": 80},
            "completion_tokens_details": {"reasoning_tokens": 15},
        }})
        self.assertEqual(usage["input_tokens"], 20)
        self.assertEqual(usage["cache_read_tokens"], 80)
        self.assertEqual(usage["output_tokens"], 20)
        self.assertEqual(usage["reasoning_tokens"], 15)
        self.assertEqual(usage["total_tokens"], 120)

    def test_anthropic_cache_is_additional(self):
        usage = usage_from_message({"usage": {
            "input_tokens": 80, "output_tokens": 20,
            "cache_read_input_tokens": 10, "cache_creation_input_tokens": 5,
        }})
        self.assertEqual(usage["total_tokens"], 115)

    def test_placeholder_zero_prices_are_unknown(self):
        message = model_record()["message"]
        message["usage"]["cost"] = {"total": 0}
        self.assertEqual(usage_from_message(message)["unpriced_usage_events"], 1)

    def test_recorded_price_preserved(self):
        message = model_record()["message"]
        message["usage"]["cost"] = {"total": 0.1}
        self.assertEqual(usage_from_message(message)["cost_usd"], 0.1)
        self.assertEqual(usage_from_message(message)["unpriced_usage_events"], 0)

    def test_negative_counts_rejected(self):
        with self.assertRaises(ValueError):
            usage_from_message({"usage": {"input": -1}})


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / "state"
        self.artifacts = self.root / "artifacts"
        self.session = self.state / "agents/main/sessions/session.jsonl"
        self.ledger = self.state / "telemetry/provider-requests.jsonl"

    def test_capture_all_roles_followup_and_helper_without_restored_usage(self):
        write_jsonl(self.session, [model_record("old")])
        write_jsonl(self.ledger, [
            {"kind": "init", "component": "melon-runtime"},
            {"kind": "finish", "call_id": "old", "usage": {"input_tokens": 999}},
        ])
        capture(self.state, self.artifacts, "begin", {
            "expected_helpers": ["melon-runtime"],
            "prices": {"test/model": RATES, "anthropic/helper": RATES},
        })
        write_jsonl(self.session, [model_record("old"), model_record("new")])
        write_jsonl(self.state / "agents/worker/sessions/worker.jsonl", [model_record("old"), model_record("worker")])
        write_jsonl(self.state / "agents/main/sessions/followup.jsonl", [model_record("followup")])
        with self.ledger.open("a") as handle:
            for record in [
                {"kind": "start", "call_id": "new"},
                {"kind": "finish", "call_id": "new", "provider": "anthropic", "model": "helper",
                 "status": "ok", "usage": {"input_tokens": 80, "output_tokens": 20}},
            ]:
                handle.write(json.dumps(record) + "\n")
        manifest = capture(self.state, self.artifacts, "end")
        self.assertEqual(manifest["status"], "complete")
        self.assertEqual(manifest["transcript_files"], 3)
        usage = parse_transcript_usage(self.root)
        self.assertEqual(usage["total_tokens"], 3 * 115 + 100)
        self.assertEqual(usage["usage_events"], 4)
        self.assertEqual(usage["auxiliary_calls"], 1)
        self.assertEqual(usage["auxiliary_usage_events"], 1)
        self.assertEqual(usage["by_model"]["anthropic/helper"]["total_tokens"], 100)
        self.assertEqual(usage["unpriced_usage_events"], 0)
        self.assertFalse((self.state / "workspace").exists())

    def test_missing_helper_instrumentation_is_explicit(self):
        capture(self.state, self.artifacts, "begin", {"expected_helpers": ["melon-runtime"]})
        write_jsonl(self.session, [model_record()])
        result = capture(self.state, self.artifacts, "end")
        self.assertEqual(result["status"], "incomplete")
        self.assertIn("missing helper instrumentation", result["errors"][0])

    def test_registered_helper_with_no_requests_is_valid_zero(self):
        write_jsonl(self.ledger, [{"kind": "init", "component": "memory-write-auditor"}])
        capture(self.state, self.artifacts, "begin", {"expected_helpers": ["memory-write-auditor"]})
        write_jsonl(self.session, [model_record()])
        self.assertEqual(capture(self.state, self.artifacts, "end")["status"], "complete")
        self.assertEqual(parse_transcript_usage(self.root)["auxiliary_calls"], 0)

    def test_missing_begin_and_no_sessions_flagged(self):
        self.assertEqual(capture(self.state, self.artifacts, "end")["status"], "incomplete")

    def test_duplicate_archives_and_corrupt_records(self):
        write_jsonl(self.artifacts / "transcripts/a.jsonl", [model_record()])
        write_jsonl(self.artifacts / "transcripts/b.jsonl", [model_record()])
        with (self.artifacts / "transcripts/b.jsonl").open("a") as handle:
            handle.write("{broken\n")
        usage = parse_transcript_usage(self.root)
        self.assertEqual(usage["usage_events"], 1)
        self.assertEqual(usage["parse_errors"], 1)

    def test_unfinished_request_not_reported_as_free_success(self):
        write_jsonl(self.artifacts / "telemetry/provider-requests.jsonl", [
            {"kind": "start", "call_id": "interrupted"},
        ])
        usage = parse_transcript_usage(self.root)
        self.assertEqual(usage["auxiliary_calls"], 1)
        self.assertEqual(usage["missing_usage_events"], 1)
        self.assertEqual(usage["error_calls"], 1)

    def test_duplicate_finishes_and_retry_calls(self):
        event = {"kind": "finish", "call_id": "success", "provider": "anthropic", "model": "helper",
                 "status": "ok", "usage": {"input_tokens": 80, "output_tokens": 20}}
        write_jsonl(self.artifacts / "telemetry/provider-requests.jsonl", [
            {"kind": "finish", "call_id": "error", "status": "http_429", "usage": None},
            event, event,
        ])
        usage = parse_transcript_usage(self.root)
        self.assertEqual(usage["total_tokens"], 100)
        self.assertEqual(usage["auxiliary_calls"], 2)
        self.assertEqual(usage["missing_usage_events"], 1)
        self.assertEqual(usage["error_calls"], 1)

    def test_totals_include_auxiliaries_once_across_phases(self):
        write_jsonl(self.artifacts / "transcripts/a.jsonl", [model_record()])
        (self.root / "result.json").write_text(json.dumps({
            "agent_execution": {"started_at": "2026-09-09T00:00:00Z", "finished_at": "2026-09-09T00:00:10Z"},
        }))
        trial = parse_trial_telemetry(self.root)
        e2e = combine_e2e_trial_telemetry("test", [("injection", trial), ("exploitation", trial)])
        summary = aggregate_telemetry([e2e])
        self.assertEqual(summary["tokens"]["total_tokens"], 230)
        self.assertEqual(summary["tokens"]["by_model"]["test/model"]["total_tokens"], 230)
        self.assertEqual(e2e["runtime"]["agent_execution_seconds"], 20)

    def test_partial_e2e_flagged(self):
        trial = {"tokens": empty_usage(), "runtime": {}}
        combined = combine_e2e_trial_telemetry("test", [("injection", trial)])
        self.assertEqual(combined["tokens"]["incomplete_captures"], 1)

    def test_raw_wire_usage_replaces_inflated_adapter_counts(self):
        write_jsonl(self.state / "telemetry/raw-api.jsonl", [{"kind": "init", "provider": "alibaba"}])
        capture(self.state, self.artifacts, "begin", {
            "raw_api_provider": "alibaba", "prices": {"alibaba/qwen": RATES},
        })
        record = model_record(provider="alibaba", model="qwen")
        record["message"]["usage"] = {"input": 100, "output": 65, "totalTokens": 165}
        write_jsonl(self.session, [record])
        write_jsonl(self.state / "telemetry/raw-api.jsonl", [
            {"kind": "init", "provider": "alibaba"},
            {"kind": "start", "call_id": "one"},
            {"kind": "finish", "call_id": "one", "provider": "alibaba", "model": "qwen", "status": "ok",
             "usage": {"prompt_tokens": 100, "completion_tokens": 40, "total_tokens": 140,
                       "completion_tokens_details": {"reasoning_tokens": 25}}},
        ])
        capture(self.state, self.artifacts, "end")
        usage = parse_transcript_usage(self.root)
        self.assertEqual(usage["total_tokens"], 140)
        self.assertEqual(usage["output_tokens"], 40)
        self.assertEqual(usage["reasoning_tokens"], 25)
        self.assertEqual(usage["raw_api_replacements"], 1)
        self.assertEqual(usage["raw_api_calls"], 1)
        self.assertEqual(usage["usage_events"], 1)
        self.assertEqual(usage["unpriced_usage_events"], 0)

    def test_packaged_trial_resolves_without_original_harbor_path(self):
        archived = "/unavailable/jobs/trial_001-inj/injection-userprompt__abc123"
        direct = self.root / "trials" / "injection-userprompt__abc123"
        direct.mkdir(parents=True)
        self.assertEqual(resolve_archived_trial(self.root, archived), direct)

        direct.rmdir()
        prefixed = self.root / "trials" / "trial_001-inj__injection-userprompt__abc123"
        prefixed.mkdir()
        self.assertEqual(resolve_archived_trial(self.root, archived), prefixed)

    def test_missing_raw_capture_is_not_treated_as_zero_usage(self):
        capture(self.state, self.artifacts, "begin", {"raw_api_provider": "alibaba"})
        write_jsonl(self.session, [model_record(provider="alibaba")])
        capture(self.state, self.artifacts, "end")
        self.assertGreater(parse_transcript_usage(self.root)["incomplete_captures"], 0)


class WrapperTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_failure_and_cancellation_all_archive(self):
        for error in (None, RuntimeError("agent failed"), asyncio.CancelledError()):
            with self.subTest(error=error), patch.dict(os.environ, {}, clear=True):
                calls = []

                class Environment:
                    async def exec(self, command, **kwargs):
                        calls.append(command)
                        return SimpleNamespace(return_code=0)

                @measured_run
                async def run(self, instruction, environment, context):
                    calls.append("heartbeat")
                    calls.append("followup")
                    context.metadata = {"original": True}
                    if error:
                        raise error
                    return "unchanged"

                context = SimpleNamespace(metadata={})
                if error:
                    with self.assertRaises(type(error)):
                        await run(None, "task", Environment(), context)
                else:
                    self.assertEqual(await run(None, "task", Environment(), context), "unchanged")
                self.assertIn(" begin --metadata ", calls[0])
                self.assertIn(" end --metadata ", calls[-1])
                self.assertIn('"agent_completed": ' + ("false" if error else "true"), calls[-1])
                self.assertEqual(calls[1:3], ["heartbeat", "followup"])
                self.assertTrue(context.metadata["original"])
                self.assertEqual(context.metadata["telemetry_capture_errors"], [])

    async def test_capture_error_does_not_change_response(self):
        class Environment:
            async def exec(self, command, **kwargs):
                return SimpleNamespace(return_code=1)

        @measured_run
        async def run(self, instruction, environment, context):
            return "unchanged"

        with patch.dict(os.environ, {}, clear=True):
            context = SimpleNamespace(metadata=None)
            with self.assertLogs("agents.telemetry", level="WARNING"):
                self.assertEqual(await run(None, "task", Environment(), context), "unchanged")
            self.assertEqual(len(context.metadata["telemetry_capture_errors"]), 2)


class MetadataTests(unittest.TestCase):
    def test_config_and_prices_archive_only_allowlisted_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config.json"
            config.write_text(json.dumps({
                "secret": "MUST_NOT_APPEAR",
                "plugins": {"entries": {"melon-runtime": {"enabled": True, "config": {"secret": "MUST_NOT_APPEAR"}}}},
            }))
            prices = root / "prices.json"
            prices.write_text(json.dumps({"test/model": {**RATES, "secret": "MUST_NOT_APPEAR"}}))
            with patch.dict(os.environ, {"BENCH_OPENCLAW_CONFIG_FILE": str(config), "BENCH_TOKEN_PRICES_FILE": str(prices)}, clear=True):
                metadata = measurement_metadata()
            self.assertNotIn("MUST_NOT_APPEAR", json.dumps(metadata))
            self.assertEqual(metadata["expected_helpers"], ["melon-runtime"])
            self.assertEqual(metadata["prices"]["test/model"], RATES)


if __name__ == "__main__":
    unittest.main()
