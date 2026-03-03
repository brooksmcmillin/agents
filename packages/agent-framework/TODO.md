# TODO

## Security Improvements

### Medium Priority

- [x] **Secure Token File Permissions** (`agent_framework/oauth/oauth_tokens.py`)
  - Token files created with `os.open()` and `0o600` permissions
  - Token directories set to `0o700`

- [ ] **Add OAuth State Parameter** (`agent_framework/oauth/oauth_flow.py`)
  - Add state parameter validation in OAuth callback to prevent CSRF attacks
  - Generate random state in `authorize()`, validate in callback handler
  - Reference: OAuth 2.0 Security Best Current Practice

### Low Priority

- [ ] **Enforce HTTPS for OAuth Discovery** (`agent_framework/oauth/oauth_config.py:67-166`)
  - Validate that OAuth discovery only occurs over HTTPS
  - Add check at start of `discover_oauth_config()` function

- [ ] **Add SSRF Protection** (`agent_framework/oauth/oauth_config.py:67-166`)
  - Validate and sanitize URLs in OAuth discovery
  - Consider blocking private IP ranges (localhost, 10.x, 192.168.x, 172.16.x)
  - Reference: CWE-918

### Tooling

- [x] **Install SAST Tools**
  - ✅ `bandit` configured in `.pre-commit-config.yaml` and `pyproject.toml`
  - Run manually: `pre-commit run bandit --all-files`
