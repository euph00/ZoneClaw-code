# Run Measurements

Both agent adapters archive main-agent and worker session JSONL files to each
phase's `artifacts/transcripts/`. Capture runs after the task, including the
heartbeat follow-up, and is attempted on failure as well. A killed container or
interrupted request can still prevent complete measurement.

Watcher and MELON also record direct helper API calls outside the agent workspace
in `.openclaw/telemetry/provider-requests.jsonl`. Copies are archived under
`artifacts/telemetry/`. These records contain model identifiers, usage counters,
request identifiers, status, and duration; no prompts, responses, or credentials.
Each actual helper request is recorded once. A cached detector decision that
does not call the provider is not counted as another request.

`artifacts/telemetry/capture.json` records capture coverage, starting file
positions, expected helper instrumentation, and any supplied price schedule.
Starting positions exclude pre-existing session history and helper events.
Measurement errors do not change agent responses or defense decisions.

## Summary

`python3 aggregate.py runs/<run>` includes helper usage in the existing token and
estimated-cost totals. `tokens.by_model` keeps the main and helper model totals
available for inspection without requiring a detailed paper table.
Packaged runs remain self-contained: if a raw log's original Harbor path is not
available, aggregation resolves the corresponding copy under the package's
`trials/` directory.

- Total tokens include input, output, cache reads, and cache writes.
- OpenAI-style cached input is already part of prompt tokens and is not added twice.
- Reported reasoning tokens are a subset of output tokens, not an additional charge.
  The detail is available only when retained by the provider adapter.
- Agent execution time includes tool calls and helper waits. Concurrent worker
  durations are not added together. End-to-end time sums the two phase durations,
  with environment setup and verification reported separately.
- Capture overhead is recorded as `telemetry_capture_seconds` in agent metadata.
- Unknown prices, missing responses, malformed usage, and incomplete capture are
  flagged. Recorded totals may then be lower bounds, not complete costs.

## Price Estimates

By default, aggregation uses the cost estimates recorded by OpenClaw. Custom
providers often have zero-price placeholders; these are flagged as unpriced when
tokens were consumed. Helper usage without a price schedule is also unpriced.

To price the next runs consistently, set `BENCH_TOKEN_PRICES_FILE` to an absolute
path to a JSON object keyed by `provider/model`. Each entry must provide `input`,
`output`, `cacheRead`, and `cacheWrite` rates in USD per million tokens, plus a
`source` identifying the applicable price schedule and date. Include both the
main model and the actual helper model. The validated rates are archived with
each phase and override transcript estimates for those models during aggregation.
Explicit zero rates are permitted only when supplied in this price schedule.
These are estimates at the stated rates, not an account billing statement.

For measured Alibaba Qwen runs, `run.sh` selects a measurement-only image derived
from `openclaw:local`. The pinned OpenClaw code is not changed. A fetch observer
archives numeric provider usage and request-setting metadata to
`telemetry/raw-api.jsonl`, without storing message text or changing request or
response bytes. Aggregation uses these counters instead of the adapter's normalized
usage for Alibaba calls: the installed pi-ai 0.55.3 adapter adds reasoning tokens
to completion tokens, whereas Qwen already includes them in the completion total.
Interrupted requests and missing raw capture remain explicitly flagged.

For example, the pinned standard Anthropic rates for the telemetry smoke are in
`experiments/measurement/anthropic-2026-09-09.json` (5-minute cache writes):

```bash
BENCH_TOKEN_PRICES_FILE="$PWD/experiments/measurement/anthropic-2026-09-09.json" \
  MODEL=anthropic/claude-sonnet-4-6 E2E=bcc-auditor-userprompt N=1 P=1 bash bench.sh
```

The paper's Qwen configuration uses Qwen3.7 Plus, medium thinking, and a
32,768-token completion cap (including reasoning):

```bash
BENCH_TOKEN_PRICES_FILE="$PWD/experiments/measurement/qwen3.7-plus-2026-05-26.json" \
  MODEL=alibaba/qwen3.7-plus-2026-05-26 OPENCLAW_THINKING=medium \
  E2E=bcc-userprompt N=1 P=1 bash bench.sh
```

Qwen3.7 uses the adapter's Qwen thinking format. `OPENCLAW_THINKING=medium`
therefore enables thinking, but is not sent as an OpenAI-style reasoning-effort
field. Captured request settings and reasoning-history counts verify the actual
behavior before scaling up. The model preset applies equally to worker agents
inheriting the selected model. Haiku-based helper configurations remain unchanged.
The price file uses Beijing list rates and implicit cache reads.

Instrumentation is model- and scenario-independent. Choose and label the cost
table's task/setting scope explicitly; retain all repetitions within that scope
rather than selecting individual trials by favorable cost or outcome.
