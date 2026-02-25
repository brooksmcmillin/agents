# Live Demo Script

One demo, three steps. Total runtime ~10 seconds. No API keys or database required.

## Setup

```bash
# From the project root
uv sync
```

## Running

```bash
# Full demo (all 3 steps)
uv run python scripts/demo_live.py

# Individual steps
uv run python scripts/demo_live.py memory     # Step 1
uv run python scripts/demo_live.py ssrf       # Step 2
uv run python scripts/demo_live.py trimming   # Step 3
```

---

## Step 1 — Memory Namespace Isolation

**What you're showing:** Two agents share the same memory backend but are completely isolated from each other. Same query, different results.

**Command:**
```bash
uv run python scripts/demo_live.py memory
```

**What happens:**
1. Saves a memory under `DemoAgent-Alpha`: *"launching rocket to Mars next quarter"*
2. Saves a memory under `DemoAgent-Beta`: *"building underwater data center in the Pacific"*
3. Searches both namespaces for "project" — each agent only sees its own memory
4. Cross-check: Alpha searches for "underwater" → 0 results (Beta's content is invisible)

**Talking points:**
- Every agent gets its own namespace. The framework auto-injects `agent_name` on every memory tool call — the LLM can't accidentally (or deliberately) read another agent's memories.
- On disk: separate `memories/<AgentName>/memories.json` directories. In Postgres: `WHERE agent_name = $1` on every query with a composite primary key.
- Agent name validation blocks path traversal (`../`), null bytes, and non-alphanumeric characters.

**Key code:**
- Auto-injection: `Agent._call_mcp_tool_with_reconnect()` in `core/agent.py`
- Namespace validation: `validate_agent_name()` in `tools/memory.py`
- File isolation: `MemoryStore.__init__()` in `storage/memory_store.py`
- DB isolation: `DatabaseMemoryStore` — `WHERE agent_name = $1` on every query

---

## Step 2 — SSRF + Permission Denial

**What you're showing:** Capability bounding at three layers — URL validation, tool permissions, and permission intersection on delegation.

**Command:**
```bash
uv run python scripts/demo_live.py ssrf
```

**What happens:**

**Layer 1 — SSRF URL validation:**
- `https://example.com/api/data` → allowed
- `http://192.168.1.1/admin` → blocked (private IP)
- `http://169.254.169.254/latest/meta-data/` → blocked (cloud metadata)
- `http://localhost:8080/internal` → blocked (localhost)
- `file:///etc/passwd` → blocked (bad scheme)

**Layer 2 — Tool permissions:**
- Shows the permission matrix: each tool requires specific capabilities (READ, WRITE, SEND, EXECUTE, DELETE)
- Email-triggered agent with `{READ, SEND}` can fetch web content and search memories, but **cannot** save memories (WRITE), delete emails (DELETE), or run code (EXECUTE)

**Layer 3 — Permission intersection:**
- `EmailIntakeAgent` (READ + SEND) delegates to `CodeReviewAgent` (full access)
- Result: CodeReviewAgent only gets READ + SEND (intersection of both)
- Agents can never gain MORE permissions through delegation

**Talking points:**
- SSRF validator checks schemes, blocks private ranges (RFC1918, loopback, link-local), cloud metadata IPs, and resolves DNS to catch rebinding attacks.
- For redirects: `validate_request_with_redirects()` manually follows redirects, validating each hop — no auto-follow that could be tricked.
- Tool permissions are checked at the enforcement layer (`_check_tool_permissions`) before every tool call, not at the LLM prompt level.
- Unknown tools default to requiring ADMIN — fail-safe, not fail-open.
- Permission intersection means a low-privilege caller can never escalate by delegating to a high-privilege agent.

**Key code:**
- SSRF validator: `SSRFValidator` in `security/ssrf.py`
- Permission check: `Agent._check_tool_permissions()` in `core/agent.py`
- Tool permission map: `TOOL_PERMISSIONS` in `permissions/tool_permissions.py`
- ExecutionContext delegation: `ExecutionContext.delegate_to()` in `permissions/context.py`

---

## Step 3 — Security Events Survive Trimming

**What you're showing:** When conversations get long, the framework trims old messages to stay within context limits — but security events (SSRF blocks, permission denials, prompt injection detections) are **pinned** and survive trimming.

**Command:**
```bash
uv run python scripts/demo_live.py trimming
```

**What happens:**
1. Builds a 44-message conversation with 40 normal messages and 2 security events:
   - SSRF block (tried to fetch `169.254.169.254`)
   - Permission denial (tried to send unauthorized email)
2. Shows classification: 2 messages are CRITICAL, rest are NORMAL
3. Trims from 44 → 20 messages (removes 24)
4. Both security events survive — they were pinned through the trim

**Talking points:**
- **Why this matters:** Without this, an attacker could send a prompt injection, get blocked, then keep chatting until context trimming erases the evidence. They retry the same attack and the agent has no memory of the previous block.
- **How it works:** Every security event is tagged with `_security_event` metadata at the enforcement point (not pattern matching). The trimmer classifies every message, pins CRITICAL ones, and only trims NORMAL messages.
- **Pair atomicity:** Tool_use + tool_result pairs are always kept or removed together — no orphaned messages that break the API contract.
- **Summarization fallback:** If there are too many pinned events (>6 pairs), the oldest are compressed into a redacted summary. Only event types are kept — attacker-controlled content is never re-injected through the summary.
- **Belt and suspenders:** Structured metadata is preferred, but pattern matching is a fallback for messages that describe security events (e.g., "your request was flagged by our security system").

**Key code:**
- Tagging at enforcement: `SECURITY_EVENT_KEY` tagging in `Agent._call_mcp_tool_with_reconnect()`
- Classification: `classify_message()` in `security/context_trimming.py`
- 8-phase trim algorithm: `trim_with_security_awareness()` in `security/context_trimming.py`
- Redacted summary builder: `_build_security_summary()` in `security/context_trimming.py`
