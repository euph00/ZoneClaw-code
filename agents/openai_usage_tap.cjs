// Read-only wire telemetry for Alibaba calls. No request/response body is changed.
const fs = require("node:fs");
const path = require("node:path");
const { randomUUID } = require("node:crypto");

function install(fetchImpl = globalThis.fetch) {
  const logPath = path.join(process.env.OPENCLAW_STATE_DIR ||
    path.join(process.env.HOME || "/home/node", ".openclaw"), "telemetry", "raw-api.jsonl");
  function append(event) {
    try {
      fs.mkdirSync(path.dirname(logPath), { recursive: true });
      fs.appendFileSync(logPath, JSON.stringify({
        schema_version: 1, timestamp: new Date().toISOString(), provider: "alibaba", ...event,
      }) + "\n");
    } catch {
      process.stderr.write("[telemetry] Could not record raw API usage\n");
    }
  }
  append({ kind: "init" });
  return async function measuredFetch(input, init) {
    let request;
    try {
      const url = new URL(typeof input === "string" || input instanceof URL ? input : input.url);
      if (!url.hostname.endsWith(".aliyuncs.com") || !url.pathname.endsWith("/chat/completions")) {
        return fetchImpl(input, init);
      }
      if (typeof init?.body !== "string") return fetchImpl(input, init);
      request = JSON.parse(init.body);
    } catch {
      return fetchImpl(input, init);
    }
    const callId = randomUUID();
    const started = performance.now();
    const assistants = (request.messages || []).filter(m => m.role === "assistant");
    const settings = {};
    for (const key of ["enable_thinking", "reasoning_effort", "thinking_budget", "max_tokens",
      "max_completion_tokens", "preserve_thinking", "temperature", "top_p", "stream"]) {
      if (request[key] !== undefined) settings[key] = request[key];
    }
    append({ kind: "start", call_id: callId, model: request.model, settings,
      system_role: request.messages?.[0]?.role,
      assistant_history: assistants.length,
      reasoning_history: assistants.filter(m => typeof m.reasoning_content === "string" && m.reasoning_content.length).length,
      tool_history: assistants.filter(m => m.tool_calls?.length).length,
    });
    function finish(usage, status, responseId = null) {
      // Only numeric usage fields are retained, not text from either direction.
      let counts = null;
      if (usage) {
        counts = {};
        for (const key of ["prompt_tokens", "completion_tokens", "total_tokens"]) {
          if (Number.isFinite(usage[key])) counts[key] = usage[key];
        }
        for (const [field, key] of [["prompt_tokens_details", "cached_tokens"],
          ["completion_tokens_details", "reasoning_tokens"]]) {
          if (Number.isFinite(usage[field]?.[key])) counts[field] = { [key]: usage[field][key] };
        }
      }
      append({ kind: "finish", call_id: callId, model: request.model, response_id: responseId,
        status, elapsed_ms: Math.round(performance.now() - started), usage: counts });
    }
    let response;
    try {
      response = await fetchImpl(input, init);
    } catch (error) {
      finish(null, "network_error");
      throw error;
    }
    // Observe a clone, allowing the SDK to consume the original bytes unchanged.
    async function observe(copy) {
      let usage = null, responseId = null;
      function consume(text) {
        if (!text || text === "[DONE]") return;
        const chunk = JSON.parse(text);
        if (chunk.usage) usage = chunk.usage;
        if (typeof chunk.id === "string") responseId = chunk.id;
      }
      try {
        if ((copy.headers.get("content-type") || "").includes("text/event-stream")) {
          const reader = copy.body.getReader();
          const decoder = new TextDecoder();
          let pending = "";
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            pending += decoder.decode(value, { stream: true });
            let newline;
            while ((newline = pending.indexOf("\n")) >= 0) {
              const line = pending.slice(0, newline).trimEnd();
              pending = pending.slice(newline + 1);
              if (line.startsWith("data:")) consume(line.slice(5).trim());
            }
          }
          pending += decoder.decode();
          if (pending.startsWith("data:")) consume(pending.slice(5).trim());
        } else {
          consume(await copy.text());
        }
        finish(usage, copy.ok ? "ok" : "http_" + copy.status, responseId);
      } catch {
        finish(usage, "capture_error", responseId);
      }
    }
    try {
      void observe(response.clone());
    } catch {
      finish(null, "capture_error");
    }
    return response;
  };
}

if (process.env.BENCH_RAW_API_CAPTURE === "alibaba") globalThis.fetch = install();
module.exports = { install };
