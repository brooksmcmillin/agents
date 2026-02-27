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
1. Saves a memory under `DemoAgent-Alpha` ("launching rocket to Mars")
2. Saves a memory with the *same key* under `DemoAgent-Beta` ("building underwater data center")
3. Searches from each namespace — each agent only sees its own memory
4. Searches Alpha's namespace for Beta's content — returns nothing

### Key code
```python
from agent_framework.tools.memory import save_memory, search_memories

# agent_name acts as the namespace key
await save_memory(key="status", value="secret", agent_name="AgentA")
result = await search_memories(query="secret", agent_name="AgentB")
# result["memories"] == []  (isolated)
```

### Why it matters
- Prevents cross-agent data leakage in multi-agent systems
- An email-triggered agent can't read the chatbot's memories
- Namespace is enforced at the storage layer, not just by convention

---

## Step 2: SSRF + Permission Denial

**Point:** Defense in depth — multiple independent layers block unauthorized actions.

### Layer 1: SSRF URL validation
Validates URLs before any HTTP request is made.

```python
from agent_framework.security.ssrf import SSRFValidator

SSRFValidator.is_safe_url("https://example.com")           # (True, None)
SSRFValidator.is_safe_url("http://169.254.169.254/meta")    # (False, "Cloud metadata...")
SSRFValidator.is_safe_url("http://192.168.1.1/admin")       # (False, "Private network...")
SSRFValidator.is_safe_url("file:///etc/passwd")             # (False, "Disallowed scheme...")
```

Blocked categories: private IPs, link-local/metadata, localhost, non-HTTP schemes.

### Layer 2: Tool permission enforcement
Each tool declares required permissions. Agents are granted a permission set at creation.

```python
from agent_framework.permissions.tool_permissions import get_required_permissions, check_tool_permission
from agent_framework.permissions.permissions import Permission

get_required_permissions("send_email")    # {Permission.SEND}
get_required_permissions("save_memory")   # {Permission.WRITE}
get_required_permissions("run_claude_code")  # {Permission.EXECUTE}

# Email agent only has READ + SEND
email_perms = {Permission.READ, Permission.SEND}
check_tool_permission("fetch_web_content", email_perms)  # (True, set())
check_tool_permission("save_memory", email_perms)        # (False, {WRITE})
check_tool_permission("run_claude_code", email_perms)    # (False, {EXECUTE})
```

### Layer 3: Permission intersection on delegation
When Agent A delegates to Agent B, B gets the *intersection* of both permission sets.
A low-privilege caller can never escalate by delegating to a high-privilege agent.

```python
from agent_framework.permissions.context import ExecutionContext
from agent_framework.permissions.identity import AgentIdentity
from agent_framework.permissions.permissions import PermissionSet, Permission

# Email intake (READ + SEND) delegates to code reviewer (full access)
ctx = ExecutionContext(
    caller=AgentIdentity(name="EmailIntake", source="email"),
    permissions=PermissionSet([Permission.READ, Permission.SEND]),
)
delegated = ctx.delegate_to("CodeReviewer", agent_permissions=PermissionSet.full_access())
# delegated.permissions == {READ, SEND}  (not full access!)
delegated.can(Permission.EXECUTE)  # False
```

---

## Step 3: Security Events Survive Context Trimming

**Point:** When conversation history is trimmed to fit context windows, security-relevant
messages (SSRF blocks, permission denials) are pinned and never dropped.

### What it does
1. Builds a synthetic 44-message conversation
2. Injects 2 security events (SSRF block at msg ~22, permission denial at msg ~32)
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
