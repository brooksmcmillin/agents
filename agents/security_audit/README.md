# Security Audit Agent

Analyzes structured JSON security audit reports produced by the non-LLM security audit collector. Provides prioritized findings with actionable remediation steps, tracks improvements over time, and supports cross-host comparison.

## Features

- **Prioritized findings** — critical-first breakdown with severity ratings (critical, high, medium, low)
- **Actionable remediation** — specific commands and config changes to fix each issue
- **Trend tracking** — compare audits over time using memory to track improvements
- **Cross-host comparison** — identify systemic issues across multiple machines
- **Two collector options** — Rust binary (zero dependencies) or Python script

## Quick Start

### 1. Run the Collector on Target Machines

**Option A — Rust binary (recommended, zero runtime dependencies):**

```bash
cd agents/security_audit/collector-rs && cargo build --release
scp target/release/security-audit-collector user@host:~
ssh user@host ./security-audit-collector
```

**Option B — Python script (requires Python 3.10+):**

```bash
scp agents/security_audit/collector.py user@host:~
ssh user@host python3 collector.py
```

Both options produce identical JSON reports saved to `~/.agents/security_audits/` by default.

### 2. Analyze Reports

```bash
uv run bin/run-agent security-audit
```

Then ask: "Analyze the latest audit report"

## MCP Tools

- `read_file`, `list_directory`, `glob_files`, `grep_files` — read audit reports from the filesystem
- `fetch_web_content` — look up CVEs and security advisories
- `get_memories`, `save_memory`, `search_memories` — persist audit findings for trend tracking
- `send_email`, `send_slack_message` — deliver audit summaries

## Audit Report Format

Reports are JSON with metadata, check results, and a severity summary:

```json
{
  "metadata": {
    "version": "1.0",
    "timestamp": "2025-01-01T00:00:00+00:00",
    "hostname": "server-name"
  },
  "results": {
    "ssh_config": { "status": "completed", "data": { ... } },
    "open_ports": { "status": "completed", "data": { ... } }
  },
  "summary": {
    "total_findings": 5,
    "by_severity": { "critical": 1, "high": 2, "medium": 1, "low": 1 }
  }
}
```

Default report directory: `~/.agents/security_audits/`

## Severity Classification

| Severity | Examples |
|----------|---------|
| **Critical** | `PermitRootLogin yes`, world-writable `/etc/shadow`, UID 0 non-root user |
| **High** | Password auth enabled for SSH, world-readable `.env` files, weak password hashes |
| **Medium** | IP forwarding enabled, NOPASSWD sudo rules, ICMP redirects accepted |
| **Low** | X11 forwarding enabled, unnecessary services, dmesg unrestricted |

## Usage Examples

```
You: Analyze the latest audit report
Agent: [lists audit directory, reads latest report, groups findings by severity,
        provides specific remediation commands, saves results to memory]

You: Compare the audits across all my servers
Agent: [reads latest report for each hostname, identifies systemic issues,
        presents cross-host summary with per-host details]

You: Did we fix the issues from last time?
Agent: [recalls previous findings from memory, reads latest report,
        reports which issues are resolved vs. persisting, updates memory]
```

## Configuration

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-...

# Optional — override default audit report directory
FILESYSTEM_ALLOWED_DIRS=~/.agents/security_audits

# Optional — for sending reports
FASTMAIL_API_TOKEN=...
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
```

## Architecture

Uses `create_simple_agent()` with filesystem, memory, communication, and web fetching tools. The two-part design keeps the collector dependency-free (no LLM, no pip packages) so it can run on any Linux host, while the analyzer uses the full agent framework to provide intelligent interpretation and trend tracking.

## Related Documentation

- [CLAUDE.md](../../CLAUDE.md) — project overview
- [docs/tools.md](../../docs/tools.md) — MCP tools reference
- [agents/system_admin/](../system_admin/) — live network scanning and system auditing
