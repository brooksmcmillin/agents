# OAuth Infrastructure

**Current State:** Complete OAuth 2.0 implementation with mock data for testing.

## Components

- `mcp_server/auth/oauth_handler.py` - Authorization Code Flow & Client Credentials Flow
- `mcp_server/auth/token_store.py` - Encrypted token storage using Fernet

## To Enable Real APIs

1. Register OAuth apps with Twitter/LinkedIn
2. Add credentials to `.env`:
   ```
   TWITTER_CLIENT_ID=...
   TWITTER_CLIENT_SECRET=...
   LINKEDIN_CLIENT_ID=...
   LINKEDIN_CLIENT_SECRET=...
   ```
3. Uncomment OAuth check in `mcp_server/server.py` `call_tool()`:
   ```python
   token = await oauth_handler.get_valid_token(platform)
   if not token:
       raise PermissionError("Authentication required")
   ```
4. Implement authorization flow UI
5. Replace mock data in tools with real API calls using `token.access_token`

## Token Storage Migration

- File-based storage interface makes migration to database/vault straightforward
- Same interface: `get_token()`, `save_token()`, `delete_token()`
- SQL schema examples available in agent-framework documentation
