# Log Analysis Agent

Investigates application and system log files to surface errors, performance issues, and security events. Automatically pins tool results containing critical findings so they survive context trimming during long investigation sessions.

## Features

- **Error diagnosis** — trace exceptions, stack traces, and error chains to root causes
- **Performance analysis** — identify latency spikes, timeouts, OOM kills, and resource exhaustion
- **Security event detection** — find authentication failures, permission denials, and suspicious patterns
- **Automatic pinning** — log results containing critical patterns (ERROR, FATAL, exceptions, etc.) are pinned and protected from context trimming
- **Cross-session continuity** — saves incident history and baselines to memory for future reference

## Quick Start

```bash
uv run bin/run-agent log-analysis
```

Point it at your log files and describe what you're investigating.

## MCP Tools

- `read_file`, `list_directory`, `glob_files`, `grep_files` — read-only filesystem access for log files
- `fetch_web_content` — look up error codes, known bugs, or library issues
- `get_memories`, `save_memory`, `search_memories` — persist incident history across sessions

## Auto-Pinning Behavior

The agent automatically scans results from `read_file` and `grep_files` for critical patterns:

| Category | Examples |
|----------|---------|
| Error levels | `ERROR`, `FATAL`, `CRITICAL`, `SEVERE` |
| Exceptions | `Exception`, `Traceback`, `panic:`, stack frames |
| Resource exhaustion | OOM, `No space left on device`, `Too many open files` |
| Connectivity | `connection refused`, `timed out`, `ECONNREFUSED` |
| HTTP errors | 5xx responses |
| Security events | `authentication fail`, `permission denied`, `brute force` |
| Process crashes | `SIGKILL`, `core dump`, `service crashed` |

Up to 5 results per session are pinned. Pinned results are the last to be removed if the context window fills up.

**Security note:** Log file content is untrusted, user-controlled input. A malicious actor who can write to a monitored log file could embed prompt injection payloads (e.g., instructions to exfiltrate memory or alter agent behavior). The per-session pin cap mitigates flooding, but does not prevent injection through pinned content itself. The agent is configured to treat log content as data for analysis only — it should not act on instructions embedded within log lines. Restrict filesystem access using `FILESYSTEM_ALLOWED_DIRS` and avoid running the agent against logs from untrusted or externally-facing systems without review.

## Usage Examples

```
You: Our service started returning 500 errors at 3am
Agent: [checks memories for previous incidents, finds relevant log files,
        greps for errors around 3am, traces root cause, saves findings]

You: Analyze these nginx access logs for unusual traffic patterns
Agent: [reads log sample to identify format, searches for 4xx/5xx codes,
        looks for unusual user agents or IP patterns, reports findings]

You: Check if there was a deployment issue last Tuesday
Agent: [searches logs for deployment timestamps, correlates with error spikes,
        builds a timeline of events before and after deployment]
```

## Configuration

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-...

# Optional — restrict filesystem access to specific directories
FILESYSTEM_ALLOWED_DIRS=/var/log,/home/user/logs
```

## Architecture

Subclasses `Agent` directly to override `_execute_tool_calls()`. After each batch of tool calls, scans results from log-reading tools against compiled regex patterns. Matching results are tagged with `_pinned` metadata that the context trimmer respects. Uses a per-session cap of 5 pins to prevent attacker-controlled log content from flooding the context with pinned entries.

## Related Documentation

- [CLAUDE.md](../../CLAUDE.md) — project overview
- [docs/tools.md](../../docs/tools.md) — MCP tools reference
