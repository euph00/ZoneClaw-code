FROM openclaw:eval

USER root

# Trust the benchmark-local CA used by the mock community forum.
COPY web-content/tls/structflow-forum-ca.crt /usr/local/share/ca-certificates/structflow-forum-ca.crt
COPY web-content/tls/structflow-benchmark-ca.crt /usr/local/share/ca-certificates/structflow-benchmark-ca.crt
RUN update-ca-certificates

# Pre-create the volume mount point with correct ownership so the named
# volume inherits node:node when Docker initialises it on first run.
RUN mkdir -p /home/node/.openclaw && chown node:node /home/node/.openclaw

# Patch: allow private network access for web_fetch when env var is set.
# See injection-userprompt/environment/Dockerfile for full explanation.
RUN find /app/dist -name '*.js' -exec grep -l 'fetchWithWebToolsNetworkGuard' {} \; | \
    xargs sed -i 's/async function fetchWithWebToolsNetworkGuard(params) {/async function fetchWithWebToolsNetworkGuard(params) { if(process.env.OPENCLAW_WEB_FETCH_ALLOW_PRIVATE_NETWORK==="1"){params={...params,policy:{...params.policy,dangerouslyAllowPrivateNetwork:true}};}/g'

# Entrypoint: process date templates, seed workspace, then exec
COPY --chmod=755 entrypoint.sh /usr/local/bin/entrypoint.sh

USER node

# Stage workspace seed files for runtime processing.
# The entrypoint script substitutes date placeholders and copies them into
# the correct locations (OpenClaw workspace) at container start.
COPY workspace-seed/ /tmp/workspace-seed/
COPY openclaw-plugins/ /tmp/openclaw-plugins/

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
