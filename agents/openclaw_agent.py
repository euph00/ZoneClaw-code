"""
OpenClaw agent adapter for Harbor.

Drives an OpenClaw Gateway running as a docker-compose sidecar service.
Communicates via the OpenAI-compatible completions endpoint on port 18789.
Response is written to /logs/response.json for the verifier to read.
"""

import json
import os
import shlex
from harbor.agents.base import BaseAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext
from agents.telemetry import measured_run

# Gateway is reachable at this hostname inside the docker-compose network.
# Docker resolves the service name "openclaw" via its internal DNS.
OPENCLAW_HOST = "openclaw"
OPENCLAW_PORT = 18789
COMPLETIONS_URL = f"http://{OPENCLAW_HOST}:{OPENCLAW_PORT}/v1/chat/completions"

# Written by the agent, read by the verifier.
RESPONSE_FILE = "/logs/agent/response.json"

GATEWAY_FAILURE_MARKERS = (
    "api rate limit reached",
    "api usage limit reached",
    "insufficient balance",
    "no resource package",
)


def _gateway_failure(content: object) -> str | None:
    if not isinstance(content, str):
        return None
    lowered = content.lower()
    if any(marker in lowered for marker in GATEWAY_FAILURE_MARKERS):
        return content.strip()
    return None


class OpenClawAgent(BaseAgent):

    @staticmethod
    def name() -> str:
        return "openclaw"

    def version(self) -> str:
        return "0.1.0-skeleton"

    async def setup(self, environment: BaseEnvironment) -> None:
        """
        Nothing to set up: the OpenClaw Gateway is already running as a
        sidecar and Harbor's depends_on / healthcheck ensures it is ready
        before run() is called.
        """
        pass

    @measured_run
    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        token = os.environ.get("OPENCLAW_GATEWAY_TOKEN", "")
        if not token:
            raise RuntimeError(
                "OPENCLAW_GATEWAY_TOKEN is not set. "
                "Pass it via task.toml [agent] env or the Harbor CLI."
            )

        # Build the completions request payload.
        payload = {
            "model": "openclaw",
            "messages": [{"role": "user", "content": instruction}],
        }
        payload_json = shlex.quote(json.dumps(payload))

        # Run curl inside the main controller container.
        # The openclaw service is reachable by its docker-compose service name.
        curl_cmd = (
            f"curl -s "
            f"-H 'Authorization: Bearer {token}' "
            f"-H 'Content-Type: application/json' "
            f"-H 'x-openclaw-agent-id: main' "
            f"-d {payload_json} "
            f"{COMPLETIONS_URL}"
        )

        result = await environment.exec(curl_cmd)

        if result.return_code != 0:
            stderr = result.stderr or ""
            stdout = result.stdout or ""
            raise RuntimeError(
                f"curl failed (exit {result.return_code})\n"
                f"stdout: {stdout}\nstderr: {stderr}"
            )

        raw_response = result.stdout or ""

        # Validate the response is parseable JSON before writing.
        try:
            parsed = json.loads(raw_response)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"Gateway returned non-JSON response: {raw_response!r}"
            ) from e

        # Surface any API-level error from OpenClaw clearly.
        if "error" in parsed:
            log_tail = ""
            log_result = await environment.exec(
                "tail -n 80 /tmp/openclaw-state/logs/openclaw.log 2>/dev/null || true"
            )
            if log_result.return_code == 0 and log_result.stdout:
                log_tail = f"\nOpenClaw log tail:\n{log_result.stdout}"
            raise RuntimeError(
                f"Gateway returned error: {parsed['error']}{log_tail}"
            )

        # Write response to /logs/ so Harbor downloads it automatically
        # and the verifier can inspect it.
        write_cmd = (
            f"mkdir -p /logs && "
            f"echo {shlex.quote(json.dumps(parsed, indent=2))} > {RESPONSE_FILE}"
        )
        write_result = await environment.exec(write_cmd)

        if write_result.return_code != 0:
            raise RuntimeError(
                f"Failed to write response file: {write_result.stderr}"
            )

        # Populate Harbor context metadata with the response.
        content = ""
        choices = parsed.get("choices", [])
        if choices:
            content = choices[0].get("message", {}).get("content", "")

        failure = _gateway_failure(content)
        if failure:
            raise RuntimeError(f"OpenClaw model call failed: {failure}")

        context.metadata = {
            "openclaw_response_id": parsed.get("id"),
            "openclaw_model": parsed.get("model"),
            "response_content": content,
        }
