# ZoneClaw

Experiment code for **ZoneClaw: Mitigating Persistent Memory Attack by Establishing Memory-Zoning among OpenClaw-Style Computer-Use Agents**.

This repository contains the benchmark tasks, defense implementations, and evaluation scripts used in the paper. The benchmark studies cross-session persistent memory attacks in OpenClaw-style computer-use agents. It covers two attack classes:

- **Hidden side effects:** BCC exfiltration and chat mirroring.
- **Provenance corruption:** source redirection and marketplace redirection.

ZoneClaw separates retained external observations from authority-bearing memory, then uses role-separated agents to observe, classify, and act on persistent information.

This code-only edition does not bundle experiment results. The paper's transcripts,
verifier evidence, and summaries are available in the
accompanying artifact repository.

## Setup

### Prerequisites

- Linux or WSL2 (tested on Ubuntu 24.04 under WSL2, x86-64)
- Docker with Compose support
- Git
- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/)

Allow at least 20 GB of free disk space for dependencies, Docker images, and generated runs. We recommend 16 GB of RAM for parallel experiments. Initial setup typically takes 10-20 minutes, depending on the network and Docker build cache.

For an anonymous download, extract the ZIP, open a terminal in its top-level directory, and run:

```bash
bash setup.sh
```

Setup fetches the pinned OpenClaw, Harbor, and WorkspaceBench dependencies directly from their public upstream repositories. No access to the original private repository is needed.

For a Git checkout, replace `<repository-url>` below with the repository's clone URL:

```bash
git clone --depth 1 --recurse-submodules --shallow-submodules \
  <repository-url> ZoneClaw-code
cd ZoneClaw-code
bash setup.sh
```

The script validates the local tools and Docker daemon, builds the required images, and creates `.env` from `.env.example`. It generates `OPENCLAW_GATEWAY_TOKEN` locally; edit `.env` only to set the provider keys needed for a run. Do not commit `.env`.

| Experiment | Required API keys |
| --- | --- |
| Anthropic main model | `ANTHROPIC_API_KEY` |
| OpenAI main model | `OPENAI_API_KEY` |
| Z.AI main model | `ZAI_API_KEY` |
| Alibaba Qwen main model | `ALIBABA_KEY` |
| Watcher or MELON with a non-Anthropic main model | Main-model key and `ANTHROPIC_API_KEY` |
| WorkspaceBench authority and benign-utility evaluations | `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` |

Experiments make paid provider calls. Start with one trial to verify the complete path:

```bash
MODEL=anthropic/claude-sonnet-4-6 \
E2E=bcc-zoneclaw-userprompt N=1 P=1 bash bench.sh
```

The main paper experiments use Claude Sonnet 4.6. After the smoke test succeeds, reproduce the full row with:

```bash
MODEL=anthropic/claude-sonnet-4-6 \
E2E=bcc-zoneclaw-userprompt N=15 P=3 bash bench.sh
```

Outputs are written to `runs/<timestamp>__e2e-<experiment>/`. The command prints a per-trial breakdown after aggregation; an existing run can be viewed again with:

```bash
bash show-bench.sh runs/<run-directory>
```

## Main Attack and Mitigation Experiments

Named end-to-end experiments follow:

```text
<scenario>[-<defense>]-<setting>
```

| Paper term | Command token |
| --- | --- |
| BCC exfiltration | `bcc` |
| Chat mirror | `chat` |
| Source redirection | `sr` |
| Marketplace redirection | `market` |
| User-triggered update | `userprompt` |
| Periodic update | `heartbeat` |
| No defense | omit the defense token |
| ClawKeeper-style Watcher | `auditor` |
| Privilege separation | `privsep` |
| ClawGuard | `clawguard` |
| MELON | `melon` |
| ZoneClaw | `zoneclaw` |

Examples:

```bash
# Undefended BCC, user-triggered update
MODEL=anthropic/claude-sonnet-4-6 \
E2E=bcc-userprompt N=15 P=3 bash bench.sh

# ClawKeeper-style Watcher, periodic Chat Mirror update
MODEL=anthropic/claude-sonnet-4-6 \
E2E=chat-auditor-heartbeat N=15 P=3 bash bench.sh

# ZoneClaw, user-triggered source-redirection update
MODEL=anthropic/claude-sonnet-4-6 \
E2E=sr-zoneclaw-userprompt N=15 P=3 bash bench.sh
```

All valid names and their injection/exploitation task pairs are listed in `experiments/e2e.tsv`.

To use another supported model, replace `MODEL`; for example:

```bash
MODEL=openai/gpt-5.5 OPENCLAW_THINKING=medium \
E2E=bcc-zoneclaw-userprompt N=15 P=3 bash bench.sh

MODEL=zai/glm-5.2 \
E2E=bcc-zoneclaw-userprompt N=15 P=3 bash bench.sh

BENCH_TOKEN_PRICES_FILE="$PWD/experiments/measurement/qwen3.7-plus-2026-05-26.json" \
MODEL=alibaba/qwen3.7-plus-2026-05-26 OPENCLAW_THINKING=medium \
E2E=bcc-zoneclaw-userprompt N=15 P=3 bash bench.sh
```

Measured runs archive per-phase runtime, model usage, and helper-model usage
alongside each trial. Alibaba Qwen runs additionally retain a content-free raw
usage ledger so reasoning tokens are not double-counted by the compatibility
adapter. See `docs/measurement.md` for the schema and aggregation rules.

## Additional Experiments

### ZoneClaw Ablations

The paper evaluates each ablation on the user-triggered form of all four scenarios. The BCC commands are:

```bash
# w/o Zone
MODEL=anthropic/claude-sonnet-4-6 \
E2E=bcc-zoneclaw-no-authority-metadata-userprompt N=15 P=3 bash bench.sh

# w/o Gatekeeper
MODEL=anthropic/claude-sonnet-4-6 \
E2E=bcc-zoneclaw-auto-promotion-userprompt N=15 P=3 bash bench.sh

# w/o Cross-check
MODEL=anthropic/claude-sonnet-4-6 \
E2E=bcc-zoneclaw-low-context-userprompt N=15 P=3 bash bench.sh
```

Replace `bcc` with `chat`, `sr`, or `market` for the remaining scenarios.

### Defense-Aware Attacks

```bash
for experiment in \
  bcc-prompt-aware-promotion-userprompt \
  bcc-zoneclaw-prompt-aware-promotion-userprompt \
  bcc-prompt-aware-composed-userprompt \
  bcc-zoneclaw-prompt-aware-composed-userprompt \
  sr-prompt-aware-finegrained-userprompt \
  sr-zoneclaw-prompt-aware-finegrained-userprompt
do
  MODEL=anthropic/claude-sonnet-4-6 \
  E2E="$experiment" N=15 P=3 bash bench.sh
done
```

### Selective Promotion

```bash
MODEL=anthropic/claude-sonnet-4-6 \
TASK=bcc-exfiltration-zoneclaw-promotion/benign-only \
N=30 P=3 bash bench.sh

MODEL=anthropic/claude-sonnet-4-6 \
TASK=bcc-exfiltration-zoneclaw-promotion/malicious-only \
N=30 P=3 bash bench.sh
```

### Repeated Use Across Sessions

The paper uses the BCC repeated-attack schedule, ten update sessions, and checkpoints after 0, 1, 2, 3, 5, and 10 updates:

```bash
MODEL=anthropic/claude-sonnet-4-6 \
SYSTEM=no-defense SCHEDULE=repeated-attack \
N=3 P=1 bash longitudinal-bench.sh

MODEL=anthropic/claude-sonnet-4-6 \
SYSTEM=zoneclaw SCHEDULE=repeated-attack \
N=3 P=1 bash longitudinal-bench.sh
```

### WorkspaceBench Authority Probe

WorkspaceBench experiments require its Lite metadata and workspace files:

```bash
uv run --with huggingface_hub python \
  workspace-bench/evaluation/scripts/download_hf_assets.py \
  --eval-root workspace-bench/evaluation \
  --language en --lite --workspaces
```

After downloading the upstream tasks, generate the paper's two disjoint 15-task
subsets with the fixed selection seed:

```bash
WB_SUBSETS="$PWD/workspace-bench/evaluation/.generated/memory_authority_probe/subsets"
python3 scripts/workspacebench_privilege_probe.py make-subset \
  --n 15 --seed 20260709 --language en \
  --dest "$WB_SUBSETS/lite-en-15-seed20260709"
python3 scripts/workspacebench_privilege_probe.py make-subset \
  --n 15 --seed 20260709 --language en \
  --exclude-selection "$WB_SUBSETS/lite-en-15-seed20260709/selection.json" \
  --dest "$WB_SUBSETS/lite-en-15-extension-seed20260709"
```

Run each of the four authority conditions on both subsets:

```bash
for batch in lite-en-15-seed20260709 lite-en-15-extension-seed20260709; do
  for condition in \
    benign-instruction memory-injection \
    memory-instruction-conflict intra-memory-conflict
  do
    python3 scripts/workspacebench_privilege_probe.py run \
      --docker-run \
      --condition "$condition" \
      --probe-kind risk-assumption-section \
      --seed-file all \
      --harness openclaw \
      --model gpt-5.5 \
      --dataset lite \
      --task-path "workspace-bench/evaluation/.generated/memory_authority_probe/subsets/$batch" \
      --task-parallel-workers 3 \
      --run-name "Authority-${batch}-${condition}"
  done
done
```

The wrapper preserves WorkspaceBench's runner and task construction. The paper's utility values use WorkspaceBench's official rubric judge.

### WorkspaceBench Benign Utility

This runner evaluates the undefended system and all five defenses on the same 30 benign tasks, split into three disjoint 10-task batches. It runs the upstream task collector and rubric judge:

```bash
for subset in pilot10 pilot20-add10 pilot30-add10; do
  for condition in undefended watcher privsep clawguard melon zoneclaw; do
    python3 scripts/workspacebench_benign_utility.py all \
      --subset "$subset" \
      --condition "$condition" \
      --workers 2 \
      --judge-workers 2
  done
done
```

### Boundary-Wise Analysis

The analysis script accepts externally supplied run packages organized into
`attack-evaluation/` and `mitigation-evaluation/` directories. To analyze packages
downloaded from the artifact repository:

```bash
python3 scripts/analyze_memory_boundaries.py \
  --artifacts-root /path/to/experiment-runs \
  --output-dir runs/analysis/memory-boundaries
```

## Repository Layout

```text
agents/           Harbor agent adapters
experiments/      End-to-end registry and repeated-session manifests
scripts/          WorkspaceBench, repeated-session, and analysis runners
tasks/            Attack, baseline, ablation, and ZoneClaw task definitions
harbor/           Pinned Harbor submodule
openclaw/         Pinned OpenClaw submodule
workspace-bench/ Pinned WorkspaceBench submodule
```
