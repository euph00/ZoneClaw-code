FROM openclaw:eval

USER root

# Install Himalaya
RUN mkdir -p /usr/local/bin && \
    curl -sL https://github.com/pimalaya/himalaya/releases/download/v1.2.0/himalaya.x86_64-linux.tgz \
      | tar -xz -C /tmp && \
    mv /tmp/himalaya /usr/local/bin/himalaya && \
    chmod +x /usr/local/bin/himalaya

# Pre-create the volume mount point with correct ownership so the named
# volume inherits node:node when Docker initialises it on first run.
RUN mkdir -p /home/node/.openclaw && chown node:node /home/node/.openclaw

# Entrypoint: process date templates, seed inbox + workspace + skills, then exec
COPY --chmod=755 entrypoint.sh /usr/local/bin/entrypoint.sh

USER node

# Himalaya config
RUN mkdir -p /home/node/.config/himalaya
COPY himalaya-config.toml /home/node/.config/himalaya/config.toml

# Maildir inbox layout
RUN mkdir -p /home/node/.mail/INBOX/new \
             /home/node/.mail/INBOX/cur \
             /home/node/.mail/INBOX/tmp

# Stage email templates and workspace seed files for runtime processing.
# The entrypoint script substitutes date placeholders and copies them into
# the correct locations (Maildir inbox + OpenClaw workspace) at container start.
COPY inbox-templates/ /tmp/inbox-templates/
COPY workspace-seed/ /tmp/workspace-seed/
COPY openclaw-plugins/ /tmp/openclaw-plugins/

# Stage Himalaya skill for runtime copy (volume mounts override build-time files)
RUN mkdir -p /tmp/openclaw-skills-seed && \
    cp -r /app/skills/himalaya /tmp/openclaw-skills-seed/himalaya

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
