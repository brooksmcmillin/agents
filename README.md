# Building Secure Agentic Systems

[![CI](https://github.com/brooksmcmillin/agents/workflows/CI/badge.svg)](https://github.com/brooksmcmillin/agents/actions/workflows/ci.yml)
[![Security](https://github.com/brooksmcmillin/agents/workflows/Security/badge.svg)](https://github.com/brooksmcmillin/agents/actions/workflows/security.yml)

A production multi-agent system built with Claude and Model Context Protocol (MCP), focused on the security architecture required to run LLM agents as daily drivers. Companion code for the [un]prompted talk *"Building Secure Agentic Systems: Lessons from Daily-Driver Agents."*

## The Problem

Running autonomous LLM agents in production means dealing with untrusted inputs, shared state, unbounded tool access, and context window limits — all of which create attack surface. This project implements layered defenses for each.

## Architecture

```
User Input (CLI / API)
    → Agent (agents/*/main.py)
        → Claude API (Sonnet 4.6)
            → MCP Client (agent-framework)
                → MCP Server (stdio transport)
                    → Tools (53 implementations)
```

**10 registered agents + 2 standalone services. 53 tools. 6 permission levels. 10 max iterations per turn.**

Each agent gets a scoped set of tools and permissions — not blanket access. Unknown tools default to `ADMIN` (deny by default).

## Defense Layers

### 1. Capability Bounding + Permission Control

If you can't enumerate what an agent *can* do, you can't reason about what it *shouldn't* do.

| Agent | Allowed Tools | Permissions |
|-------|--------------|-------------|
| Task Manager | web, memory, email | READ, WRITE, SEND |
| Security Researcher | web, memory, RAG search | READ only |
| Email Intake | email read, email send | READ, SEND |
| Chatbot | all 53 tools | Full (general purpose) |

```python
# Fail-safe: unknown tools → ADMIN → deny by default
def get_required_permissions(tool):
    return TOOL_MAP.get(tool, {ADMIN})
```

New tools are locked down by default. You opt *in* to access, not out. See [`packages/agent-framework/agent_framework/permissions/`](packages/agent-framework/agent_framework/permissions/) for the implementation.

### 2. Memory Isolation

All agents share the same PostgreSQL memory backend. Without namespacing, one agent's memories leak into another's responses — and worse, an attacker who controls untrusted input (e.g., email) can poison shared memory to influence all agents.

**The fix:** `agent_name` is auto-injected by the MCP server into every memory tool call. Queries are always filtered by namespace.

```
BEFORE                          AFTER
┌──────────┐                    ┌──────────┐
│ memories │ ← all agents       │ns:tasks  │ ← Task Manager
│ key|value│   write here       │ns:security│ ← Security Researcher
│ (no isolation)                │ns:email  │ ← Email Intake
└──────────┘                    └──────────┘
```

See [`packages/agent-framework/agent_framework/storage/`](packages/agent-framework/agent_framework/storage/) for the namespaced memory implementation.

### 3. Prompt Injection Detection

Out-of-box AI firewall configuration was too aggressive — legitimate queries got blocked:

- *"Clear your context and focus on xyz"* → BLOCKED (legitimate task instruction)
- *"What are the top prompt injection techniques?"* → BLOCKED (security research query)

**Solution:** Per-agent threshold configuration. Security researcher gets relaxed thresholds for injection-related queries. Email intake (untrusted input) gets strictest settings. If the firewall API is down, log a warning and continue — availability over perfect security.

### 4. Context-Aware Trimming

When the context window fills up, which messages get dropped? Without care, an attacker waits for trimming, then retries the same attack — and the agent has no memory of the previous attempt.

**What gets pinned (survives trimming):** Permission denials, SSRF blocks, prompt injection flags, system security warnings.

See [`packages/agent-framework/agent_framework/core/`](packages/agent-framework/agent_framework/core/) for the trimming implementation.

### 5. SSRF Protection

Agents that fetch URLs need protection against server-side request forgery. All HTTP tools validate targets against private IP ranges and dangerous redirects.

See [`packages/agent-framework/agent_framework/security/`](packages/agent-framework/agent_framework/security/) for the SSRF protection implementation.

## Observability

Every decision point is observable and costed.

- **Langfuse traces** — Per-turn traces with tool call spans, token counts, latency
- **Grafana dashboards** — Per-agent cost, daily breakdown, budget alerts, most expensive tools
- **Security audit trail** — Permission denials and SSRF blocks logged with full context + agent ID

In week one of cost tracking, found **10x token waste**: system prompt was injecting ALL memories on every turn, including low-importance ones. Fix: filter by importance >= 7. Result: 80% token reduction.

## Agents

| Agent | Description | Key Security Feature |
|-------|------------|---------------------|
| **Chatbot** | General-purpose assistant | Full tool access (baseline) |
| **Security Researcher** | AI/ML security research with RAG | READ-only permissions |
| **Email Intake** | Inbox monitor for untrusted input | Strictest injection detection |
| **Task Manager** | Task management via remote MCP | Memory isolation demo |
| **Log Analysis** | Log investigation | Context-aware pinning |
| **Red Team** | Authorized penetration testing | Scoped HTTP tools |
| **Security Audit** | Audit report analysis | Read-only structured input |
| **System Admin** | Network security assessment | Scoped network tools |
| **Code Analysis** | Repository security review | Scoped filesystem tools |
| **Web Analysis** | Website auditing | Tool allowlist + task creation |
| **Website Tester** | Automated Playwright testing | Browser sandbox |
| **Orchestrator** | Multi-agent delegation | Delegation chain permissions |

## Quick Start

```bash
# Install
uv sync
cp .env.example .env  # Add ANTHROPIC_API_KEY

# Run an agent
uv run bin/run-agent chatbot          # Full-access general assistant
uv run bin/run-agent security         # READ-only security researcher
uv run bin/run-agent tasks            # Task management with memory isolation

# REST API
uv run python -m api                  # localhost:8080

# One-shot mode
uv run bin/run-agent chatbot "What tools do you have access to?"
```

## Project Structure

```
agents/                    # Agent implementations
├── chatbot/               # General-purpose (full access)
├── security_researcher/   # READ-only security research
├── email_intake/          # Untrusted input handling
├── task_manager/          # Memory isolation demo
├── log_analysis/          # Context-aware trimming
├── red_team/              # Scoped penetration testing
├── security_audit/        # Audit report analysis
├── system_admin/          # Network security assessment
├── code_analysis/         # Repository review
├── web_analysis/          # Website auditing
├── website_tester/        # Playwright browser testing
└── orchestrator/          # Multi-agent delegation
packages/
└── agent-framework/       # Core library
    └── agent_framework/
        ├── core/          # Base Agent, MCP client, context trimming
        ├── tools/         # 53 MCP tool implementations
        ├── security/      # SSRF protection, filesystem validation
        ├── permissions/   # 6-level permission system
        ├── storage/       # Namespaced memory backend
        ├── observability/ # Langfuse integration
        └── telemetry/     # Token usage tracking
api/                       # FastAPI REST server
mcp_server/                # MCP server + OAuth infrastructure
shared/                    # Registry, delegation, agent factory
bin/                       # CLI entry points
docs/                      # Security guides, tool reference, deployment
tests/                     # Unit + integration + evaluation tests
```

## Key Implementation Files

| Concept | File |
|---------|------|
| Permission system | `packages/agent-framework/agent_framework/permissions/` |
| SSRF protection | `packages/agent-framework/agent_framework/security/ssrf_protection.py` |
| Memory namespacing | `packages/agent-framework/agent_framework/storage/` |
| Context trimming | `packages/agent-framework/agent_framework/core/agent.py` |
| Tool allowlists | `agents/*/main.py` (per-agent `allowed_tools`) |
| Agent registry | `shared/registry.py` |
| MCP tool definitions | `packages/agent-framework/agent_framework/tools/` |

## Lessons Learned

**What worked:**
- Permission system + tool allowlists early on
- MCP separation creates natural trust boundaries
- Fail-safe defaults: unknown → ADMIN → deny
- Context-aware trimming for security event persistence
- Cost dashboard: found 10x waste in week one

**What I'd do differently:**
- Namespace agent memory from day one
- Tune prompt injection detection before deploying
- Cost tracking from the start, not after surprise bill
- PII detection on outputs — added retroactively
- Design scoped delegation up front, not after bugs

**Still unsolved:**
- Multi-user support (user_id not propagated everywhere)
- Rate limiting per agent (budget caps exist, throttling doesn't)
- Delegation chains: A→B→C permission escalation risks

## Documentation

- [docs/SECURITY_UNTRUSTED_CONTENT.md](docs/SECURITY_UNTRUSTED_CONTENT.md) — Security hardening for untrusted content
- [docs/tools.md](docs/tools.md) — Complete MCP tools reference (53 tools)
- [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) — Live demo script (memory isolation, SSRF, trimming)
- [docs/CLI.md](docs/CLI.md) — CLI reference for `bin/run-agent`
- [docs/observability.md](docs/observability.md) — Langfuse tracing and Grafana dashboards
- [docs/TESTING.md](docs/TESTING.md) — Testing and debugging guide
- [docs/docker.md](docs/docker.md) — Docker deployment

## Technology

Python 3.12+ · Claude Sonnet 4.6 · Model Context Protocol · FastAPI · Langfuse · PostgreSQL · Playwright

---

*Presented at [un]prompted: The AI Practitioner Conference*
