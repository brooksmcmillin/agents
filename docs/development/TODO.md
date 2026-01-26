# Code Optimization TODO

Technical debt and optimization opportunities identified by code analysis.

## High Priority

### Deployment Script Duplication
**Files:**
- `scripts/deployment/install_notifier.py`
- `scripts/deployment/install_slack_adapter.py`

**Problem:** Both scripts share ~95% identical code (768 lines duplicated) including:
- `get_project_root()` - identical implementation
- `status()` - 90% overlap
- `install()` / `uninstall()` - same pattern with different service names
- Environment variable checking logic
- Cron/systemd service management patterns

**Solution:** Create a shared `ServiceInstaller` base class:

```python
# shared/deployment/service_installer.py
from dataclasses import dataclass
from pathlib import Path

@dataclass
class ServiceConfig:
    service_name: str
    service_type: str  # "cron" or "systemd"
    required_env_vars: list[str]
    module_path: str
    cron_schedule: str | None = None

class ServiceInstaller:
    def __init__(self, config: ServiceConfig):
        self.config = config

    def get_project_root(self) -> Path: ...
    def check_prerequisites(self) -> bool: ...
    def status(self) -> None: ...
    def install(self) -> bool: ...
    def uninstall(self) -> bool: ...
```

**Effort:** Medium (4-6 hours)

---

### OAuth Code Duplication
**Files:**
- `shared/oauth_flow.py` (350 lines)
- `scripts/mcp/mcp_auth.py` (510 lines)
- `scripts/mcp/get_mcp_token.py` (157 lines)

**Problem:** Three separate OAuth implementations with similar patterns:
- OAuth callback server logic duplicated 3 times
- Browser opening logic duplicated
- Token exchange logic duplicated
- Different error handling in each version

**Solution:** Consolidate into `shared/oauth_flow.py` and make other scripts thin wrappers:

```python
# scripts/mcp/mcp_auth.py (simplified)
from shared.oauth_config import discover_oauth_config
from shared.oauth_flow import OAuthFlowHandler
from shared.oauth_tokens import TokenStorage

async def main():
    oauth_config = await discover_oauth_config(mcp_url)
    flow = OAuthFlowHandler(oauth_config)
    token = await flow.authorize()
    TokenStorage().save_token(mcp_url, token)
```

**Effort:** Medium (3-4 hours)

---

## Medium Priority

### Two OAuth Handler Implementations
**Files:**
- `config/mcp_server/auth/oauth_handler.py` (289 lines) - For Twitter/LinkedIn OAuth
- `shared/oauth_flow.py` (350 lines) - For MCP server OAuth

**Problem:** ~640 lines total for OAuth handling with similar methods (`refresh_token()`, token storage integration).

**Solution:** Keep `shared/oauth_flow.py` as the primary implementation, make `config/mcp_server/auth/oauth_handler.py` a thin wrapper that delegates to shared flow.

**Effort:** Medium (2-3 hours)

---

### Complex Function in web_analyzer.py
**File:** `packages/agent-framework/agent_framework/tools/web_analyzer.py:369-555`

**Problem:** `analyze_website()` is 186 lines with:
- Three large conditional branches (tone, seo, engagement)
- Nested recommendation generation logic
- Multiple helper function calls
- Complex result dictionary construction

**Solution:** Extract analysis strategy pattern:

```python
class AnalysisStrategy(Protocol):
    def analyze(self, soup: BeautifulSoup, text: str, readability: dict) -> dict: ...
    def generate_recommendations(self, analysis: dict) -> list[str]: ...

class ToneAnalysisStrategy:
    def analyze(self, soup, text, readability): ...
    def generate_recommendations(self, analysis): ...

# strategies dict in analyze_website()
strategies = {
    "tone": ToneAnalysisStrategy(),
    "seo": SEOAnalysisStrategy(),
    "engagement": EngagementAnalysisStrategy()
}
```

**Effort:** Medium (3-4 hours)

---

### Token Storage Interface Duplication
**Files:**
- `config/mcp_server/auth/token_store.py` (217 lines) - Uses Fernet encryption
- `shared/oauth_tokens.py` (188 lines) - Uses plain JSON

**Problem:** Two token storage implementations with similar interfaces but different encryption approaches.

**Solution:** Create unified token storage interface:

```python
# shared/token_storage.py
from abc import ABC, abstractmethod

class TokenStorageBackend(ABC):
    @abstractmethod
    def save_token(self, key: str, token: TokenSet) -> None: ...
    @abstractmethod
    def load_token(self, key: str) -> TokenSet | None: ...
    @abstractmethod
    def delete_token(self, key: str) -> None: ...

class EncryptedFileBackend(TokenStorageBackend): ...
class PlainFileBackend(TokenStorageBackend): ...
```

**Effort:** Medium (2-3 hours)

---

## Low Priority

### Extract Common CLI Patterns
**Problem:** Multiple scripts have similar CLI argument parsing, help text display, and command dispatch logic.

**Solution:** Create a shared CLI utility for consistent command handling.

**Effort:** Small (2 hours)

---

## Completed Quick Wins

- [x] Extract `parse_task_result()` helper in `agents/notifier/main.py`
- [x] Extract `check_env_vars()` utility to `shared/env_utils.py`
- [x] Create `shared/constants.py` for common strings (DEFAULT_MCP_SERVER_URL, ENV_* names)
- [x] Update deployment scripts to use shared `check_env_vars()`
- [x] Update agents to use shared constants
- [x] Verify type hints in `web_analyzer.py` helpers (already complete)

---

## Recommended Refactoring Order

**Phase 1: Quick Wins** (Completed)

**Phase 2: Deployment Scripts** (1-2 days)
1. Create `shared/deployment/service_installer.py`
2. Refactor `install_notifier.py` to use base class
3. Refactor `install_slack_adapter.py` to use base class
4. Test both services

**Phase 3: OAuth Consolidation** (2-3 days)
1. Audit all OAuth flows and document differences
2. Enhance `shared/oauth_flow.py` to support all use cases
3. Migrate `mcp_auth.py` to use shared flow
4. Remove `get_mcp_token.py` (superseded by `mcp_auth.py`)
5. Update platform OAuth handler to delegate to shared flow

**Phase 4: Architecture Improvements** (2-3 days)
1. Extract web analyzer strategies
2. Create unified token storage interface
3. Document architecture decisions

---

## Test Coverage TODO

Current coverage is critically low (17%). Tests have been added for critical security areas.

### Completed Test Files

- [x] `tests/test_token_store.py` - Token security, encryption, expiration (27 tests)
- [x] `tests/test_oauth_handler.py` - OAuth flows, token refresh, authorization URLs (27 tests)
- [x] `tests/test_web_reader.py` - URL validation, content extraction, error handling (27 tests)
- [x] `tests/test_memory_store.py` - Memory storage (existing, 18 tests)

### Pending Test Files (This Sprint)

#### test_web_analyzer.py - Content Analysis Tests
**File:** `packages/agent-framework/agent_framework/tools/web_analyzer.py`
**Priority:** High
**Areas to test:**
- Readability calculations (`_calculate_readability`)
- Tone detection (`_analyze_tone`)
- SEO analysis (`_analyze_seo`)
- Engagement analysis (`_analyze_engagement`)
- Main `analyze_website()` function with all analysis types
- Edge cases: empty content, malformed HTML, very long content

#### test_server.py - MCP Tool Registration Tests
**File:** `config/mcp_server/server.py`
**Priority:** High
**Areas to test:**
- Tool registration in `list_tools()`
- Tool invocation in `call_tool()`
- Error handling for unknown tools
- Parameter validation

#### test_oauth_flow.py - PKCE Implementation Tests
**File:** `shared/oauth_flow.py`
**Priority:** High
**Areas to test:**
- PKCE code verifier/challenge generation
- OAuth callback server
- Token exchange flow
- Error handling

### Backlog Test Files

#### Integration Tests
- End-to-end agent workflows
- MCP client-server communication
- Remote MCP server authentication

#### Performance Tests
- Large payload handling
- Concurrent requests
- Memory usage under load

#### Security Tests
- Fuzz testing for inputs
- SSRF protection (currently documented as gap)
- XSS prevention in content extraction

### Coverage Targets

| Module | Current | Target | Priority |
|--------|---------|--------|----------|
| Auth/Security | ~60% | 90% | HIGH |
| Tools (Web) | ~30% | 80% | HIGH |
| Memory | 93% | 95% | LOW |
| Server | 0% | 85% | HIGH |
| Agents | 0% | 60% | MEDIUM |

### Test Commands

```bash
# Run all tests with coverage
uv run pytest --cov=. --cov-report=term-missing

# Run specific test file
uv run pytest tests/test_token_store.py -v

# Run with HTML coverage report
uv run pytest --cov=. --cov-report=html
```

---

## Security TODO

### High Priority

#### SSRF Protection for Web Tools
**Files:** `packages/agent-framework/agent_framework/tools/web_analyzer.py`, `packages/agent-framework/agent_framework/tools/web_reader.py`

Add IP/hostname validation to prevent Server-Side Request Forgery:
- Block private IP ranges (10.x, 172.16-31.x, 192.168.x)
- Block localhost (127.0.0.1, ::1)
- Block link-local (169.254.x.x)
- Block cloud metadata endpoints (169.254.169.254)
- Validate DNS resolution before request

```python
import ipaddress
from urllib.parse import urlparse

def validate_url_for_ssrf(url: str) -> None:
    parsed = urlparse(url)
    hostname = parsed.hostname

    # Block dangerous hostnames
    dangerous = ["localhost", "127.0.0.1", "0.0.0.0", "169.254.169.254"]
    if hostname.lower() in dangerous:
        raise ValueError(f"Access to {hostname} is not allowed")

    # Resolve and check IP
    import socket
    resolved_ip = socket.gethostbyname(hostname)
    ip = ipaddress.ip_address(resolved_ip)
    if ip.is_private or ip.is_loopback or ip.is_link_local:
        raise ValueError(f"Access to private IP is not allowed")
```

#### Encrypt oauth_tokens.py Token Storage
**File:** `shared/oauth_tokens.py`

Currently stores tokens in plaintext JSON. Add Fernet encryption like `token_store.py`:
1. Add encryption key parameter to TokenStorage
2. Encrypt tokens before writing
3. Decrypt tokens when loading
4. Set file permissions to 600

#### Fix Directory Permissions
**Locations:** `tokens/`, `memories/`

Set directory permissions to 700 (owner only):
```python
self.storage_path.mkdir(parents=True, exist_ok=True)
self.storage_path.chmod(0o700)
```

### Medium Priority

#### Add Rate Limiting to Web Tools
Prevent abuse of web fetching for DoS attacks:
- Per-URL rate limiting (max 10 requests/minute per URL)
- Global rate limiting (max 100 requests/minute total)
- Request size limits

#### Add File Permissions to oauth_tokens.py
**File:** `shared/oauth_tokens.py:134-137`

Add `token_file.chmod(0o600)` after saving tokens.

#### Strengthen Slack Webhook Validation
**File:** `packages/agent-framework/agent_framework/tools/slack.py`

Use regex to validate full webhook URL structure, not just prefix.

### Low Priority

- Sanitize error messages before returning to users
- Consider structured logging with sensitive field masking
- Add security scanning tools (bandit, semgrep) to dev dependencies

---

## Dependency Updates TODO

### Completed Security Updates

- [x] **aiohttp** 3.11.0 → 3.13.3 - Fixed 8 CVEs (DoS, request smuggling)
- [x] **mcp** 1.10.1 → 1.25.0 - Fixed CVE-2025-66416 (DNS rebinding)

### Pending Updates

#### High Priority - License Issue

**Replace html2text with markdownify**
- **Current:** html2text (GPL-3.0 license - strong copyleft)
- **Replacement:** markdownify (MIT license - permissive)
- **File to update:** `packages/agent-framework/agent_framework/tools/web_reader.py`
- **Reason:** GPL-3.0 creates potential licensing complications for distribution
- **Steps:**
  1. Add markdownify to pyproject.toml
  2. Remove html2text from pyproject.toml
  3. Update web_reader.py to use markdownify instead of html2text
  4. Run tests to verify functionality
  5. `uv sync`

#### Medium Priority - Package Updates

| Package | Current | Target | Notes |
|---------|---------|--------|-------|
| certifi | 2025.11.12 | >=2026.1.4 | CA certificates update |
| uvicorn | 0.32.0 | >=0.40.0 | ASGI server improvements |
| sse-starlette | 3.0.3 | >=3.1.2 | MCP SSE transport |

#### Low Priority - Patch Updates

| Package | Notes |
|---------|-------|
| anyio | Bug fixes |
| authlib | Review changelog |
| jsonschema | Minor update |
| python-multipart | Patch fixes |
| soupsieve | Bug fixes |
| pyright (dev) | Dev dependency |
| ruff (dev) | Dev dependency |

### Dependency Audit Commands

```bash
# Check for vulnerabilities
uv run pip-audit

# Check outdated packages
uv pip list --outdated

# Sync after updates
uv sync
```

---

## Notes

- The codebase is generally well-structured with good patterns
- Clean separation between agents, server, and shared utilities
- Consistent async patterns and modern Python typing
- Main opportunities are consolidation and extraction work
- No major architectural changes needed
