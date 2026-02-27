# Task Queue

Batch pipeline that fetches actionable tasks from the TaskManager MCP server, triages them with an LLM, and routes them to the orchestrator for execution or pre-research.

**This is a standalone batch processor, not an interactive CLI agent.** It does not use the agent registry or `bin/run-agent`.

## Features

- **Task fetching** — pulls agent-actionable tasks from the remote MCP task server
- **LLM triage** — classifies each task's action type, complexity, and execution strategy
- **Dependency ordering** — computes processing order based on task dependencies
- **Orchestrator dispatch** — routes code tasks to the orchestrator for Claude Code execution
- **Lightweight execution** — handles simple tasks (research, documentation) without full orchestration
- **Pre-research** — gathers context for tasks before execution
- **Slack notifications** — sends run reports with success/failure summaries
- **Comment tracking** — posts progress updates as task comments

## Quick Start

```python
import asyncio
from agents.task_queue.runner import TaskQueueRunner
from agents.task_queue.models import TaskQueueConfig

config = TaskQueueConfig()
runner = TaskQueueRunner(config=config)
report = asyncio.run(runner.run())
```

## Pipeline

```
Fetch tasks (MCP) → Dependency ordering → Triage (LLM) → Route:
  ├─ code/refactor → Orchestrator (Claude Code workers)
  ├─ research/doc  → Lightweight executor
  ├─ blocked       → Mark blocked with reason
  └─ skip          → Log and continue
```

## Configuration

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-...
MCP_SERVER_URL=https://mcp.brooksmcmillin.com/mcp

# Optional
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
```

## Key Modules

- `runner.py` — `TaskQueueRunner` main entry point, fetch/process/report loop
- `triage.py` — LLM-based task classification
- `models.py` — `TaskQueueConfig`, `TriageResult`, `RunReport` data models
- `dependency_graph.py` — computes processing order from task dependencies
- `lightweight_executor.py` — handles simple tasks without full orchestration
- `pre_research.py` — gathers context before task execution

## Architecture

Extends `BatchAgent` for MCP connectivity to the remote task server. Uses the `agents.orchestrator` module for Claude Code-based task execution. Each run produces a `RunReport` with per-task results, which is posted to Slack and logged.

## Related Documentation

- [CLAUDE.md](../../CLAUDE.md) — project overview
- [agents/orchestrator/](../orchestrator/) — task orchestrator (executes code tasks)
- [agents/notifier/](../notifier/) — another standalone service using the task server
