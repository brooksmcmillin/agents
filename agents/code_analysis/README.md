# Code Analysis Agent

Critically examines repositories for security vulnerabilities, logic errors, performance issues, and architectural improvements. Creates tracked tasks for every significant finding via a remote MCP task management server.

## Features

- **Security analysis** — OWASP Top 10, CWE patterns, injection flaws, auth weaknesses
- **Logic and correctness** — race conditions, off-by-one errors, unhandled edge cases
- **Performance** — algorithmic complexity, N+1 queries, missing connection pooling
- **Architecture** — SOLID violations, tight coupling, dead code, inconsistent patterns
- **Reliability** — error handling gaps, missing health checks, test coverage holes
- **Task creation** — files actionable tasks with severity, file paths, and line numbers

## Quick Start

```bash
# Requires remote MCP server for task creation
uv run bin/run-agent code-analysis
```

The agent connects to the remote MCP task management server (configured via `MCP_SERVER_URL`) to create and search tasks.

## MCP Tools

- `fetch_web_content` — look up CVE details, best practice references
- `read_file`, `list_directory`, `glob_files`, `grep_files` — navigate and search the codebase
- `save_memory`, `get_memories`, `search_memories` — persist analysis history
- `send_slack_message` — notify on critical findings
- Remote task tools (`get_tasks`, `create_task`, `update_task`, `search_tasks`) — track findings

## Usage Examples

```
You: Analyze /home/user/project for security issues
Agent: [reads project structure, scans for vulnerabilities, creates tasks for findings]

You: Check this repo for performance bottlenecks
Agent: [identifies N+1 queries, unnecessary I/O, missing caching, files tasks]
```

## Configuration

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-...

# Required for task creation
MCP_SERVER_URL=https://mcp.brooksmcmillin.com/mcp

# Optional
FILESYSTEM_ALLOWED_DIRS=/home/user/projects  # directories the agent can read
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
```

## Architecture

Uses `create_simple_agent()` with filesystem, memory, communication tools, and web fetching. Connects to a remote MCP server for task management. Findings are created as tasks with priority mapping: Critical=9-10, High=7-8, Medium=5-6, Low=1-4.

## Related Documentation

- [CLAUDE.md](../../CLAUDE.md) — project overview
- [docs/tools.md](../../docs/tools.md) — MCP tools reference
- [agents/task_manager/](../task_manager/) — interactive task management
