# Demo Cheat Sheet

Quick reference for explaining what the demo script does, and for running
pieces manually if someone asks "how does that work?"

## Running the Demo

```bash
uv run python scripts/demo_live.py               # All 4 steps, interactive (Enter to advance)
uv run python scripts/demo_live.py memory         # Step 1 only
uv run python scripts/demo_live.py ssrf           # Step 2 only
uv run python scripts/demo_live.py permissions    # Step 3 only
uv run python scripts/demo_live.py trimming       # Step 4 only
uv run python scripts/demo_live.py --no-pause     # Unattended (CI, recording)
```

---

## Step 1: Memory Namespace Isolation

**Point:** Each agent has its own memory namespace. Agent A can't read Agent B's memories.

### What it does
1. Seeds a memory (`demo-status`) into the `ChatbotAgent` namespace via `test_memory.py`
2. Chatbot agent searches for "rocket" — finds it in its own namespace
3. Security agent searches for "rocket" — finds nothing (different namespace)

### Manual commands
```bash
# Seed a memory into ChatbotAgent's namespace
uv run python scripts/testing/test_memory.py save demo-status \
  "launching rocket to Mars next quarter" --agent ChatbotAgent

# Chatbot sees it
uv run python bin/run-agent chatbot -q "Search your memories for 'rocket'"

# Security agent does not
uv run python bin/run-agent security -q "Search your memories for 'rocket'"

# Cleanup
uv run python scripts/testing/test_memory.py delete demo-status --agent ChatbotAgent
```

### Why it matters
- Prevents cross-agent data leakage in multi-agent systems
- An email-triggered agent can't read the chatbot's memories
- Namespace is enforced at the storage layer, not just by convention

---

## Step 2: SSRF Protection

**Point:** The SSRF validator blocks requests to private/internal IPs, even when hidden behind DNS.

### What it does
1. Asks the chatbot to fetch `http://app.127.0.0.1.sslip.io:8080/api/config` — the URL
   looks like a normal domain, but `sslip.io` resolves it to `127.0.0.1`. The SSRF
   validator performs DNS resolution and blocks the request.
2. Asks the chatbot to fetch `https://example.com` — legitimate URL, succeeds.

### Manual commands
```bash
# Blocked: sslip.io resolves to 127.0.0.1
uv run python bin/run-agent chatbot -q \
  "Use fetch_web_content to get http://app.127.0.0.1.sslip.io:8080/api/config"

# Allowed: legitimate public URL
uv run python bin/run-agent chatbot -q \
  "Fetch https://example.com and tell me the page title."
```

### Why it matters
- Blocks SSRF attacks that hide private IPs behind DNS (DNS rebinding)
- Validates at the tool layer — the LLM doesn't need to understand the risk
- Covers private IPs, link-local/metadata, localhost, and non-HTTP schemes

---

## Step 3: Permission Denial

**Point:** Agents can be given restricted permission sets that limit which tools they can use.

### What it does
1. Runs chatbot with `--permissions READ,SEND` and asks it to save a memory —
   `save_memory` requires `WRITE`, so the tool call is denied
2. Runs chatbot with default (full) permissions — same request succeeds

### Manual commands
```bash
# Denied: READ+SEND doesn't include WRITE
uv run python bin/run-agent chatbot -q --permissions READ,SEND \
  "Remember this: test-key is 'test-value'."

# Allowed: default permissions include WRITE
uv run python bin/run-agent chatbot -q \
  "Remember this: demo-perm-test is 'permission test passed'."
```

### Why it matters
- Enforces least-privilege per agent (email agents can't write, etc.)
- Permission intersection on delegation prevents privilege escalation
- Blocked tool calls are tagged as security events for context trimming

---

## Step 4: Security Events Survive Context Trimming

**Point:** When conversation history is trimmed to fit context windows, security-relevant
messages (SSRF blocks, permission denials) are pinned and never dropped.

### What it does
1. Builds a synthetic 44-message conversation
2. Injects 2 security events (SSRF block at msg ~22, permission denial at msg ~34)
3. Classifies each message as NORMAL or CRITICAL
4. Trims to 20 messages — security events are pinned
5. Verifies both security events survived

### Key code
```python
from agent_framework.security.context_trimming import (
    classify_message, trim_with_security_awareness,
    SecurityClassification, SECURITY_EVENT_KEY,
)

# Messages tagged with SECURITY_EVENT_KEY are classified as CRITICAL
msg = {"role": "user", "content": [{"type": "tool_result", ..., SECURITY_EVENT_KEY: "ssrf_block"}]}
classify_message(msg).classification  # SecurityClassification.CRITICAL

# Trimming preserves CRITICAL messages
trimmed, removed, pinned = trim_with_security_awareness(messages, max_messages=20)
# pinned >= 2, security events still present
```

### Why it matters
- Long-running agents eventually trim old messages to fit the context window
- If a security event (e.g., "don't fetch metadata endpoints") gets trimmed,
  the agent might retry the same blocked action
- Pinning ensures the agent always remembers what was blocked and why
