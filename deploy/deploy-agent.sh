#!/usr/bin/env bash
# deploy-agent.sh — Build, push, and run a single-agent Docker image.
#
# Usage:
#   ./deploy/deploy-agent.sh build   chatbot                # Build image locally
#   ./deploy/deploy-agent.sh push    chatbot                # Push to registry
#   ./deploy/deploy-agent.sh run     chatbot                # Run locally
#   ./deploy/deploy-agent.sh deploy  chatbot                # Build + push + run
#   ./deploy/deploy-agent.sh list                           # List available agents
#
# Environment variables:
#   REGISTRY        Container registry prefix (default: "agents")
#   TAG             Image tag (default: "latest")
#   AGENT_MODE      Runtime mode: cli, oneshot, api (default: "api")
#   ENV_FILE        Path to .env file (default: ".env")
#   DOCKER_ARGS     Extra args passed to `docker run`
#
set -euo pipefail

# ── Configuration ────────────────────────────────────────────────────────────
REGISTRY="${REGISTRY:-agents}"
TAG="${TAG:-latest}"
AGENT_MODE="${AGENT_MODE:-api}"
ENV_FILE="${ENV_FILE:-.env}"
DOCKER_ARGS="${DOCKER_ARGS:-}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ── Agent registry (must match bin/run-agent AGENTS dict) ────────────────────
KNOWN_AGENTS=(
    chatbot
    code-analysis
    events
    pr
    red-team
    tasks
    security
    business
)

# Map agent names to their directory under agents/
# Most agents use underscores in their directory name.
declare -A AGENT_DIRS=(
    [chatbot]=chatbot
    [code-analysis]=code_analysis
    [events]=events
    [pr]=pr_agent
    [red-team]=red_team
    [tasks]=task_manager
    [security]=security_researcher
    [business]=business_advisor
)

# ── Helpers ──────────────────────────────────────────────────────────────────

usage() {
    cat <<'USAGE'
deploy-agent.sh — Build, push, and run single-agent Docker images.

Commands:
    build  <agent>    Build Docker image for the agent
    push   <agent>    Push image to container registry
    run    <agent>    Run the agent container locally
    deploy <agent>    Build + push + run (full pipeline)
    list              List available agent names

Examples:
    ./deploy/deploy-agent.sh build chatbot
    ./deploy/deploy-agent.sh deploy security
    REGISTRY=ghcr.io/myorg TAG=v1.2 ./deploy/deploy-agent.sh deploy pr
    AGENT_MODE=oneshot MESSAGE="Hello" ./deploy/deploy-agent.sh run chatbot
USAGE
    exit 0
}

die() { echo "ERROR: $*" >&2; exit 1; }

image_name() {
    local agent="$1"
    echo "${REGISTRY}/${agent}:${TAG}"
}

validate_agent() {
    local agent="$1"
    local dir="${AGENT_DIRS[$agent]:-}"
    if [ -z "$dir" ]; then
        die "Unknown agent '${agent}'. Run '$0 list' to see available agents."
    fi
    if [ ! -d "${PROJECT_ROOT}/agents/${dir}" ]; then
        die "Agent directory 'agents/${dir}' not found."
    fi
}

# ── Commands ─────────────────────────────────────────────────────────────────

cmd_list() {
    echo "Available agents:"
    for name in "${KNOWN_AGENTS[@]}"; do
        local dir="${AGENT_DIRS[$name]}"
        echo "  ${name}  (agents/${dir}/)"
    done
}

cmd_build() {
    local agent="$1"
    validate_agent "$agent"
    local dir="${AGENT_DIRS[$agent]}"
    local img
    img="$(image_name "$agent")"

    echo "==> Building ${img} (agent dir: agents/${dir})"
    docker build \
        -f "${PROJECT_ROOT}/Dockerfile.agent" \
        --build-arg "AGENT_NAME=${dir}" \
        -t "$img" \
        "$PROJECT_ROOT"
    echo "==> Built ${img}"
}

cmd_push() {
    local agent="$1"
    local img
    img="$(image_name "$agent")"

    echo "==> Pushing ${img}"
    docker push "$img"
    echo "==> Pushed ${img}"
}

cmd_run() {
    local agent="$1"
    validate_agent "$agent"
    local img
    img="$(image_name "$agent")"
    local container_name="agent-${agent}"

    # Stop existing container with the same name (if any)
    if docker ps -aq -f "name=^${container_name}$" | grep -q .; then
        echo "==> Stopping existing container ${container_name}"
        docker rm -f "$container_name" >/dev/null 2>&1 || true
    fi

    local run_flags="-d --name ${container_name} -p 8080:8080"
    run_flags+=" -e AGENT_NAME=${agent}"
    run_flags+=" -e AGENT_MODE=${AGENT_MODE}"

    if [ -n "${MESSAGE:-}" ]; then
        run_flags+=" -e MESSAGE=${MESSAGE}"
    fi

    if [ -f "$ENV_FILE" ]; then
        run_flags+=" --env-file ${ENV_FILE}"
    else
        echo "WARNING: ${ENV_FILE} not found. Container may be missing required env vars." >&2
    fi

    # shellcheck disable=SC2086
    echo "==> Running ${img} as ${container_name} (mode: ${AGENT_MODE})"
    docker run ${run_flags} ${DOCKER_ARGS} "$img"
    echo "==> Container ${container_name} started"
    echo "    Logs: docker logs -f ${container_name}"
    if [ "$AGENT_MODE" = "api" ]; then
        echo "    API:  http://localhost:8080/docs"
    fi
}

cmd_deploy() {
    local agent="$1"
    cmd_build "$agent"
    cmd_push  "$agent"
    cmd_run   "$agent"
}

# ── Main ─────────────────────────────────────────────────────────────────────

[ $# -eq 0 ] && usage

CMD="$1"; shift

case "$CMD" in
    build|push|run|deploy)
        [ $# -lt 1 ] && die "${CMD} requires an agent name. Run '$0 list'."
        "$( echo "cmd_${CMD}" )" "$1"
        ;;
    list)
        cmd_list
        ;;
    -h|--help|help)
        usage
        ;;
    *)
        die "Unknown command '${CMD}'. Run '$0 --help'."
        ;;
esac
