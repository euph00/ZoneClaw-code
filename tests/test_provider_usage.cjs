const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const vm = require("node:vm");
const { createRequire } = require("node:module");
const { test } = require("node:test");

const root = path.resolve(__dirname, "..");
const canonical = fs.readFileSync(path.join(root, "agents/provider_usage.cjs"), "utf8");
const files = [];
for (const scenario of ["bcc-exfiltration", "source-redirection", "chat-mirror", "marketplace-provenance"]) {
  for (const defense of ["auditor", "melon"]) {
    for (const phase of ["injection-userprompt", "injection-heartbeat", "exploitation-userprompt"]) {
      if (defense === "auditor" && phase === "exploitation-userprompt") continue;
      const plugin = defense === "auditor" ? "memory-write-auditor" : "melon-runtime";
      files.push({ defense, file: path.join(root, "tasks", scenario + "-" + defense, phase,
        "environment/openclaw-plugins", plugin, "index.cjs") });
    }
  }
}

for (const { defense, file } of files) {
  test(path.relative(root, file) + ": usage does not change API behavior", async () => {
    const state = fs.mkdtempSync(path.join(os.tmpdir(), "helper-usage-"));
    const previous = process.env.OPENCLAW_STATE_DIR;
    process.env.OPENCLAW_STATE_DIR = state;
    try {
      assert.equal(fs.readFileSync(path.join(path.dirname(file), "provider-usage.cjs"), "utf8"), canonical);
      const source = fs.readFileSync(file, "utf8");
      const sandbox = {
        module: { exports: {} }, require: createRequire(file),
        process: { env: { ANTHROPIC_API_KEY: "TEST_KEY_NEVER_ARCHIVE" } },
        AbortController, setTimeout, clearTimeout,
        fetch: async (url, request) => {
          assert.equal(url, "https://api.anthropic.com/v1/messages");
          assert.deepEqual(JSON.parse(request.body), {
            model: "helper-model", max_tokens: defense === "auditor" ? 240 : 420,
            temperature: 0, system: "SYSTEM_NEVER_ARCHIVE",
            messages: [{ role: "user", content: "USER_NEVER_ARCHIVE" }],
          });
          return { ok: true, status: 200, text: async () => JSON.stringify({
            id: "response-1", model: "helper-model",
            content: [{ type: "text", text: "ALLOW" }],
            usage: { input_tokens: 30, output_tokens: 5, cache_read_input_tokens: 7,
              cache_creation_input_tokens: 3, secret: "EXTRA_FIELD_NEVER_ARCHIVE" },
          }) };
        },
      };
      vm.runInNewContext(source + "\nmodule.exports.testCall = callAnthropic;", sandbox);
      const call = sandbox.module.exports.testCall;
      const args = { model: "helper-model", system: "SYSTEM_NEVER_ARCHIVE", user: "USER_NEVER_ARCHIVE", timeoutMs: 100 };
      assert.equal(await call(args), "ALLOW");
      sandbox.fetch = async () => ({ ok: false, status: 429, text: async () => "provider limit" });
      await assert.rejects(call(args), /429/);
      sandbox.fetch = async (url, request) => new Promise((resolve, reject) => {
        request.signal.addEventListener("abort", () => reject(new Error("aborted")));
      });
      await assert.rejects(call({ ...args, timeoutMs: 5 }), /aborted/);
      const raw = fs.readFileSync(path.join(state, "telemetry/provider-requests.jsonl"), "utf8");
      assert.ok(!raw.includes("NEVER_ARCHIVE"));
      const events = raw.trim().split("\n").map(JSON.parse);
      assert.equal(events.filter(e => e.kind === "init").length, 1);
      assert.equal(events.filter(e => e.kind === "start").length, 3);
      const finished = events.filter(e => e.kind === "finish");
      assert.equal(finished.length, 3);
      assert.equal(new Set(finished.map(e => e.call_id)).size, 3);
      assert.deepEqual(finished[0].usage, {
        input_tokens: 30, output_tokens: 5, cache_read_input_tokens: 7, cache_creation_input_tokens: 3,
      });
      assert.equal(finished[1].status, "http_429");
      assert.equal(finished[1].usage, null);
      assert.equal(finished[2].usage, null);
      assert.ok(finished.every(e => e.elapsed_ms >= 0));
      assert.ok(!fs.existsSync(path.join(state, "workspace")));
    } finally {
      if (previous === undefined) delete process.env.OPENCLAW_STATE_DIR;
      else process.env.OPENCLAW_STATE_DIR = previous;
      fs.rmSync(state, { recursive: true, force: true });
    }
  });
}

test("measurement write failure does not throw", () => {
  const state = fs.mkdtempSync(path.join(os.tmpdir(), "helper-unwritable-"));
  const previous = process.env.OPENCLAW_STATE_DIR;
  process.env.OPENCLAW_STATE_DIR = state;
  fs.writeFileSync(path.join(state, "telemetry"), "not a directory");
  try {
    const start = require("../agents/provider_usage.cjs").createRecorder("test");
    assert.doesNotThrow(() => start("model")({ usage: { input_tokens: 1, output_tokens: 1 } }, "ok"));
  } finally {
    if (previous === undefined) delete process.env.OPENCLAW_STATE_DIR;
    else process.env.OPENCLAW_STATE_DIR = previous;
    fs.rmSync(state, { recursive: true, force: true });
  }
});
