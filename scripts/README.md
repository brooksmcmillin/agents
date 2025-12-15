# OAuth Scripts

Utility scripts for managing OAuth tokens for:
1. **MCP Server Authentication** - Authenticate with your remote MCP server
2. **Social Media Platforms** - Twitter, LinkedIn, etc.

## MCP Server Authentication

If you're using a remote MCP server that requires OAuth authentication (like `mcp.brooksmcmillin.com`), use this script to authenticate.

### Setup

1. **Register your application** with your OAuth provider:
   - Add `http://localhost:8889/callback` to the allowed redirect URIs
   - Get your Client ID and Client Secret

2. **Configure `.env`:**

```bash
# Remote MCP Server
MCP_SERVER_URL=https://mcp.brooksmcmillin.com/mcp
MCP_AUTHORIZE_URL=https://todo.brooksmcmillin.com/authorize
MCP_TOKEN_URL=https://todo.brooksmcmillin.com/oauth/token
MCP_CLIENT_ID=your_client_id
MCP_CLIENT_SECRET=your_client_secret
MCP_OAUTH_SCOPE=mcp:read mcp:write
```

3. **Run the authentication flow:**

```bash
uv run python scripts/mcp_auth.py
```

This will:
- ✅ Open your browser to the login page
- ✅ Handle the OAuth callback
- ✅ Exchange the code for an access token
- ✅ Save the token to `.env` as `MCP_AUTH_TOKEN`

4. **Test the connection:**

```bash
uv run python scripts/mcp_auth.py test
```

5. **View current configuration:**

```bash
uv run python scripts/mcp_auth.py config
```

Once authenticated, your agents will automatically use the token when connecting to the remote MCP server.

---

## Social Media OAuth

## Setup

### 1. Configure OAuth Credentials

First, register your application with the social media platforms you want to use:

**Twitter/X:**
1. Go to https://developer.twitter.com/en/portal/dashboard
2. Create a new app or use an existing one
3. Add `http://localhost:8888/callback` to "Callback URLs"
4. Copy your Client ID and Client Secret

**LinkedIn:**
1. Go to https://www.linkedin.com/developers/apps
2. Create a new app or use an existing one
3. Add `http://localhost:8888/callback` to "Redirect URLs"
4. Copy your Client ID and Client Secret

### 2. Update .env File

Add your OAuth credentials to `.env`:

```bash
# Twitter/X
TWITTER_CLIENT_ID=your_client_id_here
TWITTER_CLIENT_SECRET=your_client_secret_here

# LinkedIn
LINKEDIN_CLIENT_ID=your_client_id_here
LINKEDIN_CLIENT_SECRET=your_client_secret_here

# Token encryption (optional but recommended)
TOKEN_ENCRYPTION_KEY=generate_using_script_below
```

To generate an encryption key:

```bash
uv run python scripts/manage_tokens.py generate-key
```

## Running OAuth Flow

Run the OAuth flow to authorize and store tokens:

```bash
# For Twitter
uv run python scripts/oauth_setup.py twitter

# For LinkedIn
uv run python scripts/oauth_setup.py linkedin
```

**What happens:**
1. A local web server starts on `http://localhost:8888`
2. Your browser opens to the platform's authorization page
3. You log in and grant permissions
4. You're redirected back to the local server
5. The authorization code is exchanged for an access token
6. The token is encrypted and stored in `./tokens/`

## Managing Tokens

Use the token management script to view, refresh, or delete tokens:

```bash
# List all stored tokens
uv run python scripts/manage_tokens.py list

# Show details for a specific token
uv run python scripts/manage_tokens.py show twitter

# Refresh an expired token
uv run python scripts/manage_tokens.py refresh twitter

# Delete a token
uv run python scripts/manage_tokens.py delete twitter
```

## How It Works

### Token Storage

Tokens are stored in the `./tokens/` directory with the following structure:

```
tokens/
├── twitter_default.token
└── linkedin_default.token
```

Each token file contains:
- `access_token`: The OAuth access token
- `refresh_token`: Token for refreshing the access token (if available)
- `expires_at`: Expiration timestamp
- `scope`: Granted permissions
- `token_type`: Usually "Bearer"

Tokens are encrypted using Fernet symmetric encryption if `TOKEN_ENCRYPTION_KEY` is set.

### Auto-Refresh

The `OAuthHandler` automatically refreshes tokens when they're close to expiring (within 5 minutes). This happens transparently when you use the MCP tools.

### Multi-User Support

The token store supports multiple users. To store tokens for different users:

```python
# In your code
token_store.save_token("twitter", token_data, user_id="user123")

# Or via command line
uv run python scripts/manage_tokens.py show twitter user123
```

## Security Notes

1. **Never commit `.env` files** - Keep your OAuth credentials secret
2. **Use encryption** - Always set `TOKEN_ENCRYPTION_KEY` in production
3. **Restrict file permissions** - Token files are automatically set to `600` (owner read/write only)
4. **Rotate tokens regularly** - Delete and re-authorize periodically
5. **Use HTTPS in production** - The local callback server uses HTTP for development only

## Troubleshooting

**"Failed to connect" error:**
- Check that your Client ID and Secret are correct
- Verify the callback URL is registered in the platform's developer portal
- Make sure port 8888 is not already in use

**"Invalid state parameter" error:**
- This is a security check. Try running the script again
- Make sure you're not opening the authorization URL in a different browser session

**"No refresh token" error:**
- Some platforms require specific scopes to issue refresh tokens
- Twitter requires `offline.access` scope (already included)
- You may need to re-authorize to get a refresh token

**Token expired and can't refresh:**
- Some platforms don't provide refresh tokens
- You'll need to re-run the OAuth flow: `uv run python scripts/oauth_setup.py <platform>`

## Migration to Database

The token store is designed to be easily migrated to a database. See comments in `mcp_server/auth/token_store.py` for SQL schema examples.
