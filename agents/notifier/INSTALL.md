# Task Notifier - Server Deployment Guide

## Quick Deploy to Server

### 1. Clone or sync the repository on your server

```bash
# SSH to your server
ssh your-server

# Clone repo (if not already there)
git clone https://github.com/your-username/agents.git
cd agents

# Or pull latest changes
git pull origin main
```

### 2. Install dependencies

```bash
# Install uv if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install project dependencies
uv sync
```

### 3. Configure environment

```bash
# Copy example and edit
cp .env.example .env
nano .env  # or vim, etc.

# Required variables:
# SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
# MCP_AUTH_TOKEN=mcp_your_token_here
# MCP_SERVER_URL=https://mcp.brooksmcmillin.com/mcp
```

**Getting an MCP auth token:**
```bash
uv run python scripts/mcp_auth.py
```

### 4. Clear any stale tokens (important!)

```bash
# Clear cached OAuth tokens that might conflict
rm -rf ~/.claude-code/tokens/*.json

# Or use the helper script
uv run python scripts/clear_token_cache.py
```

### 5. Test the notifier

```bash
# Test that everything works
uv run python scripts/install_notifier.py test
```

If successful, you should see a Slack notification and the message preview in your terminal.

### 6. Install the cron job

```bash
# Check current status
uv run python scripts/install_notifier.py status

# Install cron job (will prompt for confirmation)
uv run python scripts/install_notifier.py install

# Verify installation
uv run python scripts/install_notifier.py status
```

Done! You'll now get notifications at 9 AM, 2 PM, and 6 PM (Mon-Fri).

## Managing the Cron Job

### Check status
```bash
uv run python scripts/install_notifier.py status
```

### View logs
```bash
tail -f /tmp/task-notifier.log
```

### Test manually (without waiting for cron)
```bash
uv run python scripts/install_notifier.py test
```

### Uninstall
```bash
uv run python scripts/install_notifier.py uninstall
```

### Reinstall (if you change schedule)
```bash
uv run python scripts/install_notifier.py uninstall
# Edit CRON_SCHEDULE in scripts/install_notifier.py
uv run python scripts/install_notifier.py install
```

## Customization

### Change notification schedule

Edit `scripts/install_notifier.py`:

```python
# Line ~13
CRON_SCHEDULE = "0 9,14,18 * * 1-5"  # Current: 9 AM, 2 PM, 6 PM on weekdays

# Examples:
# Every 4 hours:        "0 9,13,17,21 * * *"
# Twice daily:          "0 9,17 * * *"
# Once daily at 9 AM:   "0 9 * * *"
# Monday mornings only: "0 9 * * 1"
```

Then reinstall the cron job.

### Change log file location

Edit `scripts/install_notifier.py`:

```python
# Line ~14
LOG_FILE = "/tmp/task-notifier.log"  # Change to your preferred location
```

### Customize message format

Edit `agents/notifier/main.py` in the `format_task_message()` function to change:
- Time windows (currently 3 days for upcoming)
- Number of tasks shown (currently 5 per category)
- Emoji used for priorities
- Message structure

## Troubleshooting

### "crontab command not found"

Install cron on your server:
```bash
# Ubuntu/Debian
sudo apt install cron
sudo systemctl enable cron
sudo systemctl start cron

# Arch Linux
sudo pacman -S cronie
sudo systemctl enable cronie
sudo systemctl start cronie
```

### "401 Unauthorized" errors

Your MCP token is stale. Get a new one:
```bash
# Clear cache
rm -rf ~/.claude-code/tokens/*.json

# Get new token
uv run python scripts/mcp_auth.py

# Test
uv run python scripts/install_notifier.py test
```

### Notifications not sending

1. Check cron is running: `sudo systemctl status cron`
2. Check logs: `tail -f /tmp/task-notifier.log`
3. Verify cron job is installed: `crontab -l | grep task-notifier`
4. Test manually: `uv run python scripts/install_notifier.py test`

### Slack webhook not working

1. Verify webhook URL in `.env` is correct
2. Test webhook directly:
```bash
curl -X POST -H 'Content-type: application/json' \
  --data '{"text":"Test from command line"}' \
  YOUR_WEBHOOK_URL
```

## Multiple Servers

You can install this on multiple servers. Each server will:
- Need its own `.env` file
- Use the same MCP server (shared task list)
- Send to the same Slack channel (or configure different webhooks)

To avoid duplicate notifications, consider:
1. Only install on one server
2. Use different Slack channels per server
3. Use different schedules per server
