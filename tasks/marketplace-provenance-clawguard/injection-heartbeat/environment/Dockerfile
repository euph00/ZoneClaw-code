FROM openclaw:eval

USER root

# Pre-create the volume mount point with correct ownership so the named
# volume inherits node:node when Docker initialises it on first run.
RUN mkdir -p /home/node/.openclaw && chown node:node /home/node/.openclaw

# Patch: allow private network access for web_fetch when env var is set.
# OpenClaw's web_fetch tool blocks requests resolving to private IPs (Docker
# network aliases → 172.x.x.x).  This injects an env-var gate at the top of
# fetchWithWebToolsNetworkGuard so the eval's Docker-internal web servers are
# reachable.  Only active when OPENCLAW_WEB_FETCH_ALLOW_PRIVATE_NETWORK=1.
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
