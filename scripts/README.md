# Utility Scripts

Collection of utility scripts for managing authentication, deployment, and testing.

## Directory Structure

```
scripts/
├── mcp/           # MCP server authentication and testing
├── oauth/         # OAuth token management (social media)
├── deployment/    # Deployment and automation tools
└── README.md      # This file
```

## MCP Scripts (`mcp/`)

Scripts for authenticating with and testing remote MCP servers.

### `mcp_auth.py`

Authenticate with your remote MCP server using OAuth.

```bash
# Authenticate (opens browser)
uv run python scripts/mcp/mcp_auth.py

# Test connection
uv run python scripts/mcp/mcp_auth.py test

# View current configuration
uv run python scripts/mcp/mcp_auth.py config
```

**Required .env variables:**
- `MCP_SERVER_URL`
- `MCP_AUTHORIZE_URL`
- `MCP_TOKEN_URL`
- `MCP_CLIENT_ID`
- `MCP_CLIENT_SECRET`

**What it does:**
1. Opens your browser to the MCP OAuth login page
2. Handles the OAuth callback
3. Exchanges the authorization code for an access token
4. Saves the token to `.env` as `MCP_AUTH_TOKEN`

### `test_mcp_connection.py`

Test direct HTTP connection to remote MCP server.

```bash
uv run python scripts/mcp/test_mcp_connection.py
```

Useful for debugging MCP server connectivity and authentication.

### `debug_mcp_handshake.py`

Debug the MCP protocol handshake with detailed logging.

```bash
uv run python scripts/mcp/debug_mcp_handshake.py
```

Shows detailed protocol messages for troubleshooting.

### `get_mcp_token.py` (Legacy)

Legacy script for manual token retrieval. Use `mcp_auth.py` instead.

## OAuth Scripts (`oauth/`)

Scripts for managing OAuth tokens for social media platforms (Twitter, LinkedIn).

### `manage_tokens.py`

Manage stored OAuth tokens.

```bash
# List all stored tokens
uv run python scripts/oauth/manage_tokens.py list

# Show details for a specific token
uv run python scripts/oauth/manage_tokens.py show twitter

# Refresh an expired token
uv run python scripts/oauth/manage_tokens.py refresh twitter

# Delete a token
uv run python scripts/oauth/manage_tokens.py delete twitter

# Generate encryption key
uv run python scripts/oauth/manage_tokens.py generate-key
```

**Token Storage:**
- Tokens are stored in `./tokens/` directory
- Each token file contains: access_token, refresh_token, expires_at, scope
- Tokens are encrypted using Fernet if `TOKEN_ENCRYPTION_KEY` is set

## Deployment Scripts (`deployment/`)

Scripts for deploying and managing automated tasks.

### `install_notifier.py`

Install and manage the task notifier cron job.

```bash
# Check installation status
uv run python scripts/deployment/install_notifier.py status

# Install cron job (9 AM, 2 PM, 6 PM on weekdays)
uv run python scripts/deployment/install_notifier.py install

# Test notifier manually
uv run python scripts/deployment/install_notifier.py test

# Uninstall cron job
uv run python scripts/deployment/install_notifier.py uninstall
```

**Required .env variables:**
- `SLACK_WEBHOOK_URL`
- `MCP_AUTH_TOKEN` or MCP OAuth credentials
- `MCP_SERVER_URL`

**What it does:**
- Installs a cron job to run the notifier script at scheduled times
- Sends Slack notifications about overdue, due today, and upcoming tasks
- Logs to `/tmp/task-notifier.log`

### `clear_token_cache.py`

Clear cached OAuth tokens.

```bash
uv run python scripts/deployment/clear_token_cache.py
```

**Use when:**
- Getting 401 Unauthorized errors
- Switching between different MCP servers
- OAuth tokens are stale or corrupted

Clears tokens from `~/.agents/tokens/`

## Common Workflows

### First-Time Setup

```bash
# 1. Configure environment
cp .env.example .env
# Edit .env with your API keys

# 2. Authenticate with MCP server (for task_manager/notifier)
uv run python scripts/mcp/mcp_auth.py

# 3. (Optional) Set up social media OAuth
uv run python scripts/oauth/oauth_setup.py twitter
uv run python scripts/oauth/oauth_setup.py linkedin

# 4. (Optional) Install notifier cron job
uv run python scripts/deployment/install_notifier.py install
```

### Troubleshooting Authentication

```bash
# Clear stale tokens
uv run python scripts/deployment/clear_token_cache.py

# Re-authenticate with MCP
uv run python scripts/mcp/mcp_auth.py

# Test connection
uv run python scripts/mcp/test_mcp_connection.py
```

### Managing Notifier

```bash
# Check if notifier is installed
uv run python scripts/deployment/install_notifier.py status

# Test without waiting for cron
uv run python scripts/deployment/install_notifier.py test

# View logs
tail -f /tmp/task-notifier.log

# Uninstall and reinstall (if changing schedule)
uv run python scripts/deployment/install_notifier.py uninstall
# Edit CRON_SCHEDULE in scripts/deployment/install_notifier.py
uv run python scripts/deployment/install_notifier.py install
```

## Security Notes

1. **Never commit tokens or .env files** - They're in .gitignore
2. **Use encryption** - Always set `TOKEN_ENCRYPTION_KEY` in production
3. **Rotate tokens regularly** - Delete and re-authorize periodically
4. **Use HTTPS in production** - The local callback servers use HTTP for development only

## Migration to Database

The OAuth infrastructure is designed for easy migration from file-based storage to database. See comments in `mcp_server/auth/token_store.py` for SQL schema examples.

## Need Help?

- See main [README.md](../README.md) for project overview
- Check [GUIDES.md](../GUIDES.md) for feature-specific documentation
- Review `.env.example` for configuration options
