FROM openclaw:local
COPY openai_usage_tap.cjs /tmp/bench-telemetry/openai_usage_tap.cjs
ENV NODE_OPTIONS="--require=/tmp/bench-telemetry/openai_usage_tap.cjs"
ENV BENCH_RAW_API_CAPTURE="alibaba"
