// Measurement only. Task Docker builds carry an identical copy beside each plugin.
const fs = require("node:fs");
const path = require("node:path");
const { randomUUID } = require("node:crypto");

function createRecorder(component) {
  const logPath = path.join(
    process.env.OPENCLAW_STATE_DIR || path.join(process.env.HOME || "/home/node", ".openclaw"),
    "telemetry", "provider-requests.jsonl",
  );
  function append(record) {
    try {
      fs.mkdirSync(path.dirname(logPath), { recursive: true });
      fs.appendFileSync(logPath, JSON.stringify({
        schema_version: 1, component, timestamp: new Date().toISOString(), ...record,
      }) + "\n");
    } catch {
      // Never change a defense decision because measurement failed.
      process.stderr.write("[telemetry] Could not record auxiliary API usage\n");
    }
  }
  append({ kind: "init" });
  return function start(model) {
    const callId = randomUUID();
    const started = performance.now();
    append({ kind: "start", call_id: callId, provider: "anthropic", model });
    return function finish(body, status) {
      // Keep usage metadata only, never prompts, completions, or credentials.
      const usage = body && body.usage;
      const counts = {};
      for (const key of ["input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"]) {
        if (usage && Number.isFinite(usage[key])) counts[key] = usage[key];
      }
      append({
        kind: "finish", call_id: callId, provider: "anthropic",
        model: (body && body.model) || model, response_id: (body && body.id) || null,
        status, elapsed_ms: Math.round(performance.now() - started),
        usage: Object.keys(counts).length ? counts : null,
      });
    };
  };
}

module.exports = { createRecorder };
