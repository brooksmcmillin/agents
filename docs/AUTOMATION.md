# Automation Scripts

This document describes the automation scripts for running agents on schedules and in headless environments.

## Overview

The automation scripts are designed for:
- Cron jobs and scheduled runs
- CI/CD pipelines
- Headless deployments
- Unattended automation flows

They include built-in error handling, alerting, and wiki page logging.

## Scripts

### sprint-or-review

Attempts to sprint on open tasks from TaskManager, falling back to code review if no tasks are available. Creates a wiki page documenting results.

**Location:** `bin/sprint-or-review`

**Usage:**

```bash
sprint-or-review <directory> [options]
```

**Arguments:**

- `<directory>` - Path to the git repository to work on (required)

**Options:**

- `-c, --category NAME` - TaskManager category/project name (required)
- `-m, --max-tasks NUM` - Maximum number of tasks to sprint on (default: 4)
- `-n, --per-day NUM` - Code review: number of tasks to create per day (default: 2)
- `-s, --start DATE` - Code review: start date for task due dates in YYYY-MM-DD format (default: tomorrow)
- `-a, --agents AGENTS` - Code review: comma-separated agent names (default: all 5)
- `-d, --dry-run` - Print what would run without executing
- `-h, --help` - Show help

**Available review agents:**

- `code-optimizer`
- `dependency-auditor`
- `doc-auditor`
- `security-code-reviewer`
- `test-coverage-checker`

**Examples:**

```bash
# Sprint on tasks, create PRs
sprint-or-review ~/build/agents -c "Code Quality"

# Sprint up to 2 tasks, then code review
sprint-or-review ~/build/agents -c "Code Quality" -m 2

# Code review with custom agents
sprint-or-review ~/build/agents -c "Code Review" -a security-code-reviewer,test-coverage-checker

# Create 3 tasks per day starting March 10
sprint-or-review ~/build/agents -c "Code Quality" -n 3 -s 2025-03-10

# Preview what would run
sprint-or-review ~/build/agents -c "Code Quality" --dry-run
```

**How it works:**

1. **Phase 1: Check for tasks** - Queries TaskManager for open pending tasks in the specified category
2. **Phase 2a: Sprint (if tasks exist)**
   - Takes up to `--max-tasks` pending tasks
   - For each task:
     - Assesses feasibility
     - Creates a git worktree
     - Spawns a sub-agent to implement the fix
     - Creates a PR with results
     - Monitors CI (up to 5 iterations)
     - Merges when CI passes and review is clean
   - Cleans up worktrees
   - Logs results to wiki
3. **Phase 2b: Code Review (if no tasks)**
   - Runs specified code review agents
   - Analyzes codebase
   - Creates new tasks from findings
   - Schedules tasks due `--per-day` starting `--start`
   - Logs results to wiki

**Requirements:**

- Bash 4.0+
- Git
- GitHub CLI (`gh`)
- Python 3.7+
- `claude` CLI installed
- TaskManager OAuth token in `~/.claude/.credentials.json`
- `NTFY_TOKEN` in `.env` (for alerts on failure)

**Output:**

- Creates wiki pages at: `automation-log/<category>/<category>-YYYY-MM-DD-HHMM>`
- Sends ntfy push notifications on errors
- Logs to stdout (captures full output in session JSONL)

### weekly-pr-review

Analyzes all merged PRs from the past N days, identifying security issues, process gaps, and trends.

**Location:** `bin/weekly-pr-review`

**Usage:**

```bash
weekly-pr-review <directory> [options]
```

**Arguments:**

- `<directory>` - Path to the git repository to review (required)

**Options:**

- `-c, --category NAME` - TaskManager category/project name (required)
- `--days N` - Number of days to look back (default: 7)
- `-d, --dry-run` - Print what would run without executing
- `-h, --help` - Show help

**Examples:**

```bash
# Weekly PR review for a repo
weekly-pr-review ~/build/agents -c "PR Review"

# Review last 14 days
weekly-pr-review ~/build/agents -c "PR Review" --days 14

# Review last 30 days
weekly-pr-review ~/build/agents -c "Security Review" --days 30

# Preview what would run
weekly-pr-review ~/build/agents -c "PR Review" --dry-run
```

**How it works:**

1. **Pre-fetch PR data** - Efficiently fetches merged PR list and per-PR details (files, comments, review decisions) using `gh` CLI
2. **Analyze** - Claude analyzes PR data for:
   - Executive summary (health, highlights, concerns)
   - Security patterns and new attack surface
   - Process quality issues (missing tests, vague descriptions, large diffs, rubber-stamping)
   - Bot/CI review quality (findings vs noise, blind spots)
   - Codebase trends (high-churn files, complexity growth, consistency)
   - Action items (urgent, todo, watch)
3. **Create tasks** (optional) - If issues warrant follow-up, creates tasks in TaskManager
4. **Log to wiki** - Documents analysis at: `automation-log/<category>/<category>-week-YYYY-MM-DD-HHMM>`

**Requirements:**

- Bash 4.0+
- Git
- GitHub CLI (`gh`) with repository access
- Python 3.7+
- `claude` CLI installed
- TaskManager OAuth token in `~/.claude/.credentials.json`
- `NTFY_TOKEN` in `.env` (for alerts on failure)

**Output:**

- Creates wiki pages at: `automation-log/<category>/<category>-week-YYYY-MM-DD-HHMM>`
- Optionally creates TaskManager tasks from findings
- Sends ntfy push notifications on errors
- Logs to stdout and file

## Cron Installers

Two helper scripts install cron jobs for the automation scripts.

### install-sprint-cron

Installs a daily cron job for `sprint-or-review`.

**Location:** `bin/install-sprint-cron`

**Usage:**

```bash
install-sprint-cron <directory> <category> <HH:MM>
```

**Arguments:**

- `<directory>` - Path to the git repository
- `<category>` - TaskManager category name (quote if it has spaces)
- `<HH:MM>` - Time to run daily in 24-hour format (e.g., `02:30`, `15:00`)

**Examples:**

```bash
install-sprint-cron ~/build/agents "Code Quality" 02:30
install-sprint-cron ~/build/taskmanager "Task Manager" 03:00
```

**What it does:**

1. Validates all arguments and prerequisites
2. Checks for existing cron job for the same directory (idempotent)
3. Creates log directory at `~/.local/log`
4. Installs cron line that:
   - Sources `.env` for `NTFY_TOKEN`
   - Sets `PATH` to include `~/.local/bin` (for `claude`)
   - Runs `sprint-or-review` with your arguments
   - Redirects output to log file

**Verify installation:**

```bash
crontab -l | grep sprint-or-review
```

**Remove a job:**

```bash
crontab -l | grep -v '<directory>' | crontab -
```

**View logs:**

```bash
tail -f ~/.local/log/sprint-or-review.log
```

### install-weekly-review-cron

Installs a weekly cron job for `weekly-pr-review`.

**Location:** `bin/install-weekly-review-cron`

**Usage:**

```bash
install-weekly-review-cron <directory> <category> <day-of-week> <HH:MM>
```

**Arguments:**

- `<directory>` - Path to the git repository
- `<category>` - TaskManager category name (quote if it has spaces)
- `<day-of-week>` - Day to run: name (monday, mon) or number (0-6, 0=Sunday)
- `<HH:MM>` - Time to run in 24-hour format (e.g., `09:00`, `15:30`)

**Day-of-week formats:**

- Names: `sunday`, `monday`, `tuesday`, `wednesday`, `thursday`, `friday`, `saturday`
- Short: `sun`, `mon`, `tue`, `wed`, `thu`, `fri`, `sat`
- Numbers: `0` (Sunday) through `6` (Saturday)

**Examples:**

```bash
# Every Monday at 9:00 AM
install-weekly-review-cron ~/build/agents "PR Review" monday 09:00

# Every Friday at 2:00 PM
install-weekly-review-cron ~/build/agents "PR Review" fri 14:00

# Every Wednesday at 10:00 AM
install-weekly-review-cron ~/build/taskmanager "Security" 3 10:00
```

**What it does:**

1. Validates all arguments and prerequisites
2. Checks for existing cron job for the same directory (idempotent)
3. Offsets time by 5 minutes to avoid collision with token refresh crons
4. Creates log directory at `~/.local/log`
5. Installs cron line that:
   - Sources `.env` for `NTFY_TOKEN`
   - Sets `PATH` to include `~/.local/bin` (for `claude`)
   - Runs `weekly-pr-review` with your arguments
   - Redirects output to log file

**Verify installation:**

```bash
crontab -l | grep weekly-pr-review
```

**Remove a job:**

```bash
crontab -l | grep -v '<directory>' | grep -v 'weekly-pr-review' | crontab -
```

**View logs:**

```bash
tail -f ~/.local/log/weekly-pr-review.log
```

## Environment Setup

Before using automation scripts, ensure your environment is properly configured.

### Prerequisites

- `.env` file in project root with `NTFY_TOKEN` set:

```bash
cp .env.example .env
# Edit .env and add:
NTFY_TOKEN=your_ntfy_bearer_token
```

- TaskManager OAuth credentials:

```bash
# Authenticate with TaskManager
claude --init
# Follow the device auth flow to get credentials
```

Credentials are stored at `~/.claude/.credentials.json`.

### Testing

Test your setup before installing cron jobs:

```bash
# Test sprint-or-review
sprint-or-review ~/build/agents -c "Code Quality" --dry-run

# Test weekly-pr-review
weekly-pr-review ~/build/agents -c "PR Review" --dry-run

# Test actual run (monitor the output)
sprint-or-review ~/build/agents -c "Code Quality" -m 2
```

## Wiki Pages

Automation scripts create hierarchical wiki pages to document results.

**Page structure:**

```
automation-log/                                  # Root
├── code-quality/                               # Category
│   ├── code-quality-2025-03-04-0230/           # Sprint run
│   ├── code-quality-2025-03-05-0230/
│   └── code-quality-week-2025-03-04-0905/      # Weekly review run
└── security/
    ├── security-2025-03-04-0300/
    └── security-week-2025-03-04-0905/
```

Each run creates a page documenting:
- **Sprint run:** Tasks attempted, PRs created, merge status, notes
- **Code review run:** Agents run, findings, tasks created, priorities, due dates

Access wiki pages in TaskManager to review automation history.

## Troubleshooting

### OAuth token expired

If you see "Token Expired" alerts:

```bash
claude --init
# Re-authenticate with TaskManager
```

### Missing commands

If cron installer says commands are missing:

```bash
# Install claude CLI
curl -LsSf https://claude.sh/install.sh | sh

# Or with Homebrew
brew install claude

# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install GitHub CLI
brew install gh  # macOS
sudo apt-get install gh  # Ubuntu/Debian
```

### Logs not found

Check log directory:

```bash
ls -la ~/.local/log/
tail -f ~/.local/log/sprint-or-review.log
tail -f ~/.local/log/weekly-pr-review.log
```

### Cron job not running

- Verify cron is running: `systemctl status cron` (Linux) or `sudo launchctl list | grep cron` (macOS)
- Check logs: `tail -f ~/.local/log/sprint-or-review.log`
- Verify PATH: `crontab -l | grep sprint-or-review`
- Test manually: run the command directly from `~/.local/log` directory

## See Also

- [docs/CLI.md](CLI.md) - Run-agent CLI reference
- [docs/GUIDES.md](GUIDES.md) - Feature guides and setup
- [CLAUDE.md](../CLAUDE.md) - Project architecture
