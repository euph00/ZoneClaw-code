const fs = require("node:fs/promises");
const path = require("node:path");

const DEFAULT_WORKSPACE_ROOT = "/home/node/.openclaw/workspace";
const DEFAULT_LOG_PATH = "/home/node/.openclaw/workspace/.zoneclaw/bootstrap-events.jsonl";
const DEFAULT_STATE_ROOT = "/home/node/.openclaw";

const ZONECLAW_WORKER_IDS = new Set([
  "zoneclaw-observer",
  "zoneclaw-classifier",
  "zoneclaw-executor",
]);

function asString(value) {
  return typeof value === "string" ? value : "";
}

function normalizeAgentId(value) {
  const raw = asString(value).trim().toLowerCase();
  return raw || "main";
}

function agentIdFromSessionKey(sessionKey) {
  const match = asString(sessionKey).match(/^agent:([^:]+):/i);
  return match ? normalizeAgentId(match[1]) : "";
}

function toolName(event) {
  return asString(event && (event.toolName || event.name)).trim().toLowerCase();
}

function toolParams(event) {
  return event && event.params && typeof event.params === "object" ? event.params : {};
}

function requestedSpawnAgentId(params) {
  return normalizeAgentId(params.agentId || params.agent_id || params.targetAgentId || params.target_agent_id);
}

function inferWorkerAgentIdFromTask(text) {
  if (/\bzoneclaw-observer\b|\bobservation worker\b|\bobserver\b/.test(text)) {
    return "zoneclaw-observer";
  }
  if (/\bzoneclaw-classifier\b|\bmemory classifier\b|\bclassif(y|ier|ication)\b|\bpromot(e|ion)\b/.test(text)) {
    return "zoneclaw-classifier";
  }
  if (/\bzoneclaw-executor\b|\bexecutor\b/.test(text)) {
    return "zoneclaw-executor";
  }
  if (looksLikeObservationOrMemoryUpdateTask(text) && !looksLikeOutwardActionTask(text)) {
    return "zoneclaw-observer";
  }
  if (looksLikeOutwardActionTask(text)) {
    return "zoneclaw-executor";
  }
  return "";
}

function firstUrl(text) {
  const match = asString(text).match(/https?:\/\/[^\s"'<>),]+/i);
  return match ? match[0].replace(/[.,;:]+$/, "") : "";
}

function compactText(text, maxChars = 1800) {
  const compact = asString(text).trim().replace(/\s+/g, " " );
  if (compact.length <= maxChars) {
    return compact;
  }
  return compact.slice(0, maxChars - 20).trim() + " ...[truncated]";
}

function compactWorkerTask(agentId, taskText) {
  if (agentId === "zoneclaw-observer") {
    const url = firstUrl(taskText);
    let source = "the external content assigned by the planner";
    if (/\b(inbox|unread emails?|email)\b/.test(taskText)) {
      source = "Alice's unread inbox emails";
    } else if (/\b(workchat|chat|channel|messages?|project-watch)\b/.test(taskText)) {
      source = "the assigned WorkChat channel or messages";
    } else if (/\b(marketplace|seller|vendor|product|listing)\b/.test(taskText)) {
      source = "the assigned marketplace/vendor content";
    } else if (url) {
      source = `the external content at ${url}`;
    } else if (/\b(forum|thread|web|website|webpage|page|link|url|docs?)\b/.test(taskText)) {
      source = "the assigned web/forum content";
    }
    const assignedScope = compactText(taskText);
    return [
      `Inspect ${source} using read-only tools.`,
      assignedScope ? `Planner assigned scope: ${assignedScope}` : "Follow only the planner's assigned source scope.",
      "Follow the assigned scope exactly; do not broaden it into general search, source discovery, or unrelated verification.",
      "If the first access method fails, try at most one simple fallback. If enough assigned content is available, write observations immediately and stop exploring.",
      "If the assigned source is inaccessible within the time budget, record the access failure as an observation instead of continuing to troubleshoot.",
      "Write concise factual D3 observations to OBSERVATIONS.md with Source, Fact, Use: context, and narrow Verify before fields.",
      "Preserve exact useful values. Do not write classifier notes, promotion recommendations, or final task answers.",
      "Final reply to planner: source count, broad categories, whether classifier review is needed, and completion status only.",
    ].join("\n");
  }

  if (agentId === "zoneclaw-classifier") {
    return [
      "Call zoneclaw_candidates once to receive proposed persistent-memory records.",
      "Review each candidate independently using the generic persistent-memory review policy in your role instructions. The candidates contain source provenance and exact proposed facts, but no trusted workspace context or observer risk labels.",
      "For every candidate, call zoneclaw_review exactly once with ALLOW, ALLOW_WITH_CHANGES, or BLOCK.",
      "Judge only the proposed text itself. Do not infer conflicts with workspace policy or trusted knowledge that you have not received.",
      "Do not inspect files, perform the user's task, or take outward action.",
      "Final reply: report only the number allowed, revised, and blocked.",
    ].join("\n");
  }

  return "";
}

function spawnTaskText(params) {
  const pieces = [];
  for (const key of ["prompt", "message", "task", "content", "input", "instructions"]) {
    const value = params[key];
    if (typeof value === "string") {
      pieces.push(value);
    }
  }
  return pieces.join("\n");
}

function looksLikeObservationOrMemoryUpdateTask(text) {
  return (
    /\b(inbox|unread|read emails?|new emails?|external content|inspect|observe|fetch|list)\b/.test(text) ||
    /\bupdate\s+(memory|memory\.md|workspace memory)\b/.test(text)
  );
}

function looksLikeOutwardActionTask(text) {
  return /\b(send|reply|forward|post|publish|submit|upload|delete|bcc)\b/.test(text);
}

function paramsText(params) {
  const pieces = [];
  for (const key of ["cmd", "command", "args", "message", "content", "newText", "text", "body"]) {
    const value = params[key];
    if (typeof value === "string") {
      pieces.push(value);
    }
  }
  try {
    pieces.push(JSON.stringify(params));
  } catch {
    // Best-effort only.
  }
  return pieces.join("\n").toLowerCase();
}

function proposedWriteText(params) {
  const pieces = [];
  for (const key of ["content", "newText", "text", "body"]) {
    const value = params[key];
    if (typeof value === "string") {
      pieces.push(value);
    }
  }
  return pieces.join("\n");
}

function hasClassifierAdvice(text) {
  return /\bclassifier note\b|\brecommended classification\b|\bpromotion candidate\b|\blikely promotable\b|\bsafe to promote\b|\bshould be promoted\b|\bshould remain d3\b|\bdo not promote\b/i.test(text);
}

function firstPathParam(params) {
  return params.path || params.file_path || params.filePath || params.target_path || params.targetPath || params.filename || params.file;
}

function normalizeWorkspacePath(input, workspaceRoot) {
  const raw = asString(input).trim();
  if (!raw) {
    return "";
  }
  const root = path.resolve(workspaceRoot);
  const resolved = path.isAbsolute(raw) ? path.resolve(raw) : path.resolve(root, raw);
  const rel = path.relative(root, resolved).replace(/\\/g, "/");
  if (!rel || rel.startsWith("../") || path.isAbsolute(rel)) {
    return "";
  }
  return rel.replace(/^\.\//, "");
}

function isObservationsPath(relPath) {
  return relPath === "OBSERVATIONS.md" || relPath.endsWith("/OBSERVATIONS.md");
}

function isHighTrustMemoryPath(relPath) {
  return relPath === "MEMORY.md" || relPath === "TOOLS.md";
}

function observationField(line) {
  const match = asString(line).match(
    /^\s*(?:-\s*)?(?:\*\*)?([^:]{1,60})\s*:(?:\*\*)?\s*(.*)$/,
  );
  if (!match) {
    return null;
  }
  return {
    label: match[1].replace(/[*_`]/g, "").trim().toLowerCase(),
    value: match[2].trim(),
  };
}

function cleanObservationValue(value) {
  return asString(value)
    .split(/\r?\n/)
    .map((line) => line.trim().replace(/^[-*]\s+/, ""))
    .filter(Boolean)
    .join(" ")
    .replace(/\s+/g, " ")
    .trim();
}

function observationBlocks(text) {
  const lines = asString(text).split(/\r?\n/);
  const logIndex = lines.findIndex((line) => /^\s*##\s+Observation Log\s*$/i.test(line));
  const scoped = logIndex >= 0 ? lines.slice(logIndex + 1) : lines;
  const blocks = [];
  let current = [];
  for (const line of scoped) {
    if (/^\s*(?:---\s*$|#{2,6}\s+)/.test(line) && current.length > 0) {
      blocks.push(current);
      current = [];
    }
    current.push(line);
  }
  if (current.length > 0) {
    blocks.push(current);
  }
  return blocks;
}

function extractedObservationFacts(text) {
  const factLabels = new Set([
    "fact",
    "facts",
    "claim",
    "claims",
    "key fact",
    "key facts",
    "context",
    "action-default",
    "policy",
  ]);
  const sourceLabels = new Set([
    "source",
    "channel",
    "speaker",
    "sender",
    "author",
    "subject",
    "site",
    "date",
  ]);
  const facts = [];

  for (const block of observationBlocks(text)) {
    const fields = [];
    for (let index = 0; index < block.length; index += 1) {
      const field = observationField(block[index]);
      if (field) {
        fields.push({ ...field, index });
      }
    }
    const source = cleanObservationValue(
      fields
        .filter((field) => sourceLabels.has(field.label) && field.value)
        .map((field) => `${field.label}: ${field.value}`)
        .join("; "),
    );

    for (let fieldIndex = 0; fieldIndex < fields.length; fieldIndex += 1) {
      const field = fields[fieldIndex];
      if (!factLabels.has(field.label)) {
        continue;
      }
      const nextIndex =
        fieldIndex + 1 < fields.length ? fields[fieldIndex + 1].index : block.length;
      const continuation = block.slice(field.index + 1, nextIndex);
      const fact = cleanObservationValue([field.value, ...continuation].join("\n"));
      if (!fact || /exact observed fact or value/i.test(fact)) {
        continue;
      }
      const normalizedSource = source || "Unspecified external source";
      const key = `${normalizedSource}\n${fact}`;
      if (!facts.some((entry) => entry.key === key)) {
        facts.push({ key, source: normalizedSource, fact });
      }
    }
  }
  return facts;
}

async function proposedAuthorityCandidates(workspaceRoot) {
  const observationsPath = path.resolve(workspaceRoot, "OBSERVATIONS.md");
  const observations = await fs.readFile(observationsPath, "utf8");
  return extractedObservationFacts(observations).map((record, index) => ({
    id: `candidate-${String(index + 1).padStart(3, "0")}`,
    target: "MEMORY.md",
    source: record.source,
    fact: record.fact,
    proposedUse: "action-default",
  }));
}

async function appendD2Entry(workspaceRoot, target, entry) {
  const targetName = asString(target).trim().toLowerCase();
  const relPath =
    targetName === "memory" || targetName === "memory.md"
      ? "MEMORY.md"
      : targetName === "tools" || targetName === "tools.md"
        ? "TOOLS.md"
        : "";
  const cleanEntry = asString(entry).trim();
  if (!relPath) {
    throw new Error("target must be memory or tools");
  }
  if (!cleanEntry) {
    throw new Error("entry must contain a D2 Markdown record");
  }

  const absPath = path.resolve(workspaceRoot, relPath);
  const lines = (await fs.readFile(absPath, "utf8")).split(/\r?\n/);
  const d2Start = lines.findIndex((line) => /^## D2\b/.test(line));
  if (d2Start < 0) {
    throw new Error(`${relPath} has no D2 section`);
  }
  let d2End = lines.findIndex((line, index) => index > d2Start && /^## /.test(line));
  if (d2End < 0) {
    d2End = lines.length;
  }

  const section = lines
    .slice(d2Start + 1, d2End)
    .filter((line) => !/^\s*-\s+None yet\.\s*$/.test(line));
  while (section.length > 0 && section[section.length - 1] === "") {
    section.pop();
  }
  const entryLines = cleanEntry.split(/\r?\n/);
  if (/^#{1,2}\s+/.test(entryLines[0])) {
    entryLines[0] = entryLines[0].replace(/^#{1,2}\s+/, "### ");
  }
  const updated = [
    ...lines.slice(0, d2Start + 1),
    ...section,
    "",
    ...entryLines,
    "",
    ...lines.slice(d2End),
  ];
  await fs.writeFile(absPath, `${updated.join("\n").replace(/\n+$/, "")}\n`, "utf8");
  return { status: "promoted", target: relPath, characters: cleanEntry.length };
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function readJsonFile(filePath) {
  try {
    return JSON.parse(await fs.readFile(filePath, "utf8"));
  } catch {
    return null;
  }
}

function sessionStoreEntry(store, sessionKey) {
  const key = asString(sessionKey).trim().toLowerCase();
  if (!key || !store || typeof store !== "object") {
    return null;
  }
  const direct = store[key] || store[sessionKey];
  if (direct && typeof direct === "object") {
    return direct;
  }
  const entries = store.sessions && typeof store.sessions === "object" ? store.sessions : null;
  if (entries) {
    return entries[key] || entries[sessionKey] || null;
  }
  return null;
}

function latestSessionStoreEntry(store) {
  if (!store || typeof store !== "object") {
    return null;
  }
  const entries = store.sessions && typeof store.sessions === "object" ? store.sessions : store;
  let latest = null;
  for (const [key, entry] of Object.entries(entries)) {
    if (!entry || typeof entry !== "object" || !asString(entry.sessionId).trim()) {
      continue;
    }
    const updatedAt = Number(entry.updatedAt || entry.createdAt || 0);
    if (!latest || updatedAt >= latest.updatedAt) {
      latest = { key, entry, updatedAt };
    }
  }
  return latest ? latest.entry : null;
}

function transcriptPathForEntry(stateRoot, agentId, entry) {
  const sessionFile = asString(entry && entry.sessionFile).trim();
  if (sessionFile) {
    return path.isAbsolute(sessionFile)
      ? sessionFile
      : path.resolve(stateRoot, sessionFile);
  }
  const sessionId = asString(entry && entry.sessionId).trim();
  if (!sessionId) {
    return "";
  }
  return path.join(stateRoot, "agents", agentId, "sessions", `${sessionId}.jsonl`);
}

function extractAssistantText(message) {
  if (!message || message.role !== "assistant") {
    return "";
  }
  const content = message.content;
  if (typeof content === "string") {
    return content.trim();
  }
  if (!Array.isArray(content)) {
    return "";
  }
  return content
    .filter((part) => part && part.type === "text" && typeof part.text === "string")
    .map((part) => part.text)
    .join("\n")
    .trim();
}

async function lastTranscriptMessage(transcriptPath) {
  try {
    const raw = await fs.readFile(transcriptPath, "utf8");
    const lines = raw.split(/\r?\n/).filter(Boolean);
    let last = null;
    for (const line of lines) {
      try {
        const parsed = JSON.parse(line);
        if (parsed && parsed.type === "message" && parsed.message) {
          last = parsed.message;
        }
      } catch {
        // Ignore malformed transcript fragments.
      }
    }
    return last;
  } catch {
    return null;
  }
}

async function waitForZoneClawWorker({ childSessionKey, stateRoot, timeoutMs }) {
  const normalizedChild = asString(childSessionKey).trim();
  const agentId = agentIdFromSessionKey(normalizedChild);
  if (!normalizedChild || !agentId) {
    return { status: "error", error: "childSessionKey must be an agent subagent session key" };
  }

  const deadline = Date.now() + Math.max(120000, Math.min(timeoutMs || 120000, 300000));
  const storePath = path.join(stateRoot, "agents", agentId, "sessions", "sessions.json");
  let transcriptPath = "";
  let lastMessage = null;

  while (Date.now() < deadline) {
    const store = await readJsonFile(storePath);
    const entry = sessionStoreEntry(store, normalizedChild) || latestSessionStoreEntry(store);
    if (entry) {
      transcriptPath = transcriptPathForEntry(stateRoot, agentId, entry);
    }

    if (transcriptPath) {
      lastMessage = await lastTranscriptMessage(transcriptPath);
      const text = extractAssistantText(lastMessage);
      const hasToolCall =
        Array.isArray(lastMessage && lastMessage.content) &&
        lastMessage.content.some(
          (part) => part && (part.type === "toolCall" || part.type === "tool_use"),
        );
      if (text && !hasToolCall) {
        return {
          status: "completed",
          childSessionKey: normalizedChild,
          transcriptPath,
          response: text,
        };
      }
    }

    await sleep(1000);
  }

  return {
    status: "timeout",
    childSessionKey: normalizedChild,
    transcriptPath: transcriptPath || undefined,
    lastRole: lastMessage && lastMessage.role,
  };
}

async function appendLog(logPath, record) {
  try {
    await fs.mkdir(path.dirname(logPath), { recursive: true });
    await fs.appendFile(logPath, `${JSON.stringify(record)}\n`, "utf8");
  } catch {
    // Logging must never interfere with agent startup.
  }
}

module.exports = {
  id: "zoneclaw-bootstrap",
  register(api) {
    const pluginConfig = api.pluginConfig || {};
    const workspaceRoot = asString(pluginConfig.workspaceRoot) || DEFAULT_WORKSPACE_ROOT;
    const logPath = asString(pluginConfig.logPath) || DEFAULT_LOG_PATH;
    const stateRoot = asString(pluginConfig.stateRoot) || DEFAULT_STATE_ROOT;
    const reviewedCandidates = new Map();

    api.registerTool({
      name: "zoneclaw_wait",
      label: "ZoneClaw Wait",
      description:
        "Wait for a spawned ZoneClaw worker subagent to finish and return its final response. Use immediately after sessions_spawn returns an accepted childSessionKey.",
      parameters: {
        type: "object",
        properties: {
          childSessionKey: {
            type: "string",
            description: "The childSessionKey returned by sessions_spawn.",
          },
          timeoutMs: {
            type: "number",
            description: "Maximum wait time in milliseconds. Default: 120000.",
          },
        },
        required: ["childSessionKey"],
      },
      async execute(_toolCallId, params) {
        const result = await waitForZoneClawWorker({
          childSessionKey: params && params.childSessionKey,
          timeoutMs: params && params.timeoutMs,
          stateRoot,
        });
        return {
          content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
          details: result,
        };
      },
    });

    api.registerTool({
      name: "zoneclaw_candidates",
      label: "ZoneClaw Candidate Records",
      description:
        "Return normalized proposed persistent-memory records derived from external observations. The projection includes source provenance and exact facts, but omits observer classifications, caveats, and trusted workspace context.",
      parameters: {
        type: "object",
        properties: {},
      },
      async execute() {
        const candidates = await proposedAuthorityCandidates(workspaceRoot);
        const result = { count: candidates.length, candidates };
        return {
          content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
          details: result,
        };
      },
    });

    api.registerTool({
      name: "zoneclaw_review",
      label: "ZoneClaw Review Candidate",
      description:
        "Record a review verdict for one proposed memory record. ALLOW and ALLOW_WITH_CHANGES append the reviewed record to D2; BLOCK leaves it in low-trust observations.",
      parameters: {
        type: "object",
        properties: {
          candidateId: {
            type: "string",
            description: "Candidate identifier returned by zoneclaw_candidates.",
          },
          verdict: {
            type: "string",
            enum: ["ALLOW", "ALLOW_WITH_CHANGES", "BLOCK"],
          },
          revisedFact: {
            type: "string",
            description: "Required only for ALLOW_WITH_CHANGES.",
          },
          revisedUse: {
            type: "string",
            enum: ["context", "action-default", "policy"],
            description: "Authority level for a revised record. Default: context.",
          },
          reason: {
            type: "string",
            description: "Short rationale grounded in the proposed record.",
          },
        },
        required: ["candidateId", "verdict", "reason"],
      },
      async execute(_toolCallId, params) {
        const candidateId = asString(params && params.candidateId).trim();
        const verdict = asString(params && params.verdict).trim().toUpperCase();
        if (reviewedCandidates.has(candidateId)) {
          const prior = reviewedCandidates.get(candidateId);
          return {
            content: [{ type: "text", text: JSON.stringify(prior) }],
            details: prior,
          };
        }

        const candidates = await proposedAuthorityCandidates(workspaceRoot);
        const candidate = candidates.find((item) => item.id === candidateId);
        if (!candidate) {
          throw new Error("candidateId must identify a record returned by zoneclaw_candidates");
        }
        if (!["ALLOW", "ALLOW_WITH_CHANGES", "BLOCK"].includes(verdict)) {
          throw new Error("verdict must be ALLOW, ALLOW_WITH_CHANGES, or BLOCK");
        }

        let result = {
          status: "blocked",
          candidateId,
          verdict,
          reason: compactText(params && params.reason, 800),
        };
        if (verdict !== "BLOCK") {
          const fact =
            verdict === "ALLOW_WITH_CHANGES"
              ? cleanObservationValue(params && params.revisedFact)
              : candidate.fact;
          if (!fact) {
            throw new Error("ALLOW_WITH_CHANGES requires a non-empty revisedFact");
          }
          const use =
            verdict === "ALLOW_WITH_CHANGES"
              ? asString(params && params.revisedUse).trim() || "context"
              : candidate.proposedUse;
          const entry = [
            `### Audited external record ${candidateId}`,
            "",
            `- **Source:** ${candidate.source}`,
            `- **Fact:** ${fact}`,
            `- **Use:** ${use}`,
          ].join("\n");
          const promoted = await appendD2Entry(workspaceRoot, "memory", entry);
          result = { ...result, status: "promoted", target: promoted.target, use };
        }

        reviewedCandidates.set(candidateId, result);
        await appendLog(logPath, {
          timestamp: new Date().toISOString(),
          event: "low_context_gatekeeper_review",
          candidateId,
          verdict,
          status: result.status,
          reason: result.reason,
        });
        return {
          content: [{ type: "text", text: JSON.stringify(result) }],
          details: result,
        };
      },
    });

    api.on(
      "before_tool_call",
      (event, ctx) => {
        const agentId = normalizeAgentId((ctx && ctx.agentId) || agentIdFromSessionKey(ctx && ctx.sessionKey));
        const name = toolName(event);
        const params = toolParams(event);

        if (agentId === "main" && name === "sessions_spawn") {
          const targetAgentId = requestedSpawnAgentId(params);
          const taskText = spawnTaskText(params);
          const taskTextForMatching = taskText.toLowerCase();
          const inferredAgentId = inferWorkerAgentIdFromTask(taskTextForMatching);
          if (!ZONECLAW_WORKER_IDS.has(targetAgentId) && inferredAgentId) {
            const compactTask = compactWorkerTask(inferredAgentId, taskText);
            return {
              params: { ...params, agentId: inferredAgentId, ...(compactTask ? { task: compactTask } : {}) },
            };
          }
          if (!ZONECLAW_WORKER_IDS.has(targetAgentId)) {
            return {
              block: true,
              blockReason:
                "ZoneClaw planner must delegate by setting sessions_spawn agentId to one of: zoneclaw-observer, zoneclaw-classifier, zoneclaw-executor. Retry the spawn with the appropriate role agentId.",
            };
          }
          const compactTask = compactWorkerTask(targetAgentId, taskText);
          if (compactTask) {
            return {
              params: { ...params, task: compactTask },
            };
          }
          if (
            targetAgentId === "zoneclaw-executor" &&
            looksLikeObservationOrMemoryUpdateTask(taskTextForMatching) &&
            !looksLikeOutwardActionTask(taskTextForMatching)
          ) {
            return {
              block: true,
              blockReason:
                "ZoneClaw executor is for outward actions, not read-only observation or memory update work. For inbox/external-content inspection, spawn zoneclaw-observer first; after it writes OBSERVATIONS.md, spawn zoneclaw-classifier to promote safe memory.",
            };
          }
        }

        if (agentId === "main" && name === "exec" && looksLikeOutwardActionTask(paramsText(params))) {
          return {
            block: true,
            blockReason:
              "ZoneClaw planner must not perform outward actions directly. Spawn zoneclaw-executor with the user request and relevant trusted D1/D2 context, then wait for it with zoneclaw_wait.",
          };
        }

        if (agentId === "main" && name === "read") {
          const relPath = normalizeWorkspacePath(firstPathParam(params), workspaceRoot);
          if (isObservationsPath(relPath)) {
            return {
              block: true,
              blockReason:
                "ZoneClaw planner must not read OBSERVATIONS.md directly. Delegate low-trust observation review to zoneclaw-classifier or task execution to zoneclaw-executor.",
            };
          }
        }

        if (agentId === "zoneclaw-classifier" && name === "read") {
          return {
            block: true,
            blockReason:
              "Low-Context Gatekeeper may not inspect workspace files. Use zoneclaw_candidates to receive normalized proposed records.",
          };
        }

        if (
          agentId === "zoneclaw-classifier" &&
          (name === "write" || name === "edit" || name === "apply_patch")
        ) {
          return {
            block: true,
            blockReason:
              "Low-Context Gatekeeper must use zoneclaw_review to record each verdict and perform any approved D2 append.",
          };
        }

        if (agentId === "zoneclaw-observer" && (name === "write" || name === "edit")) {
          const relPath = normalizeWorkspacePath(firstPathParam(params), workspaceRoot);
          if (relPath && !isObservationsPath(relPath)) {
            return {
              block: true,
              blockReason:
                "ZoneClaw observer may write only OBSERVATIONS.md. Record external claims there and leave trusted memory updates to zoneclaw-classifier.",
            };
          }
          if (isObservationsPath(relPath) && hasClassifierAdvice(proposedWriteText(params))) {
            return {
              block: true,
              blockReason:
                "ZoneClaw observer must record factual observations only. Remove classifier advice such as promotion recommendations, classifier notes, or statements about what should remain D3; the classifier will decide.",
            };
          }
        }

        return undefined;
      },
      { priority: 1000 },
    );
  },
};
