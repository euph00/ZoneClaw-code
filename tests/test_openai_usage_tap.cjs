const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { install } = require("../agents/openai_usage_tap.cjs");

test("wire observation preserves requests and SSE bytes, retaining only usage/settings", async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "raw-usage-"));
  const previous = process.env.OPENCLAW_STATE_DIR;
  process.env.OPENCLAW_STATE_DIR = directory;
  try {
    const usage = { prompt_tokens: 100, completion_tokens: 40, total_tokens: 140,
      prompt_tokens_details: { cached_tokens: 50 }, completion_tokens_details: { reasoning_tokens: 25 } };
    const data = 'data: {"choices":[{"delta":{"reasoning_content":"PRIVATE_REASONING"}}]}\n\n' +
      'data: {"id":"response-1","choices":[],"usage":' + JSON.stringify(usage) + '}\n\ndata: [DONE]\n\n';
    const request = {
      method: "POST", headers: { Authorization: "SECRET_KEY" },
      body: JSON.stringify({ model: "qwen3.8-max-0902", reasoning_effort: "medium", max_completion_tokens: 32768,
        messages: [{ role: "system", content: "PRIVATE_SYSTEM" },
          { role: "assistant", content: "PRIVATE_ANSWER", reasoning_content: "PRIVATE_REASONING", tool_calls: [{}] }] }),
    };
    const url = "https://test.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions";
    const tapped = install(async (input, init) => {
      assert.equal(input, url);
      assert.equal(init, request);
      const bytes = new TextEncoder().encode(data);
      return new Response(new ReadableStream({ start(controller) {
        for (let i = 0; i < bytes.length; i += 7) controller.enqueue(bytes.slice(i, i + 7));
        controller.close();
      } }), { headers: { "content-type": "text/event-stream" } });
    });
    const response = await tapped(url, request);
    assert.equal(await response.text(), data);
    const log = path.join(directory, "telemetry/raw-api.jsonl");
    let records;
    for (let attempt = 0; attempt < 50; attempt++) {
      records = fs.readFileSync(log, "utf8").trim().split("\n").map(JSON.parse);
      if (records.some(r => r.kind === "finish")) break;
      await new Promise(resolve => setTimeout(resolve, 5));
    }
    assert.equal(records.length, 3);
    const start = records.find(r => r.kind === "start");
    const finish = records.find(r => r.kind === "finish");
    assert.equal(start.settings.reasoning_effort, "medium");
    assert.equal(start.settings.max_completion_tokens, 32768);
    assert.equal(start.system_role, "system");
    assert.equal(start.reasoning_history, 1);
    assert.deepEqual(finish.usage, usage);
    assert.equal(finish.status, "ok");
    assert.ok(!JSON.stringify(records).includes("PRIVATE_"));
    assert.ok(!JSON.stringify(records).includes("SECRET_KEY"));
  } finally {
    if (previous === undefined) delete process.env.OPENCLAW_STATE_DIR;
    else process.env.OPENCLAW_STATE_DIR = previous;
    fs.rmSync(directory, { recursive: true, force: true });
  }
});

test("unrelated endpoints pass through and network errors are preserved", async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "raw-failure-"));
  const previous = process.env.OPENCLAW_STATE_DIR;
  process.env.OPENCLAW_STATE_DIR = directory;
  try {
    const error = new Error("network unavailable");
    const tapped = install(async () => { throw error; });
    await assert.rejects(tapped("https://api.anthropic.com/v1/messages", {}), e => e === error);
    await assert.rejects(tapped("https://x.aliyuncs.com/chat/completions", {
      body: JSON.stringify({ model: "test", messages: [] }),
    }), e => e === error);
    const records = fs.readFileSync(path.join(directory, "telemetry/raw-api.jsonl"), "utf8").trim().split("\n").map(JSON.parse);
    assert.equal(records.length, 3);
    assert.equal(records[2].status, "network_error");
    assert.equal(records[2].usage, null);
  } finally {
    if (previous === undefined) delete process.env.OPENCLAW_STATE_DIR;
    else process.env.OPENCLAW_STATE_DIR = previous;
    fs.rmSync(directory, { recursive: true, force: true });
  }
});
