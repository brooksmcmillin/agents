# Task Notifier

Simple notification script that sends Slack updates about your open tasks.

## Features

- Fetches tasks from remote MCP server (same server used by task_manager agent)
- Categorizes tasks into:
  - **Overdue** - Past due date
  - **Due Today** - Due today
  - **Upcoming** - Due in next 3 days
- Sends formatted Slack notifications
- Lightweight - no agent overhead, just fetch and send

## Setup

**For server deployment, see [INSTALL.md](INSTALL.md) for complete step-by-step guide.**

### Quick Setup (Development/Testing):

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

### Server Setup (Production):

See **[INSTALL.md](INSTALL.md)** for complete deployment guide including:
- Installing on remote servers
- Setting up cron jobs
- Managing the installation
- Troubleshooting

## Usage

### Manual Run

```bash
# From project root
uv run python -m agents.notifier.main
```

### Scheduled Notifications (Cron) - RECOMMENDED METHOD

**Use the installation script** for easy setup:

```bash
# Check if installed
uv run python scripts/install_notifier.py status

# Install cron job (9 AM, 2 PM, 6 PM on weekdays)
uv run python scripts/install_notifier.py install

# Test without waiting for cron
uv run python scripts/install_notifier.py test

# Uninstall
uv run python scripts/install_notifier.py uninstall
```

See [INSTALL.md](INSTALL.md) for full details.

### Manual Cron Setup (Alternative)

If you prefer to set up cron manually, see `example_crontab.txt` for examples.

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

## Troubleshooting

### "SLACK_WEBHOOK_URL not set"

Add your webhook URL to `.env`:
```bash
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
```

### OAuth Authentication Issues / Stale Token

**Problem**: Getting 401 Unauthorized even with a valid token in `.env`

**Cause**: The RemoteMCPClient caches OAuth tokens in `~/.claude-code/tokens/` which can override your `.env` token

**Solution**: Clear the cached tokens:
```bash
rm -rf ~/.claude-code/tokens/*.json
uv run python -m agents.notifier.main
```

Or use the helper script:
```bash
uv run python scripts/clear_token_cache.py
```

### No Tasks Showing Up

Check that your tasks are in the remote MCP server:
```bash
# Use the task_manager agent to verify
uv run python -m agents.task_manager.main
```

### Cron Not Working

1. Check cron is running: `systemctl status cron`
2. View cron logs: `tail -f /tmp/task-notifier.log`
3. Test the exact command manually first
4. Make sure the path is absolute in crontab

## Customization

Edit `agents/notifier/main.py` to customize:

- **Time windows**: Change the 3-day upcoming window
- **Task limits**: Show more/fewer tasks per category
- **Message format**: Modify `format_task_message()` function
- **Emoji**: Change emoji icons in the message
- **Filtering**: Add category filters or other criteria

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
