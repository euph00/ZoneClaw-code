FROM openclaw:eval

USER root

RUN mkdir -p /home/node/.openclaw && chown node:node /home/node/.openclaw

COPY --chmod=755 entrypoint.sh /usr/local/bin/entrypoint.sh
COPY --chmod=755 workchat.py /usr/local/bin/workchat

USER node

COPY workspace-seed/ /tmp/workspace-seed/
COPY chat-seed.json /tmp/chat-seed.json
COPY openclaw-plugins/ /tmp/openclaw-plugins/

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
