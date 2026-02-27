# Code Reviewer

Batch code review runner that executes 5 specialized review agents in parallel on a target directory, then emails the combined report and optionally creates GitHub issues for findings.

**This is a standalone script, not an interactive CLI agent.** It does not use the agent registry or `bin/run-agent`.

## Features

- **5 parallel agents** — code optimizer, security reviewer, doc auditor, dependency auditor, test coverage checker
- **Independent timeouts** — each agent gets 10 minutes; failures don't block others
- **Email reports** — styled HTML report sent via FastMail
- **GitHub issues** — auto-creates issues from findings (with duplicate detection)
- **Model selection** — choose between opus, sonnet, or haiku

## Quick Start

```bash
# Run review and email results
uv run python -m agents.code_reviewer.main /path/to/review

# Print to stdout instead of emailing
uv run python -m agents.code_reviewer.main /path/to/review --no-email

# Save report to file
uv run python -m agents.code_reviewer.main /path/to/review --output report.md

# Create GitHub issues from findings
uv run python -m agents.code_reviewer.main /path/to/review --repo owner/name

# Skip issue creation
uv run python -m agents.code_reviewer.main /path/to/review --no-issues

# Use a different model
uv run python -m agents.code_reviewer.main /path/to/review --model sonnet
```

## Review Agents

| Agent | Focus |
|-------|-------|
| `code-optimizer` | Maintainability, duplication, complexity |
| `security-code-reviewer` | Vulnerabilities, security issues |
| `doc-auditor` | Stale/inconsistent documentation |
| `dependency-auditor` | CVEs, outdated packages |
| `test-coverage-checker` | Untested code paths |

## Configuration

```bash
# Required for email delivery
ADMIN_EMAIL_ADDRESS=you@example.com
FASTMAIL_API_TOKEN=...
FASTMAIL_ACCOUNT_ID=...

# Required for GitHub issues
# gh CLI must be authenticated (gh auth login)
```

## Architecture

Each review agent runs in its own Claude Code session via `run_claude_code()`. Results are gathered with `asyncio.gather()`, combined into a markdown report, converted to styled HTML, and emailed. GitHub issues are created by a separate pass that parses the report with Claude.

## Related Documentation

- [CLAUDE.md](../../CLAUDE.md) — project overview
- [docs/CLAUDE_CODE_TOOLS.md](../../docs/CLAUDE_CODE_TOOLS.md) — Claude Code integration
