# CLI Reference: run-agent

This document describes the command-line interface for `bin/run-agent`, the main entry point for running agents.

## Overview

`bin/run-agent` runs individual agents from the command line in interactive or one-off mode.

```bash
uv run python bin/run-agent <agent> [message] [options]
```

## Basic Usage

### Interactive Mode

Run an agent interactively:

```bash
uv run python bin/run-agent pr
```

You'll enter a conversation loop where you can send multiple messages. Type `exit` or `quit` to end the session.

### One-Off Mode

Run an agent with a single message and exit:

```bash
uv run python bin/run-agent pr "Summarize this article"
```

This is useful for scripting, piping, and automation.

## Available Agents

List all available agents:

```bash
uv run python bin/run-agent --list
```

Or with short flag:

```bash
uv run python bin/run-agent -l
```

Output shows agent names and descriptions:

```
Available agents:
  • business         Business strategy and monetization expert
  • chatbot          General-purpose assistant with all tools
  • code-analysis    Code analyzer for architecture and patterns
  • pr               Content strategy assistant
  • security        AI security expert with RAG search
  • tasks            Task management interface
  [... and more]
```

## Session Management

### Resume Previous Sessions

Resume the most recent session:

```bash
uv run python bin/run-agent pr --resume last
```

Resume a specific session by ID:

```bash
uv run python bin/run-agent pr --resume <session-id>
```

### List Saved Sessions

List all saved sessions:

```bash
uv run python bin/run-agent --sessions
```

List sessions for a specific agent:

```bash
uv run python bin/run-agent --sessions pr
```

Output shows session details including tokens used:

```
All saved sessions:
  SESSION ID                          AGENT              MSGS     TOKENS       UPDATED
  ----------------------------------- ------------------- -------- ------------ --------------------
  a1b2c3d4-e5f6-4a5b-6c7d-8e9f0a1b2c3d pr                  8        12,450       2025-03-04 15:30:42
  ...
```

## Flags and Options

### `-l, --list`

List all available agents and exit.

```bash
uv run python bin/run-agent --list
```

### `-q, --quiet`

Quiet mode: suppress status messages and only output the agent's response. Useful for scripting and piping.

In quiet mode:
- Status messages like "Running Agent..." are suppressed
- Tool calls are shown inline
- Token usage summary is suppressed
- Only the agent's final response is printed

```bash
uv run python bin/run-agent pr -q "List 5 blog ideas"
```

Piping example:

```bash
uv run python bin/run-agent pr -q "Summarize this doc" | head -20
```

### `-r, --resume <SESSION_ID>`

Resume a previous session. Only works in interactive mode (without a message).

```bash
uv run python bin/run-agent pr --resume last
uv run python bin/run-agent pr --resume a1b2c3d4-e5f6-4a5b-6c7d-8e9f0a1b2c3d
```

### `-p, --permissions <PERMISSIONS>`

Restrict the agent to a specific set of permissions. Only works in one-off mode (with a message).

Comma-separated list of permission names. Valid permissions:

- `READ` - Read files and access read-only tools
- `WRITE` - Create and modify files
- `SEND` - Send emails, Slack messages, etc.
- `EXECUTE` - Run shell commands
- `FETCH` - Make HTTP requests to external APIs
- `SEARCH` - Use RAG/search tools
- `MEMORY` - Access persistent memory
- `DELETE` - Delete files and database records

Examples:

```bash
# Only read access
uv run python bin/run-agent pr -p READ "Analyze the codebase"

# Read and fetch (no write or execute)
uv run python bin/run-agent security -p READ,FETCH "Check for vulnerable dependencies"

# Full access (default if not specified)
uv run python bin/run-agent pr -p READ,WRITE,SEND,EXECUTE,FETCH,SEARCH,MEMORY,DELETE "Implement a feature"
```

If you specify invalid permissions, you'll get an error:

```
Unknown permission 'INVALID'. Valid: READ, WRITE, SEND, EXECUTE, FETCH, SEARCH, MEMORY, DELETE
```

### `--skip-failed-mcp`

Skip remote MCP servers that fail to connect (e.g., due to temporary network issues or OAuth token problems) instead of blocking the entire session.

By default, if a remote MCP server fails to connect, the agent startup fails. With this flag, the agent will start with whatever MCP servers are reachable and ignore the unreachable ones.

```bash
uv run python bin/run-agent pr --skip-failed-mcp "Analyze the code"
```

This is useful for:
- CI/CD environments where some OAuth credentials might not be available
- Local development when some MCP servers are offline
- Automated scripts that should continue even if secondary tools are unavailable

## Examples

### Scripting and Automation

```bash
# Generate blog ideas and pipe to a file
uv run python bin/run-agent pr -q "Generate 5 blog ideas for 2025" > blog-ideas.txt

# Quick security check (read-only)
uv run python bin/run-agent security -p READ -q "List the top 3 security risks in this codebase"

# Run in CI without interactive tools
uv run python bin/run-agent pr --skip-failed-mcp "Summarize recent commits"
```

### Session Management

```bash
# Check your recent work
uv run python bin/run-agent --sessions

# Continue yesterday's analysis
uv run python bin/run-agent security --resume last

# Review last PR feedback
uv run python bin/run-agent pr --resume last
```

### Combining Flags

```bash
# One-off with limited permissions and quiet output
uv run python bin/run-agent chatbot -p READ,FETCH -q "Summarize this URL: https://example.com"

# Interactive mode with skipped MCP servers
uv run python bin/run-agent code-analysis --skip-failed-mcp
```

## Interactive Commands

When running an agent in interactive mode, you can use these commands:

- `exit` or `quit` - End the session and save it
- `stats` - Show token usage statistics for the current session
- `reload` - Reconnect to the MCP server to reload tools after editing

## Configuration

The agent behavior is controlled by environment variables in `.env`:

- `ANTHROPIC_API_KEY` (required) - Your Anthropic API key
- `GITHUB_MCP_PAT` (optional) - GitHub personal access token for PR agent
- `NTFY_TOKEN` (optional) - Notification token for alerts
- Other MCP-specific tokens as needed

See `.env.example` for all available options.

## Troubleshooting

### Agent fails to start

- Check that `ANTHROPIC_API_KEY` is set in `.env`
- Verify your API key is valid and has quota remaining
- For GitHub agents, ensure `GITHUB_MCP_PAT` is set if accessing private repositories

### MCP connection fails

- Use `--skip-failed-mcp` flag if some OAuth tokens are unavailable
- Check that required MCP servers are running (if using remote MCP)
- See [docs/REMOTE_MCP.md](REMOTE_MCP.md) for remote setup

### Permission denied

- Ensure you're running with `uv run` or from a Python virtual environment
- Check that dependencies are installed: `uv sync`
- Verify script permissions: `ls -la bin/run-agent`

## See Also

- [docs/AUTOMATION.md](AUTOMATION.md) - Automation scripts for scheduled runs
- [docs/tools.md](tools.md) - MCP tools reference (all available tools)
- [CLAUDE.md](../CLAUDE.md) - Project architecture and development guide
