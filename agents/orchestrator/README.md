# Orchestrator

Task-driven agentic orchestrator that decomposes tasks, dispatches Claude Code workers in parallel, and publishes PRs.

**This is a standalone CLI tool, not an interactive CLI agent.** It does not use the agent registry or `bin/run-agent`.

## Features

- **Task decomposition** — uses Claude to break tasks into subtasks with dependency ordering
- **Parallel workers** — runs Claude Code sessions concurrently for independent subtasks
- **Autonomy tiers** — 4 levels from fully autonomous to manual-only
- **Git integration** — clones repos, creates branches, pushes fixes
- **Task files** — batch-process tasks from a JSON file
- **Dry run** — plan decomposition without executing workers

## Quick Start

```bash
# Run a single task
uv run python -m agents.orchestrator.main "Implement rate limiting on /api/auth" \
    --repo https://github.com/user/project.git \
    --tier 2

# Dry run (plan only)
uv run python -m agents.orchestrator.main "Add caching layer" --dry-run

# Run from a task file
uv run python -m agents.orchestrator.main --file tasks.json

# Skip decomposition (single worker)
uv run python -m agents.orchestrator.main "Fix typo in README" --no-decompose

# Use a specific model for workers
uv run python -m agents.orchestrator.main "Add tests" --worker-model opus
```

## Autonomy Tiers

| Tier | Behavior |
|------|----------|
| 1 | Fully autonomous — auto-merge PRs |
| 2 | Propose and execute — create PR, wait for review (default) |
| 3 | Propose and wait — create plan, wait for approval |
| 4 | Manual only — report findings, take no action |

## Task File Format

```json
[
  {
    "title": "Add input validation",
    "description": "Validate all user inputs in the API layer",
    "priority": 7,
    "autonomy_tier": 2,
    "tags": ["security", "api"],
    "category": "backend"
  }
]
```

## CLI Options

| Flag | Description |
|------|-------------|
| `--repo URL` | Git repo to clone for workspace |
| `--workspace NAME` | Use existing workspace |
| `--tier 1-4` | Autonomy tier (default: 2) |
| `--priority 1-10` | Task priority (default: 5) |
| `--file PATH` | Load tasks from JSON file |
| `--dry-run` | Plan only, don't execute |
| `--no-decompose` | Skip decomposition, run as single task |
| `--worker-model` | Model for workers: sonnet, haiku, opus |
| `--max-tasks N` | Safety limit (default: 20) |
| `--external-id ID` | Link to external task (e.g., task_386) |

## Architecture

The orchestrator is a state machine (`state_machine.py`) that manages tasks through states: pending → planning → executing → completed/failed/awaiting_human. The planner (`planner.py`) uses Claude to decompose tasks into subtasks. Workers are Claude Code sessions managed via `agent_framework.tools.claude_code`.

**Key modules:**
- `main.py` — CLI entry point and task file loading
- `models.py` — Task, AutonomyTier, OrchestratorConfig data models
- `planner.py` — LLM-based task decomposition
- `state_machine.py` — orchestration loop and state management

## Related Documentation

- [CLAUDE.md](../../CLAUDE.md) — project overview
- [docs/CLAUDE_CODE_TOOLS.md](../../docs/CLAUDE_CODE_TOOLS.md) — Claude Code integration
- [agents/task_queue/](../task_queue/) — batch pipeline that feeds into the orchestrator
