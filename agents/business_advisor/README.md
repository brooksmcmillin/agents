# Business Advisor Agent

A strategic business advisor powered by Claude Sonnet 4.5, specialized in technology entrepreneurship, software monetization, and consulting business models. Analyzes your existing work, skills, and assets to identify income opportunities with realistic assessments of effort, risk, and potential.

## Features

### 🎯 Opportunity Discovery
- Analyze GitHub repositories to understand your technical skills
- Review websites, portfolios, and blogs for positioning insights
- Identify monetizable projects and expertise
- Map skills to market opportunities

### 💼 Business Idea Generation
- Generate 3-5 ideas ranging from low to high effort/reward
- Honest assessments of risk and competitive landscape
- Multiple revenue models: SaaS, consulting, licensing, education
- Tailored to your specific skills and constraints

### 📊 Comprehensive Business Plans
- Executive summaries for quick evaluation
- Full plans with market analysis, competitive landscape
- Go-to-market strategies and pricing models
- Resource requirements and timeline estimates
- Risk assessment and mitigation strategies

### ✅ Validation-First Approach
- Recommend customer discovery before building
- Suggest low-effort validation methods
- Test ideas before major time/money investment
- Focus on learning over premature execution

### 🛡️ Content Guardrails
- **No unvalidated claims**: Never fabricates metrics or ROI without your data
- **No fictional social proof**: Won't invent past clients or fake testimonials
- **Legal disclaimers**: Flags contracts, SOWs, and legal terms for attorney review
- **Realistic timelines**: Factors in first-time delivery overhead and buffers
- **Honest framing**: Transparent about uncertainty and effort required

### 🧠 Persistent Memory
- Remembers your skills, projects, and goals across conversations
- Tracks business ideas you've explored
- Maintains context about your constraints and preferences

## Quick Start

### Prerequisites

1. **Python 3.11 or higher**

2. **Anthropic API Key**: Required for Claude
   ```bash
   ANTHROPIC_API_KEY=your_key_here
   ```

3. **Optional**: GitHub MCP server for repository analysis
   ```bash
   GITHUB_MCP_SERVER=stdio://path/to/github-mcp
   ```

### Installation

```bash
# Install dependencies
uv sync
```

### Configuration

Copy `.env.example` to `.env` and configure:

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-...

# Optional - GitHub Analysis
GITHUB_MCP_SERVER=stdio://path/to/github-mcp  # or HTTP URL

# Optional - Memory Backend
MEMORY_BACKEND=file  # or "database"
MEMORY_DATABASE_URL=postgresql://user:pass@localhost:5432/agent_memory

# Optional - Slack Notifications
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...

# Optional - Logging
LOG_LEVEL=INFO  # DEBUG, INFO, WARNING, ERROR
```

### Running

```bash
# Start the business advisor agent
uv run python -m agents.business_advisor.main

# With GitHub MCP server
GITHUB_MCP_SERVER=stdio://path/to/github-mcp uv run python -m agents.business_advisor.main
```

## MCP Tools

The business advisor has access to **8 tools**:

### Web Analysis (1 tool)
- **fetch_web_content**: Fetch and read web content as clean markdown
  - Read user's website, blog, or portfolio
  - Research competitor websites and market trends
  - Gather information from industry resources
  - Parameters: `url` (string), `max_length` (optional)

### Memory (6 tools)
- **save_memory**: Save business context, ideas, and user information
  - Parameters: `key`, `value`, `category` (optional), `tags` (optional), `importance` (1-10)
  - Use for: Tracking skills, project details, business ideas, goals

- **get_memories**: Retrieve saved memories with filtering
  - Parameters: `category` (optional), `tags` (optional), `min_importance` (optional)

- **search_memories**: Search memories by keyword
  - Parameters: `query` (string)

- **delete_memory**: Delete a memory by key
  - Parameters: `key` (string)

- **get_memory_stats**: Get memory system statistics
  - Returns: Total memories, categories, average importance

- **configure_memory_store**: Configure memory backend
  - Parameters: `backend` (file|database), `database_url` (optional)

### Communication (1 tool)
- **send_slack_message**: Send notifications and updates
  - Parameters: `channel`, `text`, `username` (optional), `icon_emoji` (optional)

### GitHub Tools (optional, if GitHub MCP configured)
When GitHub MCP server is connected, can analyze:
- Repository technologies and languages
- Project complexity and quality indicators
- Community traction (stars, forks, issues)
- Development patterns and expertise areas

Note: If GitHub analysis fails, agent proceeds with other available information.

## Usage Examples

### Example 1: Initial Discovery Session

```
You: I want to start making money with my coding skills. My GitHub is github.com/user

Agent: I'll analyze your GitHub repositories and help identify monetization opportunities.

[If GitHub MCP is available, calls GitHub tools]
[Calls fetch_web_content if you have a website/blog]
[Saves discovered skills and projects to memory]

Based on your work, I see you have:
- **Strong expertise in**: Python, FastAPI, PostgreSQL, React
- **Notable projects**:
  - Task management API (150 stars) - shows API design skills
  - Developer tools library (50 stars) - demonstrates tooling expertise
  - Personal blog with technical content - establishes thought leadership

Let me generate some business ideas tailored to your skills...

### Idea 1: Developer Tools Consulting

**Value Proposition**: Help startups build internal developer tools and automation.

**Target Market**: Series A-B startups with 10-50 engineers needing better tooling.

**Revenue Model**: Project-based consulting at $150-200/hr, 2-3 week engagements.

**Effort Level**: Medium - Requires client acquisition but leverages existing expertise.

**Risk Level**: Low - Clear market need, skills you already have.

**Competitive Advantage**: Your open-source tool library demonstrates capability.

**Quick Validation**: Talk to 5-10 engineering managers about their tooling pain points.

### Idea 2: SaaS Task Management for Niche
[Additional ideas...]

[Saves business ideas to memory]

Which idea interests you most? I can expand any of these into a full business plan.
```

### Example 2: Expanding Into Full Business Plan

```
You: Tell me more about the consulting idea

Agent: I'll develop a comprehensive business plan for developer tools consulting.
[Retrieves context from memory]

## Developer Tools Consulting - Business Plan

### Executive Summary
You'll offer specialized consulting to help startups build internal developer tools,
automation pipelines, and engineering infrastructure. Target market is Series A-B
companies (10-50 engineers) who need better tooling but lack dedicated platform teams.

Revenue model: Project-based consulting at $150-200/hr with typical engagements of
80-120 hours over 2-3 weeks. Target: 2-3 projects per quarter = $24k-72k quarterly.

⚠️ Note: Revenue estimates are hypothetical. Actual results depend on your client
acquisition effectiveness and market conditions.

### Problem & Solution
**Problem**: Growing startups hit inefficiencies around 20-30 engineers. Manual
processes, poor CI/CD, missing observability, slow deployments. They know they need
better tooling but can't justify a full-time platform hire yet.

**Solution**: You come in for focused 2-3 week engagements to build specific tools:
CI/CD pipelines, deployment automation, monitoring dashboards, developer CLIs, etc.

### Target Market
**Primary Audience**: Engineering managers and CTOs at Series A-B startups

**Market Size**: ~5,000 Series A-B companies in US, many with these pain points

**Acquisition Channels**:
- Direct outreach to engineering leaders on LinkedIn
- Content marketing (blog posts about tooling challenges)
- Referrals from first few clients
- Developer communities (Slack groups, forums)

### Competitive Analysis
**Direct Competitors**:
- Large consulting firms (expensive, slow)
- Full-time platform engineer hires (expensive, long commitment)
- Freelance generalists (may lack specific tooling expertise)

**Differentiation**:
- More affordable than agencies, faster than hiring
- Specialized expertise shown through your open-source tools
- Fixed-scope projects reduce uncertainty for clients

### Product/Service Definition
**Core Offering**: 2-3 week tool-building engagements

**Deliverables**:
- Custom developer tools/scripts
- CI/CD pipeline setup
- Documentation and knowledge transfer
- 30 days of post-delivery support

**MVP Scope**: Start with CI/CD and deployment automation (highest demand)

**Future**: Expand to monitoring, testing infrastructure, dev environments

### Go-to-Market Strategy
**Phase 1 - Validation (Weeks 1-4)**:
- Conduct 10 customer discovery calls with target personas
- Validate pricing and service packaging
- Get 2-3 pilot clients (possibly discounted for testimonials)

**Phase 2 - Launch (Weeks 5-12)**:
- Create simple landing page with positioning
- Write 3-4 blog posts on tooling challenges
- Direct outreach: 20 prospects per week on LinkedIn
- Goal: 2 paying projects

**Phase 3 - Scale (Months 4-6)**:
- Build referral system
- Expand content marketing
- Raise rates based on demand
- Goal: Booked 2 months in advance

### Pricing & Revenue
**Pricing Model**: $150-200/hr depending on project complexity

**Typical Project**: 80-120 hours over 2-3 weeks = $12k-24k

**Projected Bookings**:
- Month 1-2: 1 pilot project (validation)
- Month 3-4: 2 projects = $24k-48k
- Month 5-6: 2-3 projects = $36k-72k

⚠️ Note: These projections are hypothetical estimates for planning purposes. Actual
revenue depends on your client acquisition success, market conditions, and execution.

### Resource Requirements
**Time**:
- Client acquisition: 5-10 hours/week initially
- Project delivery: 20-30 hours/week per active project
- Admin/overhead: 5 hours/week

**Total**: 30-45 hours/week - this is a substantial time commitment

**Money**:
- Website/hosting: $20/month
- Email/CRM tools: $50/month
- Insurance (if needed): $100/month
- Total startup costs: ~$500

**Tools**:
- Your existing development setup
- Video conferencing (Zoom free tier)
- Basic CRM (HubSpot free or Airtable)

### Timeline & Milestones
**Month 1**: Validation
- Complete 10 customer discovery calls
- Refine positioning based on feedback
- Create basic website/portfolio

**Month 2**: First Pilot
- Acquire 1-2 pilot clients
- Deliver first projects
- Document processes
- Get testimonials

**Month 3-4**: Scaling
- Ramp up outreach
- Target 2 projects per month
- Build referral system
- Publish content

⚠️ Note: First client projects typically take 50% longer than estimated due to
process development and unexpected issues. Build buffer time into early commitments.

### Risks & Mitigation
**Risk 1: Client acquisition takes longer than expected**
- Mitigation: Start outreach before quitting other work, build pipeline early
- Fallback: Keep current job while doing 1-2 pilots on weekends

**Risk 2: Projects take longer than estimated**
- Mitigation: Fixed-price with clear scope, buffer time in estimates
- Fallback: Hourly billing for first few projects to learn actual timelines

**Risk 3: Market doesn't value service at target price**
- Mitigation: Customer discovery first, test pricing with pilots
- Fallback: Adjust positioning or target market based on feedback

**Risk 4: Full-time job conflicts (if applicable)**
- Mitigation: Check employment agreement for moonlighting clauses, IP assignment
- Action: Verify company policies before starting client work

### Next Steps

**Do This First (Validation - don't build anything yet)**:
1. Create list of 20 target companies (Series A-B with 10-50 engineers)
2. Write outreach message: "Building tooling for startups, doing research calls"
3. Schedule 10 customer discovery calls over next 2 weeks
4. In calls, ask:
   - What tooling pain points do you have?
   - How are you currently solving them?
   - What would you pay someone to fix this?
   - How do you currently hire for this type of work?

**Only After Validation**:
5. If validation confirms demand, create simple landing page
6. Document your service offering based on real feedback
7. Set pricing based on what market told you
8. Do 1-2 pilot projects (can be discounted for testimonials)

**Don't Do Yet**:
- ❌ Build elaborate website
- ❌ Create extensive marketing materials
- ❌ Quit your job (if applicable)
- ❌ Make business cards or branding

---
⚠️ LEGAL REVIEW REQUIRED: Before signing any client contracts or SOWs, have them
reviewed by an attorney. The sample agreements and IP clauses I can provide are
templates only, not legal advice.

[Saves expanded plan to memory]

What questions do you have, or would you like me to refine any section?
```

### Example 3: Returning User Continuity

```
You: I'm back! What should I work on?

Agent: Welcome back! Let me recall what we discussed.
[Retrieves all memories about user]

Last time we explored developer tools consulting for Series A-B startups. You were
interested in the $150-200/hr project-based model with 2-3 week engagements.

We outlined:
- Target market: Engineering managers at 10-50 person startups
- Core offering: CI/CD and deployment automation
- Next step: 10 customer discovery calls

Have you made progress on the customer discovery calls? What's changed since we
last talked?
```

### Example 4: Content Guardrails in Action

```
You: Can you write an outreach email where I mention past client results?

Agent: I can help you write an outreach email, but I need to make sure we frame it
honestly. Do you actually have past clients with measured results?

If not, I'll write the email with honest framing instead of fabricated social proof:

---
Subject: Building AI agents for [industry] - looking for founding clients

Hi [Name],

I'm a developer specializing in [your skills] and I'm building AI-powered tools for
[target industry]. I'm currently looking for 2-3 founding clients to work with closely.

I've built [mention your actual open-source projects or portfolio], and I'm now
offering these services:
- [Service 1]
- [Service 2]

As a founding client, you'd get:
- Heavily discounted rate ([your rate])
- Close collaboration on requirements
- Priority support during and after delivery

I'm specifically interested in companies facing [pain point]. Does this sound relevant
to your team?

[Your name]
---

⚠️ This framing is honest about where you are (building client base) rather than
fabricating past results. Many people respond well to "founding client" positioning.

Once you have real client results, we can update your messaging to include specific
outcomes with proper attribution.

Would you like me to refine this draft or adjust the positioning?
```

## Interactive Commands

- `exit`, `quit`, `q` - Exit the agent
- `stats` - Show token usage statistics
- `reload` - Reconnect to MCP server (refresh tools)

## Configuration

### Environment Variables

```bash
# Core Configuration (Required)
ANTHROPIC_API_KEY=sk-ant-...          # Anthropic API key

# GitHub Analysis (Optional)
GITHUB_MCP_SERVER=stdio://...         # GitHub MCP server path or URL

# Memory Configuration (Optional)
MEMORY_BACKEND=file                   # file (default) or database
MEMORY_DATABASE_URL=postgresql://...  # if using database

# Communication (Optional)
SLACK_WEBHOOK_URL=https://hooks...   # for notifications

# Logging
LOG_LEVEL=INFO                       # DEBUG, INFO, WARNING, ERROR
```

### GitHub MCP Integration

To enable GitHub repository analysis:

1. Install a GitHub MCP server (e.g., @modelcontextprotocol/server-github)
2. Configure it with your GitHub token
3. Set GITHUB_MCP_SERVER environment variable:
   ```bash
   # Stdio transport
   GITHUB_MCP_SERVER=stdio://node /path/to/github-mcp/dist/index.js

   # HTTP transport (if using remote MCP)
   GITHUB_MCP_SERVER=https://your-mcp-server.com/github
   ```

If GitHub MCP is not configured or fails, the agent will inform you and proceed with
web-based analysis and other available tools.

### Customization

Edit `agents/business_advisor/prompts.py` to customize:
- **SYSTEM_PROMPT**: Agent expertise and guardrails
- **USER_GREETING_PROMPT**: Initial greeting
- **GUARDRAILS_SECTION**: Content generation rules
- **BUSINESS_IDEA_TEMPLATE**: Structure for ideas
- **BUSINESS_PLAN_TEMPLATE**: Structure for full plans

## Troubleshooting

### GitHub MCP Not Working

```bash
# Check if environment variable is set
echo $GITHUB_MCP_SERVER

# Test GitHub MCP server directly
# (depends on your MCP server's test interface)

# Agent will report if GitHub connection fails and continue without it
# Look for log messages about GitHub MCP status
```

### Memory Issues

```bash
# Check memory backend configuration
echo $MEMORY_BACKEND

# View memory statistics in conversation
You: Can you show me memory statistics?

# For database backend, test connection
psql $MEMORY_DATABASE_URL -c "SELECT COUNT(*) FROM memories"
```

### API Key Issues

```bash
# Verify API key is set
echo $ANTHROPIC_API_KEY

# Check .env file
cat .env | grep ANTHROPIC_API_KEY
```

### Agent Providing Generic Advice

If the agent isn't personalizing recommendations:

1. Ensure you've provided your GitHub profile or portfolio URL
2. Check that memories are being saved (ask "what do you know about me?")
3. Give more context about your goals, skills, and constraints

## Guardrails & Responsible Use

This agent includes strict guardrails to ensure responsible content generation:

### No Fabricated Metrics
The agent will NEVER invent quantified claims without your actual measured data:
- Won't claim "saves 15 hours/week" without your baseline data
- Won't provide ROI calculations without your numbers
- Uses bracket notation for placeholders: "[X hours - to be determined]"
- Explicitly labels hypothetical examples as such

### No Fictional Social Proof
Won't create fake testimonials, case studies, or past client references:
- Outreach templates use honest "founding client" framing
- No invented success stories
- Case study templates clearly marked as placeholders

### Legal Disclaimers
Automatically flags content requiring legal review:
- Contracts, SOWs, and service agreements
- IP ownership clauses
- Guarantees and liability terms
- Recommendation: "⚠️ LEGAL REVIEW REQUIRED: Review with attorney before use"

### Employment Compliance
Reminds about potential employment conflicts:
- Moonlighting policies
- IP assignment clauses in employment agreements
- Non-compete and non-solicitation restrictions
- Frames as checklist, not legal advice

### Realistic Timelines
Provides honest time estimates:
- Factors in 50% longer delivery for first clients
- Includes buffers for client delays, scope clarification, integration issues
- Recommends 4-6 week timelines for first-time deliveries

### Validation Before Building
Always recommends customer discovery before execution:
- 5-10 customer calls before building products
- Low-effort validation methods
- Distinguish idea validation from solution validation
- Discourages premature execution

## Architecture

The business advisor uses:
- **Claude Sonnet 4.5** for strategic analysis and planning
- **Local MCP Client** via stdio transport
- **Optional GitHub MCP** for repository analysis
- **Anthropic SDK** for Claude API integration
- **Hot reload** - edit tools while agent is running

## Development

### Adding Business Analysis Features

To extend the agent:

1. **Add market research tools**: Integrate APIs for market data, competitor analysis
2. **Add financial modeling**: More sophisticated revenue projections and scenarios
3. **Add content generation**: Blog posts, landing pages, marketing copy (with guardrails)
4. **Add pitch deck creation**: Structured pitch deck generation

### Testing

```bash
# Test memory system
uv run python scripts/testing/test_memory.py

# Test with sample GitHub profile
uv run python -m agents.business_advisor.main
# Then provide: github.com/octocat

# Test guardrails by asking for fabricated content
# Agent should refuse or add disclaimers
```

### Hot Reload

Edit tools while the agent is running:

1. Edit tool code in `packages/agent-framework/agent_framework/tools/*.py`
2. Save the file
3. Type `reload` or next tool call picks up changes

See [HOT_RELOAD.md](../../HOT_RELOAD.md) for details.

## Related Documentation

- [CLAUDE.md](../../CLAUDE.md) - Project overview and development guide
- [GUIDES.md](../../GUIDES.md) - Memory system, deployment guides
- [agent-framework](../../packages/agent-framework/) - Shared library documentation
- [Testing Guide](../../docs/TESTING.md) - Testing and debugging
- [HOT_RELOAD.md](../../HOT_RELOAD.md) - Development workflow

## Ethical Considerations

This agent is designed to help developers build legitimate businesses. Important notes:

- **Honest communication**: Guardrails prevent fabricated social proof and unvalidated claims
- **Realistic expectations**: Agent provides honest assessments of effort, risk, and timelines
- **Validation first**: Always recommends talking to customers before building
- **Legal awareness**: Flags content requiring professional legal review
- **Responsible advice**: Won't encourage misleading marketing or unrealistic promises

The guardrails exist to help you build a sustainable, honest business that serves customers well and doesn't overpromise.
