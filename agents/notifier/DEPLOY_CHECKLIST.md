# Task Notifier Deployment Checklist

Use this checklist when deploying to a new server.

## Pre-Deployment

- [ ] Server has SSH access configured
- [ ] You have your Slack webhook URL handy
- [ ] You have your MCP auth token (or can generate one)

## On the Server

### 1. System Prerequisites
- [ ] Install uv: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- [ ] Verify cron is installed: `which crontab`
  - If not: `sudo apt install cron` (Ubuntu/Debian) or `sudo pacman -S cronie` (Arch)
- [ ] Start cron service: `sudo systemctl enable --now cron` (or `cronie` on Arch)

### 2. Repository Setup
- [ ] Clone repository: `git clone <repo-url> && cd agents`
  - OR: Pull latest: `git pull origin main`
- [ ] Install dependencies: `uv sync`

### 3. Configuration
- [ ] Copy `.env.example` to `.env`: `cp .env.example .env`
- [ ] Edit `.env` with required values:
  - [ ] `SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...`
  - [ ] `MCP_AUTH_TOKEN=mcp_...` (or generate with `uv run python scripts/mcp_auth.py`)
  - [ ] `MCP_SERVER_URL=https://mcp.brooksmcmillin.com/mcp`
- [ ] Verify `.env` is not committed to git: `git check-ignore .env` (should output `.env`)

### 4. Token Management
- [ ] Clear any stale tokens: `rm -rf ~/.claude-code/tokens/*.json`
- [ ] If needed, generate new token: `uv run python scripts/mcp_auth.py`

### 5. Testing
- [ ] Test notifier manually: `uv run python scripts/install_notifier.py test`
- [ ] Verify Slack notification was received
- [ ] Check output for any errors

### 6. Installation
- [ ] Check installation status: `uv run python scripts/install_notifier.py status`
- [ ] Install cron job: `uv run python scripts/install_notifier.py install`
- [ ] Verify installation: `crontab -l | grep task-notifier`

### 7. Verification
- [ ] Check status again: `uv run python scripts/install_notifier.py status`
- [ ] Wait for next scheduled run OR test again: `uv run python scripts/install_notifier.py test`
- [ ] Monitor logs: `tail -f /tmp/task-notifier.log`

## Post-Deployment

### First Day
- [ ] Verify notifications arrive at scheduled times (9 AM, 2 PM, 6 PM)
- [ ] Check logs for any errors: `cat /tmp/task-notifier.log`
- [ ] Confirm Slack messages are well-formatted

### First Week
- [ ] Monitor notification reliability
- [ ] Check if schedule needs adjustment
- [ ] Verify task data is accurate

## Rollback Plan

If something goes wrong:
1. Uninstall cron job: `uv run python scripts/install_notifier.py uninstall`
2. Check logs: `cat /tmp/task-notifier.log`
3. Test manually to debug: `uv run python scripts/install_notifier.py test`

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
uv run python scripts/mcp_auth.py test

# Clear token cache
uv run python scripts/clear_token_cache.py
```

## Troubleshooting Reference

| Issue | Solution |
|-------|----------|
| 401 Unauthorized | Clear tokens, regenerate: `rm -rf ~/.claude-code/tokens/*.json && uv run python scripts/mcp_auth.py` |
| Cron not running | Check service: `sudo systemctl status cron`, start: `sudo systemctl start cron` |
| No notifications | Check logs: `tail -f /tmp/task-notifier.log` |
| Wrong schedule | Edit `scripts/install_notifier.py`, then uninstall/reinstall |
| Slack webhook fails | Test manually: `curl -X POST -d '{"text":"test"}' YOUR_WEBHOOK_URL` |
