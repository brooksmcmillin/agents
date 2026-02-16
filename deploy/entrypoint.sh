#!/usr/bin/env bash
# Container entrypoint for single-agent images.
#
# Modes (set via AGENT_MODE env var):
#   cli     — interactive terminal session (default)
#   oneshot — process a single MESSAGE and exit
#   api     — start the REST API server serving this agent
#
set -euo pipefail

AGENT_MODE="${AGENT_MODE:-cli}"
MESSAGE="${MESSAGE:-}"

echo "==> Starting agent '${AGENT_NAME}' in ${AGENT_MODE} mode"

case "${AGENT_MODE}" in
    cli)
        exec uv run python bin/run-agent "${AGENT_NAME}"
        ;;
    oneshot)
        if [ -z "${MESSAGE}" ]; then
            echo "ERROR: AGENT_MODE=oneshot requires MESSAGE env var" >&2
            exit 1
        fi
        exec uv run python bin/run-agent "${AGENT_NAME}" "${MESSAGE}"
        ;;
    api)
        exec uv run python -m api
        ;;
    *)
        echo "ERROR: Unknown AGENT_MODE '${AGENT_MODE}'. Use: cli, oneshot, api" >&2
        exit 1
        ;;
esac
