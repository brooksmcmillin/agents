# Agents

This directory contains all agent implementations. Each agent is a standalone application that extends the `Agent` class from `agent-framework` and has access to shared MCP tools.

## Available Agents

### Chatbot (`chatbot/`)
General-purpose AI assistant with access to all 29 MCP tools including web analysis, memory, RAG document search, email management, and communication.

**Use for**: General assistance, multi-domain tasks, research, content analysis, email workflows

**Run:** `uv run python -m agents.chatbot.main` | **[Documentation](chatbot/README.md)**

---

### PR Agent (`pr_agent/`)
PR and content strategy assistant specialized in content creation, social media strategy, and brand voice.

**Use for**: Blog post analysis, social media content, SEO recommendations, content calendars

**Run:** `uv run python -m agents.pr_agent.main` | **[Documentation](pr_agent/README.md)**

---

### Security Researcher (`security_researcher/`)
AI/ML security expert with RAG-backed knowledge base for security research papers and vulnerability analysis.

**Use for**: Security research questions, blog post fact-checking, threat modeling, security reviews

**Requirements**: PostgreSQL + OpenAI API for RAG functionality

**Run:** `uv run python -m agents.security_researcher.main` | **[Documentation](security_researcher/README.md)**

---

### Business Advisor (`business_advisor/`)
Business strategy and monetization advisor that analyzes repositories and websites to identify income opportunities.

**Use for**: Monetization ideas, business plans, market analysis, competitive research

**Optional**: GitHub MCP integration for repository analysis

**Run:** `uv run python -m agents.business_advisor.main` | **[Documentation](business_advisor/README.md)**

---

### Task Manager (`task_manager/`)
Interactive task management assistant that connects to remote MCP server for task operations.

**Use for**: Rescheduling overdue tasks, pre-researching upcoming tasks, task prioritization

**Requirements**: Remote MCP server with task management tools

**Run:** `uv run python -m agents.task_manager.main` | **[Documentation](task_manager/README.md)**

---

### REST API Server (`api/`)
HTTP/REST interface providing stateless and stateful access to agents via API endpoints.

**Use for**: Integrating agents into web applications, mobile apps, or other services via HTTP

**Features**: Stateless requests, stateful sessions, multi-agent support, token tracking

**Run:** `uv run python -m agents.api` | **[Documentation](api/README.md)**

---

### Task Notifier (`notifier/`)
Lightweight notification script (not a full interactive agent) that sends Slack messages about open tasks.

**Use for**: Automated task notifications, cron-based reminders, Slack integrations

**Requirements**: Remote MCP server, Slack webhook

**Run:** `uv run python -m agents.notifier.main` | **[Documentation](notifier/README.md)**

---

## Shared Resources

All agents have access to:

- **MCP Server** (`../config/mcp_server/`) - 29 shared tools across 8 categories
  - Web analysis (2 tools)
  - Memory (6 tools)
  - RAG document search (6 tools)
  - FastMail email (8 tools)
  - Communication (1 tool)
  - Social media (1 tool)
  - Content suggestions (1 tool)

- **agent-framework** (`../packages/agent-framework/`) - Shared library with:
  - Base Agent class
  - MCP client implementations (local stdio and remote HTTP/SSE)
  - Security utilities (SSRF protection)
  - All MCP tools

- **Shared utilities** (`../shared/`) - Common code reusable across agents
  - Logging setup
  - Configuration helpers
  - Prompt templates

## Adding New Agents

See the main [CLAUDE.md](../CLAUDE.md#adding-new-agents) for step-by-step instructions on creating new agents.

Quick summary:
1. Create agent directory: `mkdir -p agents/your_agent`
2. Create `main.py` extending `Agent` class
3. Create `prompts.py` with system prompt and greeting
4. Create `__init__.py` and `README.md`
5. Run: `uv run python -m agents.your_agent.main`

All agents automatically have access to the shared MCP tools.

## Documentation

Each agent directory contains:
- `README.md` - Comprehensive agent documentation
- `main.py` - Agent implementation
- `prompts.py` - System prompts and behavior configuration
- `__init__.py` - Package metadata

For framework documentation, see:
- [../CLAUDE.md](../CLAUDE.md) - Project overview and development guide
- [../packages/agent-framework/](../packages/agent-framework/) - Framework documentation
- [../GUIDES.md](../GUIDES.md) - Feature guides (memory, OAuth, deployment)
- [../HOT_RELOAD.md](../HOT_RELOAD.md) - Development workflow
- [../REMOTE_MCP.md](../REMOTE_MCP.md) - Remote MCP setup
