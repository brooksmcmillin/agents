# Tenuo.ai Evaluation for Multi-Agent System

**Date:** 2026-03-02
**Status:** Evaluation / Recommendation

## What Is Tenuo?

[Tenuo](https://github.com/tenuo-ai/tenuo) is an open-source (MIT/Apache-2.0)
cryptographic capability-token library for AI agents. It enforces least-privilege
authorization at the tool-call level using signed, attenuated **warrants** that
expire when tasks end.

Core analogy: warrants work like a **prepaid debit card** (scoped, ephemeral,
expiring) rather than a **corporate Amex** (ambient, broad, persistent).

Key properties:
- **Offline verification in ~27 microseconds** -- no network calls needed
- **Monotonic attenuation** -- authority can only shrink as it delegates
- **Proof-of-possession** -- stolen tokens are useless without the signing key
- **Semantic constraints** -- parses URLs, paths, and shell commands the way
  target systems interpret them (not naive string matching)
- **Rust core with Python bindings** -- `uv pip install tenuo`

Current version: **v0.1 Beta** (core semantics stable, APIs may evolve).

## Our Current Security Architecture

This repo already has layered authorization. Here is how each layer maps to what
Tenuo offers:

### 1. Permission System (`agent_framework/permissions/`)

| Aspect | Current Implementation | With Tenuo |
|--------|----------------------|------------|
| **Model** | `PermissionSet` enum (READ, WRITE, DELETE, EXECUTE, SEND, ADMIN) | Capability tokens with typed constraints |
| **Enforcement** | Python `if` checks in `_check_tool_permissions()` | Cryptographic verification (~27 us) |
| **Delegation** | `ExecutionContext.delegate_to()` intersects permissions | Warrant attenuation -- authority shrinks cryptographically |
| **Granularity** | 6 coarse permissions mapped to tools via `TOOL_PERMISSIONS` dict | Per-argument constraints (e.g., `send_email` only to `*@company.com`) |
| **Bypass risk** | A bug in permission checking code could skip the gate | Cryptographic -- no code path can bypass verification |

**Assessment:** Our permission system is well-designed (intersection on
delegation, fail-secure defaults for unknown tools). Tenuo would add
cryptographic enforcement and finer granularity, but requires migrating the
existing `PermissionSet` model. This is the **highest-effort, highest-payoff**
change.

### 2. SSRF Protection (`agent_framework/security/ssrf.py`)

| Aspect | Current Implementation | With Tenuo |
|--------|----------------------|------------|
| **Pre-check** | `SSRFValidator.is_safe_url()` blocks private IPs, metadata endpoints | `UrlSafe()` constraint type |
| **DNS rebinding** | `SSRFTransport` validates at TCP connect time | Not addressed (Tenuo authorizes, doesn't isolate) |
| **Redirect validation** | Per-hop validation in `validate_request_with_redirects()` | Not addressed |

**Assessment:** Our SSRF protection is **more comprehensive** than what Tenuo
provides. `SSRFTransport` handles DNS rebinding (TOCTOU) at the TCP layer, which
Tenuo's `UrlSafe()` does not. **Keep our existing SSRF implementation.** Tenuo's
`UrlSafe()` could be layered on top as an additional pre-check but would not
replace the custom transport.

### 3. Filesystem Access (`tools/filesystem.py`)

| Aspect | Current Implementation | With Tenuo |
|--------|----------------------|------------|
| **Path validation** | `FilesystemValidator` with `FILESYSTEM_ALLOWED_DIRS` env var | `Subpath("/data/allowed")` constraint |
| **Symlink defense** | `Path.resolve()` before validation | Tenuo `Subpath` also resolves |
| **Traversal defense** | Rejects `..` segments + `relative_to()` check | Handled by `Subpath` |

**Assessment:** Roughly equivalent. Tenuo's `Subpath` is a clean replacement but
doesn't add significant security beyond what we already have. Low-priority swap.

### 4. HTTP Client / Red Team (`tools/http_client.py`)

| Aspect | Current Implementation | With Tenuo |
|--------|----------------------|------------|
| **Target allowlist** | `REDTEAM_ALLOWED_TARGETS` env var, parsed per-request | `UrlPattern()` or `Exact()` constraint in warrant |
| **Redirect protection** | Manual per-hop validation against allowlist | Not addressed |

**Assessment:** Our redirect-aware validation is stronger. Tenuo could issue
warrants that scope red-team agents to specific targets with TTLs, which is a
nice ergonomic improvement but not a security uplift.

### 5. Orchestrator Workers (`agents/orchestrator/workers.py`)

| Aspect | Current Implementation | With Tenuo |
|--------|----------------------|------------|
| **Input sanitization** | Regex stripping + `shlex.quote()` + git ref validation | Tenuo `Shlex()` constraint |
| **Worker authority** | `skip_permissions=True` -- workers get full tool access | Attenuated warrants scoped to workspace + branch + TTL |
| **Workspace isolation** | Directory-based isolation, validated paths | `Subpath()` per workspace |

**Assessment:** This is the **strongest fit**. Today, orchestrator workers run
with `skip_permissions=True`, meaning they have unrestricted tool access. Tenuo
could issue attenuated warrants per worker:

```python
from tenuo import mint, Capability, Subpath, Exact
from datetime import timedelta

worker_warrant = await mint(
    Capability("run_claude_code", workspace=Subpath(f"/workspaces/{task.id}")),
    Capability("git_push", branch=Exact(f"orchestrator/{task.id}-fix")),
    ttl=timedelta(minutes=30),
)
```

This would be the single biggest security improvement: converting autonomous
workers from ambient authority to task-scoped, time-limited, cryptographic
authorization.

### 6. Claude Code Subprocess (`tools/claude_code.py`)

| Aspect | Current Implementation | With Tenuo |
|--------|----------------------|------------|
| **Env filtering** | `_ALLOWED_ENV_KEYS` allowlist | Not addressed (Tenuo doesn't sandbox) |
| **Tool allowlist** | `_DEFAULT_ALLOWED_TOOLS` list | Could be warrant-scoped |
| **Output sanitization** | `LLMOutputSanitizer` with pattern blocking | Not addressed |

**Assessment:** Tenuo complements but doesn't replace our subprocess isolation.
The env filtering and output sanitization are defense-in-depth layers that Tenuo
has no equivalent for.

### 7. MCP Tool Gating

| Aspect | Current Implementation | With Tenuo |
|--------|----------------------|------------|
| **Tool filtering** | `allowed_tools` list in agent constructor | `tenuo[mcp]` integration wraps tool calls |
| **Enforcement** | MCP client only exposes allowed tools to Claude | Cryptographic -- even if tool is discovered, can't call without warrant |

**Assessment:** Good fit. Currently, tool filtering is a code-level allowlist. An
LLM that discovers tool names through other means (e.g., prompt injection) could
potentially reference tools outside its allowlist. Tenuo's MCP integration adds a
cryptographic gate at execution time.

## Integration Compatibility

Tenuo explicitly supports our stack:

| Component | Tenuo Extra | Notes |
|-----------|-------------|-------|
| MCP server/client | `tenuo[mcp]` | Python >= 3.10 |
| FastAPI (API server) | `tenuo[fastapi]` | Header-based warrant verification |
| Agent-to-agent delegation | `tenuo[a2a]` | Warrant-based inter-agent auth |
| Python | Core | 3.9 - 3.14, binary wheels (no Rust needed) |
| uv | Core | `uv pip install tenuo` |

**Not yet available:** TypeScript/Node SDK (planned for v0.2), which means the
React web UI cannot do client-side warrant validation. Server-side enforcement
via FastAPI middleware would cover this.

## Recommendation

### Phase 1: Orchestrator Workers (High Impact, Medium Effort)

**Why:** Workers currently run with `skip_permissions=True`. This is the widest
privilege gap in the system. Tenuo's attenuation model is purpose-built for
exactly this pattern: orchestrator mints broad warrant, attenuates per-worker
with workspace path, git branch, and TTL constraints.

**Steps:**
1. `uv pip install "tenuo[mcp]"`
2. Configure Tenuo with a signing key in orchestrator startup
3. Mint root warrant in `Orchestrator.run()`
4. Attenuate per-task in `dispatch_worker()` with:
   - `Subpath` for workspace directory
   - `Exact` for git branch name
   - `ttl` for task timeout
5. Pass warrant context to `run_claude_code()`
6. Verify warrant in Claude Code tool handler

### Phase 2: MCP Tool Authorization (Medium Impact, Medium Effort)

**Why:** Adds cryptographic enforcement to the existing `allowed_tools`
filtering. Prevents prompt-injection-driven tool access outside the agent's
intended scope.

**Steps:**
1. Add `@guard(tool="tool_name")` decorators to MCP tool handlers
2. Mint per-agent warrants at session start with appropriate capabilities
3. Existing `TOOL_PERMISSIONS` mapping informs which capabilities each agent gets

### Phase 3: FastAPI Endpoint Scoping (Medium Impact, Low Effort)

**Why:** Currently all authenticated API consumers get equal access. Tenuo's
FastAPI integration enables per-consumer capability scoping.

**Steps:**
1. `uv pip install "tenuo[fastapi]"`
2. Add `TenuoGuard` dependency to agent endpoints
3. Issue warrants to API consumers with appropriate agent/tool scopes

### Not Recommended

- **Replacing SSRF protection** -- Our `SSRFTransport` with DNS-rebinding defense
  is more comprehensive than Tenuo's `UrlSafe()`.
- **Replacing filesystem validation** -- Roughly equivalent; migration cost
  outweighs benefit.
- **Full permission system migration** -- High effort, should wait until Tenuo
  reaches v1.0 stable.

## Risks and Considerations

1. **Beta status (v0.1)** -- APIs may evolve. Core semantics are stable, but
   breaking changes are possible before v1.0.
2. **Rust binary dependency** -- Binary wheels are provided, but exotic
   platforms may need a Rust toolchain.
3. **New dependency** -- Adds a security-critical dependency. Tenuo's Rust core
   is a positive (memory safety), but the project is young.
4. **Learning curve** -- Team needs to understand capability-token model vs.
   traditional RBAC.
5. **No TypeScript SDK yet** -- Web UI can't do client-side verification until
   v0.2.

## Conclusion

Tenuo is a strong fit for this repo, particularly for the **orchestrator worker
delegation** pattern where the privilege gap is widest. It complements (rather
than replaces) our existing security layers. The phased approach lets us capture
the highest-value improvements first while the library matures toward v1.0.

**Start with Phase 1** (orchestrator workers) as a proof of concept. If it
proves out, Phase 2 (MCP tool gating) hardens the entire tool boundary
cryptographically.

## References

- [Tenuo GitHub](https://github.com/tenuo-ai/tenuo)
- [Tenuo Website](https://tenuo.ai/)
- [Tenuo Rust Crate](https://crates.io/crates/tenuo)
- Current security implementation: `packages/agent-framework/agent_framework/security/`
- Current permissions: `packages/agent-framework/agent_framework/permissions/`
- Orchestrator workers: `agents/orchestrator/workers.py`
