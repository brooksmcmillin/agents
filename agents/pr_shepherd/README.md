# PR Shepherd

Async service that polls open pull requests, fixes CI failures using Claude Code workers, and auto-merges when checks pass.

**This is a standalone daemon, not an interactive CLI agent.** It does not use the agent registry or `bin/run-agent`.

## Features

- **CI monitoring** — polls GitHub for open PRs and checks their CI status
- **Automated fixes** — spawns Claude Code workers to fix failing checks
- **Auto-merge** — merges PRs when all checks pass (configurable merge method)
- **Retry limits** — abandons PRs after configurable max fix attempts
- **Review comments** — includes PR review comments in fix instructions
- **Multi-repo** — monitors multiple repositories in a single instance
- **Dry run** — preview actions without making changes

## Quick Start

```python
import asyncio
from agents.pr_shepherd.main import PRShepherd
from agents.pr_shepherd.models import PRShepherdConfig

config = PRShepherdConfig(
    repos=["owner/repo"],
    poll_interval=60,
    max_fix_attempts=3,
    merge_method="squash",
)

shepherd = PRShepherd(config)
asyncio.run(shepherd.run())
```

For a single pass (no polling loop):

```python
tracked = asyncio.run(shepherd.run_once())
```

## Configuration

```python
PRShepherdConfig(
    repos=["owner/repo1", "owner/repo2"],  # repos to monitor
    poll_interval=60,          # seconds between polls
    max_fix_attempts=3,        # retries before abandoning
    merge_method="squash",     # squash, merge, or rebase
    label_filter="auto-merge", # only process PRs with this label (optional)
    worker_model="sonnet",     # model for fix workers
    worker_timeout=600,        # seconds per fix attempt
    dry_run=False,             # preview mode
)
```

Requires `gh` CLI authenticated (`gh auth login`) for GitHub operations.

## PR Lifecycle

```
Open PR → Check CI status
  ├─ passing  → auto-merge
  ├─ failing  → spawn Claude Code worker to fix
  │              ├─ fix succeeds → push, wait for CI
  │              └─ fix fails / max attempts → abandon
  └─ pending  → skip, check next poll
```

## Architecture

Stateless polling loop — fix attempt counts are recovered from PR comment history on each cycle. All GitHub interaction uses the `gh` CLI (via `github_ops.py`). CI fixes are done by cloning the repo into a Claude Code workspace, checking out the PR branch, and running Claude with the failing logs.

**Key modules:**
- `main.py` — `PRShepherd` class with polling loop and fix logic
- `models.py` — `PRShepherdConfig`, `TrackedPR`, `PRStatus`
- `github_ops.py` — `gh` CLI wrappers for PR operations
- `prompts.py` — fix instruction templates

## Related Documentation

- [CLAUDE.md](../../CLAUDE.md) — project overview
- [docs/CLAUDE_CODE_TOOLS.md](../../docs/CLAUDE_CODE_TOOLS.md) — Claude Code integration
- [agents/orchestrator/](../orchestrator/) — task orchestrator (shared workspace utilities)
