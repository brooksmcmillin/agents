# Task Notifier

Simple notification script that sends Slack updates about your open tasks from a remote MCP server.

## Overview

The notifier is a **lightweight script** (not a full agent) that:
- Fetches tasks from remote MCP server (same server used by task_manager agent)
- Categorizes tasks into: Overdue, Due Today, Upcoming (next 3 days)
- Sends formatted Slack notifications
- Can be run manually or scheduled via cron

## Quick Start

### Development/Testing Setup

1. **Configure environment** (`.env` file):
   ```bash
   SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
   MCP_AUTH_TOKEN=mcp_your_token_here
   MCP_SERVER_URL=https://mcp.brooksmcmillin.com/mcp
   ```

2. **Clear any cached tokens**:
   ```bash
   rm -rf ~/.claude-code/tokens/*.json
   ```

3. **Test the notifier**:
   ```bash
   uv run python -m agents.notifier.main
   ```

## Server Deployment

### Quick Deploy to Server

**1. Clone or sync repository:**
```bash
# SSH to your server
ssh your-server

# Clone repo (if not already there)
git clone https://github.com/your-username/agents.git
cd agents

# Or pull latest changes
git pull origin main
```

**2. Install dependencies:**
```bash
# Install uv if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install project dependencies
uv sync
```

**3. Configure environment:**
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
uv run python scripts/mcp/mcp_auth.py
```

**4. Clear any stale tokens:**
```bash
# Clear cached OAuth tokens that might conflict
rm -rf ~/.claude-code/tokens/*.json

# Or use the helper script
uv run python scripts/deployment/clear_token_cache.py
```

**5. Test the notifier:**
```bash
# Test that everything works
uv run python scripts/deployment/install_notifier.py test
```

If successful, you should see a Slack notification and the message preview in your terminal.

**6. Install the cron job:**
```bash
# Check current status
uv run python scripts/deployment/install_notifier.py status

# Install cron job (will prompt for confirmation)
uv run python scripts/deployment/install_notifier.py install

# Verify installation
uv run python scripts/deployment/install_notifier.py status
```

Done! You'll now get notifications at 9 AM, 2 PM, and 6 PM (Mon-Fri).

## Managing the Cron Job

### Check Status
```bash
uv run python scripts/deployment/install_notifier.py status
```

### View Logs
```bash
tail -f /tmp/task-notifier.log
```

### Test Manually
```bash
uv run python scripts/deployment/install_notifier.py test
```

### Uninstall
```bash
uv run python scripts/deployment/install_notifier.py uninstall
```

### Reinstall (if you change schedule)
```bash
uv run python scripts/deployment/install_notifier.py uninstall
# Edit CRON_SCHEDULE in scripts/deployment/install_notifier.py
uv run python scripts/deployment/install_notifier.py install
```

## Message Format

The script sends a formatted Slack message like this:

```
*Task Update - Monday, December 21, 2025 at 09:00 AM*

⚠️ *3 Overdue Tasks*
❗ High priority task (due: 2025-12-18)
🔸 Regular task (due: 2025-12-19)
🔸 Another task (due: 2025-12-20)

📅 *2 Tasks Due Today*
⭐ Important meeting prep
🔹 Code review

🔮 *5 Upcoming Tasks (Next 3 Days)*
• Task A (due: 2025-12-22)
• Task B (due: 2025-12-23)
• Task C (due: 2025-12-24)
...and 2 more
```

## Customization

### Change Notification Schedule

Edit `scripts/deployment/install_notifier.py`:

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

### Change Log File Location

Edit `scripts/deployment/install_notifier.py`:

```python
# Line ~14
LOG_FILE = "/tmp/task-notifier.log"  # Change to your preferred location
```

### Customize Message Format

Edit `agents/notifier/main.py` in the `format_task_message()` function to change:
- Time windows (currently 3 days for upcoming)
- Number of tasks shown (currently 5 per category)
- Emoji used for priorities
- Message structure

## Deployment Checklist

Use this checklist when deploying to a new server.

### Pre-Deployment
- [ ] Server has SSH access configured
- [ ] You have your Slack webhook URL handy
- [ ] You have your MCP auth token (or can generate one)

### On the Server

**System Prerequisites:**
- [ ] Install uv: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- [ ] Verify cron is installed: `which crontab`
  - If not: `sudo apt install cron` (Ubuntu/Debian) or `sudo pacman -S cronie` (Arch)
- [ ] Start cron service: `sudo systemctl enable --now cron` (or `cronie` on Arch)

**Repository Setup:**
- [ ] Clone repository: `git clone <repo-url> && cd agents`
  - OR: Pull latest: `git pull origin main`
- [ ] Install dependencies: `uv sync`

**Configuration:**
- [ ] Copy `.env.example` to `.env`: `cp .env.example .env`
- [ ] Edit `.env` with required values:
  - [ ] `SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...`
  - [ ] `MCP_AUTH_TOKEN=mcp_...` (or generate with `uv run python scripts/mcp/mcp_auth.py`)
  - [ ] `MCP_SERVER_URL=https://mcp.brooksmcmillin.com/mcp`
- [ ] Verify `.env` is not committed to git: `git check-ignore .env` (should output `.env`)

**Token Management:**
- [ ] Clear any stale tokens: `rm -rf ~/.claude-code/tokens/*.json`
- [ ] If needed, generate new token: `uv run python scripts/mcp/mcp_auth.py`

**Testing:**
- [ ] Test notifier manually: `uv run python scripts/deployment/install_notifier.py test`
- [ ] Verify Slack notification was received
- [ ] Check output for any errors

**Installation:**
- [ ] Check installation status: `uv run python scripts/deployment/install_notifier.py status`
- [ ] Install cron job: `uv run python scripts/deployment/install_notifier.py install`
- [ ] Verify installation: `crontab -l | grep task-notifier`

**Verification:**
- [ ] Check status again: `uv run python scripts/deployment/install_notifier.py status`
- [ ] Wait for next scheduled run OR test again: `uv run python scripts/deployment/install_notifier.py test`
- [ ] Monitor logs: `tail -f /tmp/task-notifier.log`

### Post-Deployment

**First Day:**
- [ ] Verify notifications arrive at scheduled times (9 AM, 2 PM, 6 PM)
- [ ] Check logs for any errors: `cat /tmp/task-notifier.log`
- [ ] Confirm Slack messages are well-formatted

**First Week:**
- [ ] Monitor notification reliability
- [ ] Check if schedule needs adjustment
- [ ] Verify task data is accurate

## Troubleshooting

### "SLACK_WEBHOOK_URL not set"

Add your webhook URL to `.env`:
```bash
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
```

### OAuth Authentication Issues / Stale Token

**Problem:** Getting 401 Unauthorized even with a valid token in `.env`

**Cause:** The RemoteMCPClient caches OAuth tokens in `~/.claude-code/tokens/` which can override your `.env` token

**Solution:** Clear the cached tokens:
```bash
rm -rf ~/.claude-code/tokens/*.json
uv run python -m agents.notifier.main
```

Or use the helper script:
```bash
uv run python scripts/deployment/clear_token_cache.py
```

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

### "401 Unauthorized" Errors

Your MCP token is stale. Get a new one:
```bash
# Clear cache
rm -rf ~/.claude-code/tokens/*.json

# Get new token
uv run python scripts/mcp/mcp_auth.py

# Test
uv run python scripts/deployment/install_notifier.py test
```

### Notifications Not Sending

1. Check cron is running: `sudo systemctl status cron`
2. Check logs: `tail -f /tmp/task-notifier.log`
3. Verify cron job is installed: `crontab -l | grep task-notifier`
4. Test manually: `uv run python scripts/install_notifier.py test`

### Slack Webhook Not Working

1. Verify webhook URL in `.env` is correct
2. Test webhook directly:
```bash
curl -X POST -H 'Content-type: application/json' \
  --data '{"text":"Test from command line"}' \
  YOUR_WEBHOOK_URL
```

### No Tasks Showing Up

Check that your tasks are in the remote MCP server:
```bash
# Use the task_manager agent to verify
uv run python -m agents.task_manager.main
```

## Useful Commands

```bash
# View cron job
crontab -l

# Edit cron job manually (not recommended, use install script instead)
crontab -e

# Check cron service
sudo systemctl status cron  # Ubuntu/Debian
sudo systemctl status cronie # Arch

# View logs
tail -f /tmp/task-notifier.log

# Clear logs
echo '' > /tmp/task-notifier.log

# Test authentication
uv run python scripts/mcp/mcp_auth.py test

# Clear token cache
uv run python scripts/deployment/clear_token_cache.py
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

## Rollback Plan

If something goes wrong:
1. Uninstall cron job: `uv run python scripts/deployment/install_notifier.py uninstall`
2. Check logs: `cat /tmp/task-notifier.log`
3. Test manually to debug: `uv run python scripts/deployment/install_notifier.py test`

## Quick Reference

| Issue | Solution |
|-------|----------|
| 401 Unauthorized | Clear tokens, regenerate: `rm -rf ~/.claude-code/tokens/*.json && uv run python scripts/mcp/mcp_auth.py` |
| Cron not running | Check service: `sudo systemctl status cron`, start: `sudo systemctl start cron` |
| No notifications | Check logs: `tail -f /tmp/task-notifier.log` |
| Wrong schedule | Edit `scripts/deployment/install_notifier.py`, then uninstall/reinstall |
| Slack webhook fails | Test manually: `curl -X POST -d '{"text":"test"}' YOUR_WEBHOOK_URL` |

## Architecture

This is a **script**, not a full agent:

- No interactive loop
- No conversation context
- Just: fetch tasks → format → send

For interactive task management, use the full `task_manager` agent instead.

## Integration with ntfy (Optional)

To add ntfy notifications alongside Slack:

1. Install ntfy: https://ntfy.sh/docs/install/
2. Modify `main.py` to send to both Slack and ntfy
3. Use simpler messages for ntfy (it's just a notification service)

Example ntfy addition:
```python
# Add to main.py
async def send_ntfy_notification(message: str, topic: str = "tasks"):
    async with httpx.AsyncClient() as client:
        await client.post(
            f"https://ntfy.sh/{topic}",
            data=message.encode('utf-8'),
            headers={"Title": "Task Update"}
        )
```
