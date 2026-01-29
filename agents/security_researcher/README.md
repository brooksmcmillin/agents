# Security Researcher Agent

An expert AI security research assistant powered by Claude Sonnet 4.5, specialized in AI/ML security, LLM vulnerabilities, and technical content fact-checking. Features RAG-backed knowledge base integration for querying security research papers and maintaining domain expertise.

## Features

### 🔍 AI Security Research Expertise
- Deep knowledge of AI/ML security vulnerabilities and attack vectors
- LLM-specific threats: prompt injection, jailbreaking, model extraction
- Adversarial ML: evasion, poisoning, backdoors, membership inference
- RAG system security and prompt injection through retrieved content
- AI supply chain security and secure deployment practices

### 📚 RAG Knowledge Base Integration
- Add security research papers to a searchable knowledge base
- Query papers with semantic similarity search
- Synthesize findings across multiple papers
- Track citations and research references
- Stay current with AI security literature

### ✅ Blog Post Fact-Checking
- Verify technical claims against research literature
- Identify unsupported or inaccurate statements
- Check terminology accuracy and proper usage
- Suggest improvements for clarity and precision
- Recommend citations and additional references
- Flag misconceptions or oversimplifications

### 🛡️ Security Reviews
- Threat modeling for AI/LLM systems
- Architecture security analysis
- Attack surface identification
- Defense mechanism evaluation
- Compliance with security best practices
- Actionable remediation recommendations

### 🧠 Persistent Memory
- Save security insights and findings across conversations
- Track user's system architecture and threat models
- Remember research interests and focus areas
- Maintain context about ongoing security projects

## Quick Start

### Prerequisites

1. **Python 3.11 or higher**

2. **Anthropic API Key**: Required for Claude
   ```bash
   ANTHROPIC_API_KEY=your_key_here
   ```

3. **RAG Requirements** (Critical - this agent heavily uses RAG):
   - PostgreSQL database for document storage
   - OpenAI API key for embeddings
   ```bash
   RAG_DATABASE_URL=postgresql://user:pass@localhost:5432/agent_rag
   OPENAI_API_KEY=sk-...
   ```

4. **Optional**: Database for memory backend
   ```bash
   MEMORY_BACKEND=database
   MEMORY_DATABASE_URL=postgresql://user:pass@localhost:5432/agent_memory
   ```

### Installation

```bash
# Install dependencies
uv sync

# Set up PostgreSQL database for RAG
createdb agent_rag

# Initialize RAG schema (run once)
psql agent_rag < packages/agent-framework/schema/rag.sql
```

### Configuration

Copy `.env.example` to `.env` and configure:

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-...
RAG_DATABASE_URL=postgresql://user:pass@localhost:5432/agent_rag
OPENAI_API_KEY=sk-...  # for embeddings

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
# Start the security researcher agent
uv run python -m agents.security_researcher.main
```

## MCP Tools

The security researcher has access to **14 tools** across 4 categories:

### Web Content Analysis (1 tool)
- **fetch_web_content**: Fetch web content as clean markdown for reading and fact-checking
  - Parameters: `url` (string), `max_length` (optional, default 50000)
  - Returns: URL, title, content, word count, metadata
  - Essential for blog post review and content verification

### RAG Document Search (6 tools)
*Required for core functionality*

- **add_document**: Add security research paper to knowledge base
  - Parameters: `content` (string), `metadata` (dict, optional), `document_id` (string, optional)
  - Use for: Adding research papers, security advisories, vulnerability reports

- **search_documents**: Search knowledge base by query
  - Parameters: `query` (string), `limit` (int, default 5), `min_similarity` (float, default 0.7)
  - Use for: Finding relevant research, answering security questions, verifying claims

- **get_document**: Retrieve full document by ID
  - Parameters: `document_id` (string)
  - Use for: Reading complete paper content, getting full context

- **list_documents**: List all documents in knowledge base
  - Parameters: `limit` (int, optional), `offset` (int, optional)
  - Use for: Browsing available research, managing knowledge base

- **delete_document**: Remove document from knowledge base
  - Parameters: `document_id` (string)
  - Use for: Removing outdated or duplicate papers

- **get_rag_stats**: Get RAG system statistics
  - Returns: Total documents, total chunks, database size
  - Use for: Monitoring knowledge base growth and health

### Memory (6 tools)
- **save_memory**: Save security insights, findings, or context
  - Parameters: `key`, `value`, `category` (optional), `tags` (optional), `importance` (1-10, optional)
  - Use for: Tracking user's systems, threat models, research interests

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
- **send_slack_message**: Send security alerts and notifications
  - Parameters: `channel`, `text`, `username` (optional), `icon_emoji` (optional)

## Usage Examples

### Example 1: Research Question with RAG

```
You: What are the main attack vectors against RAG systems?

Agent: Let me search my knowledge base for research on RAG security vulnerabilities.
[Calls search_documents with query="RAG system attacks vulnerabilities"]

Based on recent security research, I've identified these main attack vectors against RAG systems:

1. **Prompt Injection Through Retrieved Documents**
   - Attackers poison the knowledge base with malicious instructions
   - Retrieved documents can override system prompts
   - Defense: Sanitize retrieved content, use structured outputs

2. **Data Poisoning of the Knowledge Base**
   - Inject misleading or malicious information
   - Subtly alter facts to produce incorrect outputs
   - Defense: Access controls, content validation, provenance tracking

3. **Information Leakage Through Retrieval**
   - Inference attacks on what documents exist
   - Extracting sensitive info via crafted queries
   - Defense: Query filtering, retrieval access controls

4. **Indirect Prompt Injection**
   - Malicious content in legitimate documents
   - Instructions embedded in retrieved text
   - Defense: Content scanning, privilege separation

Sources: [Lists specific papers from knowledge base with document IDs]

[Saves context to memory: user interested in RAG security]

Would you like me to dive deeper into any of these attack vectors or discuss specific mitigations?
```

### Example 2: Blog Post Fact-Checking

```
You: Can you review my blog post about LLM security? https://myblog.com/llm-security

Agent: I'll fetch and review your blog post for technical accuracy.
[Calls fetch_web_content]
[Calls search_documents for relevant research to verify claims]

## Fact-Check Review: LLM Security Best Practices

### Summary
Your post covers prompt injection, jailbreaking, and basic mitigations. Overall technically sound with a few clarifications needed.

### Verified Claims ✓
- ✓ "Prompt injection is the #1 vulnerability in LLM applications" - Correct, well-documented
- ✓ "Input validation is essential" - Accurate best practice
- ✓ "System prompts can be leaked via crafted queries" - Confirmed by research

### Issues Found ⚠️
1. **Line 45**: "Rate limiting prevents all prompt injection attacks"
   - Issue: Overstated claim
   - Correction: Rate limiting helps prevent DoS but doesn't stop prompt injection
   - Suggested rewording: "Rate limiting mitigates abuse and DoS, but additional controls are needed for prompt injection"

2. **Line 78**: "Fine-tuning removes all harmful outputs"
   - Issue: Incorrect - fine-tuning can be circumvented
   - Correction: Fine-tuning improves safety but isn't foolproof
   - Add: Mention adversarial suffix attacks that bypass fine-tuning

### Completeness
Missing important topics:
- Indirect prompt injection (via retrieved content)
- Output filtering and content safety APIs
- Monitoring and incident response for LLM applications

### Recommended Citations
- Add: "Prompt Injection Attacks Against LLMs" (arXiv:2302.12173)
- Add: OWASP Top 10 for LLM Applications reference
- Add: Recent work on jailbreaking defenses

### Overall Assessment
Strong foundation, but needs corrections on overstated claims and coverage of indirect attacks. The mitigations section could be more comprehensive.

[Saves to memory: user writing blog series on LLM security]

Would you like me to suggest specific text revisions for the issues I found?
```

### Example 3: Security Review

```
You: Can you review the security of my RAG-based customer support chatbot?

Agent: I'll conduct a security review of your RAG chatbot. Let me first gather some details.
[Checks memories for any previous context about this system]

What information can you provide about:
1. System architecture: How does your RAG pipeline work? (retrieval → LLM → response)
2. Knowledge base: What documents are in it? Who can modify them?
3. User inputs: Are they validated or sanitized?
4. Access controls: Authentication, authorization, rate limiting?
5. Monitoring: Logging, anomaly detection, abuse monitoring?

[After receiving details...]

## Security Review: Customer Support RAG Chatbot

### Overview
RAG-based chatbot for customer support with product documentation knowledge base.
External users interact directly via web interface.

### Threat Model
- **Attacker Goals**: Extract sensitive info, manipulate responses, DoS, prompt injection
- **Assets at Risk**: Customer data, product documentation, chatbot availability
- **Attack Surface**: User input field, retrieval pipeline, LLM interface

### Findings

#### Critical
🔴 **Prompt Injection via Retrieved Documents**
- Knowledge base has no content sanitization
- Retrieved documents directly concatenated into LLM prompt
- **Risk**: Attacker adds malicious instructions to documentation
- **Mitigation**: Implement retrieval content filtering, use structured outputs

🔴 **No Input Validation**
- User queries passed directly to retrieval and LLM
- **Risk**: Adversarial queries, information extraction, jailbreaking
- **Mitigation**: Input sanitization, query length limits, content filtering

#### High
🟠 **Information Leakage Through Error Messages**
- Detailed errors exposed to users reveal system internals
- **Risk**: Reconnaissance for attacks, sensitive info disclosure
- **Mitigation**: Generic error messages, detailed logging server-side only

🟠 **No Rate Limiting**
- Unlimited queries per user
- **Risk**: DoS attacks, abuse, cost explosion
- **Mitigation**: Per-user/IP rate limits, CAPTCHA, cost monitoring

#### Medium
🟡 **Insufficient Logging**
- Queries and responses not logged
- **Risk**: Cannot detect or investigate abuse
- **Mitigation**: Log all interactions with retention policy

### Recommendations
1. **Immediate** (Critical):
   - Add input sanitization and validation
   - Implement content filtering for retrieved documents
   - Deploy rate limiting (100 queries/hour per IP)

2. **Short-term** (High, within 2 weeks):
   - Improve error handling
   - Implement comprehensive logging and monitoring
   - Add anomaly detection for abuse patterns

3. **Medium-term** (Medium, within 1 month):
   - Implement output filtering/content safety API
   - Add privilege separation between retrieval and generation
   - Set up alerting for security events

### Next Steps
1. Prioritize the two Critical findings
2. Would you like detailed implementation guidance for any of these mitigations?
3. Consider a red teaming exercise once mitigations are in place

[Saves architecture and findings to memory for follow-up]

Let me know which areas you'd like to tackle first, and I can provide specific implementation recommendations.
```

### Example 4: Adding Research Papers to Knowledge Base

```
You: I want to add this new research paper on adversarial prompts

Agent: I'll help you add that paper to your knowledge base. Please provide:
- The paper content (text, PDF, or URL)
- Any metadata (title, authors, publication date, arXiv ID)

[After receiving paper...]

[Calls add_document with content and metadata]

Successfully added "Adversarial Prompts in Large Language Models" to your knowledge base!
- Document ID: doc_789
- Added 15 chunks for semantic search
- Metadata: Authors, 2024, arXiv:2401.12345

The paper is now searchable and will be included in future research queries.

[Saves to memory: user interested in adversarial prompts research]

Would you like me to summarize the key findings from this paper?
```

## RAG Setup Guide

### Populating Your Knowledge Base

Add security research papers to enable the agent's research capabilities:

```bash
# Option 1: Add papers via agent conversation
# Start agent and provide paper content directly

# Option 2: Bulk add papers via script
uv run python scripts/add_security_papers.py /path/to/papers/

# Option 3: Use add_document tool programmatically
uv run python -c "
import asyncio
from agent_framework.tools import add_document

async def add_paper():
    with open('paper.txt', 'r') as f:
        content = f.read()

    result = await add_document(
        content=content,
        metadata={
            'title': 'Prompt Injection Attacks',
            'authors': ['Smith et al.'],
            'year': 2024,
            'arxiv_id': 'arXiv:2401.12345'
        }
    )
    print(result)

asyncio.run(add_paper())
"
```

### Recommended Papers to Add

To build a comprehensive AI security knowledge base, consider adding:

**LLM Security:**
- "Prompt Injection Attacks Against LLMs" (arXiv:2302.12173)
- "Jailbreaking ChatGPT via Prompt Engineering" (arXiv:2305.13860)
- "Universal and Transferable Adversarial Attacks on Aligned LLMs" (arXiv:2307.15043)

**Adversarial ML:**
- "Explaining and Harnessing Adversarial Examples" (Goodfellow et al., 2015)
- "Backdoor Attacks Against Deep Neural Networks" (various)
- "Membership Inference Attacks Against Machine Learning Models" (Shokri et al., 2017)

**RAG Security:**
- Research on retrieval-augmented generation vulnerabilities
- Indirect prompt injection via retrieved content
- Data poisoning in knowledge bases

**Defense Mechanisms:**
- Constitutional AI and RLHF papers
- Output filtering and content safety
- Red teaming and adversarial testing methodologies

## Interactive Commands

- `exit`, `quit`, `q` - Exit the agent
- `stats` - Show token usage statistics
- `reload` - Reconnect to MCP server (refresh tools)

## Configuration

### Environment Variables

```bash
# Core Configuration (Required)
ANTHROPIC_API_KEY=sk-ant-...          # Anthropic API key
RAG_DATABASE_URL=postgresql://...     # PostgreSQL for RAG
OPENAI_API_KEY=sk-...                # OpenAI for embeddings

# Memory Configuration (Optional)
MEMORY_BACKEND=file                   # file (default) or database
MEMORY_DATABASE_URL=postgresql://...  # if using database

# Communication (Optional)
SLACK_WEBHOOK_URL=https://hooks...   # for security alerts

# Logging
LOG_LEVEL=INFO                       # DEBUG, INFO, WARNING, ERROR
```

### Customization

Edit `agents/security_researcher/prompts.py` to customize:
- **SYSTEM_PROMPT**: Agent expertise and behavior
- **USER_GREETING_PROMPT**: Initial greeting
- **SECURITY_REVIEW_TEMPLATE**: Structure for security reviews
- **FACT_CHECK_TEMPLATE**: Structure for fact-checking reports

## Troubleshooting

### RAG Not Working

The most common issue - RAG is required for this agent:

```bash
# Verify database exists and is accessible
psql $RAG_DATABASE_URL -c "SELECT COUNT(*) FROM documents"

# Check if tables exist
psql $RAG_DATABASE_URL -c "\dt"

# Initialize schema if missing
psql $RAG_DATABASE_URL < packages/agent-framework/schema/rag.sql

# Verify OpenAI API key
curl https://api.openai.com/v1/models \
  -H "Authorization: Bearer $OPENAI_API_KEY"
```

### No Documents in Knowledge Base

```bash
# Check if any documents are added
psql $RAG_DATABASE_URL -c "SELECT id, metadata FROM documents LIMIT 10"

# Add test document
uv run python -c "
import asyncio
from agent_framework.tools import add_document

async def test():
    result = await add_document(
        content='Test security paper about prompt injection...',
        metadata={'title': 'Test Paper', 'authors': ['Test']}
    )
    print(result)

asyncio.run(test())
"
```

### OpenAI API Errors

```bash
# Check API key is valid
echo $OPENAI_API_KEY

# Test embeddings endpoint
curl https://api.openai.com/v1/embeddings \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"input": "test", "model": "text-embedding-ada-002"}'
```

### PostgreSQL Connection Issues

```bash
# Test database connectivity
psql $RAG_DATABASE_URL -c "SELECT version()"

# Check connection string format
# Correct: postgresql://user:pass@host:5432/dbname
# Common error: missing database name or wrong port
```

### Memory Issues

```bash
# View memory statistics in conversation
You: Can you show me memory statistics?

# Check file-based memories
ls -la memories/

# For database backend
psql $MEMORY_DATABASE_URL -c "SELECT COUNT(*) FROM memories"
```

### API Key Issues

```bash
# Verify all required keys are set
echo $ANTHROPIC_API_KEY
echo $RAG_DATABASE_URL
echo $OPENAI_API_KEY

# Check .env file
cat .env | grep -E '(ANTHROPIC|RAG|OPENAI)'
```

## Architecture

The security researcher uses:
- **Claude Sonnet 4.5** for security expertise and analysis
- **PostgreSQL + pgvector** for RAG document storage and semantic search
- **OpenAI Ada-002** for document embeddings
- **Local MCP Client** via stdio transport
- **Hot reload** - edit tools while agent is running

The agent maintains conversation context and can execute complex multi-step research and analysis workflows.

## Development

### Adding Security-Specific Features

To extend the agent:

1. **Add new research sources**: Integrate arXiv API, Semantic Scholar, etc.
2. **Add CVE database**: Query CVE databases for vulnerability information
3. **Add code analysis**: Integrate static analysis tools for security reviews
4. **Enhance RAG**: Add citation tracking, paper relationship graphs

### Testing

```bash
# Test RAG functionality
uv run python scripts/testing/test_rag.py

# Test memory system
uv run python scripts/testing/test_memory.py

# Test full agent workflow
uv run python -m agents.security_researcher.main
```

### Hot Reload

Edit tools while the agent is running:

1. Edit tool code in `packages/agent-framework/agent_framework/tools/*.py`
2. Save the file
3. Type `reload` or next tool call picks up changes

See [HOT_RELOAD.md](../../HOT_RELOAD.md) for details.

## Related Documentation

- [CLAUDE.md](../../CLAUDE.md) - Project overview and development guide
- [GUIDES.md](../../GUIDES.md) - RAG setup, memory system, deployment
- [agent-framework](../../packages/agent-framework/) - Shared library documentation
- [Testing Guide](../../docs/TESTING.md) - Testing and debugging
- [HOT_RELOAD.md](../../HOT_RELOAD.md) - Development workflow

## Security Considerations

This agent provides security advice and analysis. Important notes:

- **Accuracy**: Security recommendations are based on research and best practices, but should be validated for your specific context
- **Currency**: AI security is a rapidly evolving field - verify that advice reflects current understanding
- **Scope**: Reviews are based on provided information and may not catch all vulnerabilities
- **Responsible Use**: Do not use this agent to develop or improve malicious tools or techniques
- **Limitations**: This is a research assistant, not a replacement for professional security audits
