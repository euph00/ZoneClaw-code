const fs = require("node:fs/promises");
const path = require("node:path");

const ROLE_BY_AGENT = {
  main: "planner",
  "privsep-reader": "reader",
  "privsep-actor": "actor",
};

const ROLE_POLICY_PATH = {
  planner: ".privsep/roles/planner.md",
  reader: ".privsep/roles/reader.md",
  actor: ".privsep/roles/actor.md",
};

const BOOTSTRAP_BY_ROLE = {
  planner: ["AGENTS.md", "MEMORY.md", "TOOLS.md", "IDENTITY.md", "USER.md"],
  reader: ["AGENTS.md", "TOOLS.md", "IDENTITY.md", "USER.md"],
  actor: ["AGENTS.md", "MEMORY.md", "TOOLS.md", "IDENTITY.md", "USER.md"],
};

function normalizeAgentId(value) {
  const normalized = typeof value === "string" ? value.trim().toLowerCase() : "";
  return normalized || "main";
}

function agentIdFromSessionKey(sessionKey) {
  const match =
    typeof sessionKey === "string" ? sessionKey.match(/^agent:([^:]+):/i) : null;
  return match ? normalizeAgentId(match[1]) : "";
}

async function readWorkspaceFile(workspaceRoot, relPath, name = path.basename(relPath)) {
  const root = path.resolve(workspaceRoot);
  const absolutePath = path.resolve(root, relPath);
  const relativePath = path.relative(root, absolutePath);
  if (!relativePath || relativePath.startsWith("..") || path.isAbsolute(relativePath)) {
    return null;
  }

  try {
    return {
      name,
      path: absolutePath,
      content: await fs.readFile(absolutePath, "utf8"),
      missing: false,
    };
  } catch {
    return null;
  }
}

async function buildRoleBootstrapFiles(workspaceRoot, role) {
  const files = [];
  const missing = [];

  for (const relPath of BOOTSTRAP_BY_ROLE[role] || []) {
    const sourcePath = relPath === "AGENTS.md" ? ROLE_POLICY_PATH[role] : relPath;
    const file = await readWorkspaceFile(workspaceRoot, sourcePath, relPath);
    if (file) {
      files.push(file);
    } else {
      missing.push(sourcePath);
    }
  }

  return { files, missing };
}

async function appendLog(workspaceRoot, record) {
  try {
    const logPath = path.join(workspaceRoot, ".privsep", "bootstrap-events.jsonl");
    await fs.mkdir(path.dirname(logPath), { recursive: true });
    await fs.appendFile(logPath, `${JSON.stringify(record)}\n`, "utf8");
  } catch {
    // Bootstrap logging must not interrupt an agent run.
  }
}

module.exports = async function privsepRoleBootstrap(event) {
  if (!event || event.type !== "agent" || event.action !== "bootstrap") {
    return;
  }

  const context = event.context || {};
  const agentId = normalizeAgentId(
    context.agentId || agentIdFromSessionKey(context.sessionKey),
  );
  const role = ROLE_BY_AGENT[agentId];
  if (!role || !context.workspaceDir) {
    return;
  }

  const { files, missing } = await buildRoleBootstrapFiles(context.workspaceDir, role);

  // Always replace the defaults for known roles. Missing files must not cause
  // a silent fallback to OpenClaw's broader subagent bootstrap allowlist.
  context.bootstrapFiles = files;

  await appendLog(context.workspaceDir, {
    timestamp: new Date().toISOString(),
    event: "role_bootstrap_applied",
    agentId,
    role,
    sessionKey: context.sessionKey,
    files: files.map((file) => path.relative(context.workspaceDir, file.path)),
    missing,
  });
};
