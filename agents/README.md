# Agents

This directory contains all agent implementations. Each agent extends the `Agent` class from `agent-framework` and has access to shared MCP tools. Agents are registered in `shared/registry.py` and run via `bin/run-agent`.

## Security-Focused Agents

### Chatbot (`chatbot/`)
General-purpose AI assistant with access to all 53 MCP tools. Serves as the baseline "full access" agent — contrast with restricted agents below to see capability bounding in action.

**Run:** `uv run bin/run-agent chatbot` | **[Documentation](chatbot/README.md)**

---

### Security Researcher (`security_researcher/`)
AI/ML security expert with RAG-backed knowledge base. **READ-only permissions** — demonstrating least-privilege access control.

**Run:** `uv run bin/run-agent security` | **[Documentation](security_researcher/README.md)**

---

### Red Team (`red_team/`)
Authorized penetration testing agent for security assessments.

**Run:** `uv run bin/run-agent red-team` | **[Documentation](red_team/README.md)**

---

### Security Audit (`security_audit/`)
Reads structured JSON reports from the non-LLM security audit collector. Provides prioritized findings and remediation steps.

**Run:** `uv run bin/run-agent security-audit` | **[Documentation](security_audit/README.md)**

---

### System Admin (`system_admin/`)
Network and system security assessment with host discovery, port scanning, TLS inspection, SSH config auditing, and default credential detection.

**Run:** `uv run bin/run-agent sysadmin` | **[Documentation](system_admin/README.md)**

---

## Infrastructure Agents

### Task Manager (`task_manager/`)
Task management via remote MCP server. Central to the **memory isolation** architecture — each agent's memory is namespaced to prevent cross-contamination.

**Run:** `uv run bin/run-agent tasks` | **[Documentation](task_manager/README.md)**

---

### Log Analysis (`log_analysis/`)
Log investigation agent that automatically **pins security-critical findings** (errors, exceptions, security events) so they survive context trimming during long investigations.

**Run:** `uv run bin/run-agent log-analysis` | **[Documentation](log_analysis/README.md)**

---

### Email Intake (`email_intake/`)
Email inbox monitor handling **untrusted input** — runs with the strictest prompt injection detection thresholds.

**Run:** `uv run python -m agents.email_intake.main` | **[Documentation](email_intake/README.md)**

---

### Code Analysis (`code_analysis/`)
Repository security and quality review agent.

**Run:** `uv run bin/run-agent code-analysis` | **[Documentation](code_analysis/README.md)**

---

### Web Analysis (`web_analysis/`)
Website auditing with headless Chromium. Demonstrates **tool allowlists** — only granted web and task tools.

**Run:** `uv run bin/run-agent web-analysis` | **[Documentation](web_analysis/README.md)**

---

### Website Tester (`website_tester/`)
Automated website testing with Playwright for accessibility, performance, and broken link detection.

**Run:** `uv run bin/run-agent website-tester` | **[Documentation](website_tester/README.md)**

---

### Orchestrator (`orchestrator/`)
Task decomposition and multi-agent delegation. Relevant to the **delegation chain** security problem — A→B→C permission escalation risks.

**Run:** `uv run python -m agents.orchestrator.main` | **[Documentation](orchestrator/README.md)**

---

## Architecture

All agents share:

- **agent-framework** (`packages/agent-framework/`) — Base Agent class, MCP client, security utilities (SSRF protection, filesystem validation), permission system
- **MCP Tools** (`packages/agent-framework/agent_framework/tools/`) — 53 tools across web, memory, RAG, email, HTTP, filesystem, browser, and network categories
- **Registry** (`shared/registry.py`) — Central agent registration with per-agent tool allowlists and MCP configuration

See [CLAUDE.md](../CLAUDE.md#adding-new-agents) for instructions on adding new agents.
