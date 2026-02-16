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

# ── Validate AGENT_NAME ─────────────────────────────────────────────────────
# Only allow lowercase alphanumerics, underscores, and hyphens.
if [[ ! "${AGENT_NAME:-}" =~ ^[a-z][a-z0-9_-]*$ ]]; then
    echo "ERROR: AGENT_NAME must match ^[a-z][a-z0-9_-]*$ (got '${AGENT_NAME:-}')" >&2
    exit 1
fi

# ── Validate AGENT_MODE ─────────────────────────────────────────────────────
case "${AGENT_MODE}" in
    cli|oneshot|api) ;; # valid
    *)
        echo "ERROR: Unknown AGENT_MODE '${AGENT_MODE}'. Use: cli, oneshot, api" >&2
        exit 1
        ;;
esac

echo "==> Starting agent '${AGENT_NAME}' in ${AGENT_MODE} mode"

case "${AGENT_MODE}" in
    cli)
        exec uv run python bin/run-agent "${AGENT_NAME}"
        ;;
    oneshot)
        if [ -z "${MESSAGE:-}" ]; then
            echo "ERROR: AGENT_MODE=oneshot requires MESSAGE env var" >&2
            exit 1
        fi
        # MESSAGE is read from the environment by Python directly — it never
        # appears as a shell argument.  This avoids any metacharacter or
        # command-injection risk.
        exec uv run python deploy/oneshot.py
        ;;
    api)
        exec uv run python -m api
        ;;
esac
