# Task Manager Agent

An intelligent task management assistant powered by Claude that connects to a remote MCP server to help you organize, prioritize, and prepare for your tasks.

## Features

### 🔄 Reschedule Overdue Tasks
Automatically identifies expired or overdue tasks and intelligently reschedules them:
- Spreads tasks evenly across the next week or two
- Considers realistic completion timelines
- Avoids overloading specific days
- Maintains workload balance

### 🔍 Pre-Research Upcoming Tasks
Analyzes tasks coming up in the next day or few days:
- Searches for relevant documentation and resources
- Identifies potential blockers or dependencies
- Adds helpful context, links, and suggestions to task descriptions
- Breaks down complex tasks into manageable subtasks
- Prepares you for successful task completion

### ⚡ Intelligent Task Prioritization
Assigns relative priorities (1-10 scale) based on:
- Due dates and urgency
- Dependencies between tasks
- Estimated effort vs. deadline proximity
- Category-based importance
- Your patterns and preferences

## Setup

### Prerequisites

1. **Anthropic API Key**: Set in `.env` file
   ```bash
   ANTHROPIC_API_KEY=your_key_here
   ```

2. **Remote MCP Server**: Running at `https://mcp.brooksmcmillin.com/mcp` with task management tools

### Required MCP Tools

Your remote MCP server must expose these tools:

#### 1. `get_tasks`
Retrieve tasks with filtering options.

**Parameters:**
- `status` (string, optional): Filter by status ("pending", "completed", "overdue", "all")
- `start_date` (string, optional): ISO format date (e.g., "2025-12-14")
- `end_date` (string, optional): ISO format date
- `category` (string, optional): Filter by category
- `limit` (number, optional): Maximum number of tasks to return

**Returns:**
```json
{
  "tasks": [
    {
      "id": "task_123",
      "title": "Task name",
      "description": "Details...",
      "due_date": "2025-12-20",
      "status": "pending",
      "category": "work",
      "priority": 5,
      "tags": ["urgent", "research"],
      "created_at": "2025-12-01",
      "updated_at": "2025-12-10"
    }
  ]
}
```

#### 2. `create_task`
Create a new task.

**Parameters:**
- `title` (string, required): Task title
- `description` (string, optional): Task details
- `due_date` (string, optional): ISO format date
- `category` (string, optional): Task category
- `priority` (number, optional): Priority 1-10
- `tags` (array of strings, optional): Task tags

**Returns:**
```json
{
  "id": "task_456",
  "title": "New task",
  "status": "created"
}
```

#### 3. `update_task`
Update an existing task.

**Parameters:**
- `task_id` (string, required): Task ID
- `title` (string, optional): New title
- `description` (string, optional): New description
- `due_date` (string, optional): New due date (for rescheduling)
- `status` (string, optional): New status
- `category` (string, optional): New category
- `priority` (number, optional): New priority
- `tags` (array of strings, optional): New tags

**Returns:**
```json
{
  "id": "task_123",
  "updated_fields": ["due_date", "priority"],
  "status": "updated"
}
```

#### 4. `get_categories`
List all available task categories.

**Returns:**
```json
{
  "categories": [
    {"name": "work", "task_count": 15},
    {"name": "personal", "task_count": 8},
    {"name": "research", "task_count": 5}
  ]
}
```

#### 5. `search_tasks` (optional)
Search tasks by keyword.

**Parameters:**
- `query` (string, required): Search query
- `category` (string, optional): Filter by category

**Returns:**
```json
{
  "tasks": [/* same format as get_tasks */],
  "count": 5
}
```

## Usage

### Start the Agent

```bash
# Default MCP URL (https://mcp.brooksmcmillin.com/mcp)
uv run python -m agents.task_manager.main

# Custom MCP URL (via environment variable)
MCP_SERVER_URL=https://your-mcp-server.com/mcp uv run python -m agents.task_manager.main
```

### Interactive Commands

Once running, you can use these commands:
- `exit`, `quit`, `q` - Exit the agent
- `stats` - Show token usage statistics
- `reload` - Reconnect to MCP server (refresh tools)

### Example Conversations

**Reschedule overdue tasks:**
```
You: I have some overdue tasks. Can you reschedule them for me?

Agent: I'll help you reschedule your overdue tasks. Let me first check what tasks are overdue.
[Calls get_tasks with status="overdue"]

I found 5 overdue tasks. Here's my suggested rescheduling:
- "Write blog post" (due Dec 10) → Dec 16 (Monday)
- "Review PRs" (due Dec 11) → Dec 17 (Tuesday)
- "Update documentation" (due Dec 12) → Dec 18 (Wednesday)
...

This spreads them across the next week. Shall I proceed with these changes?
```

**Pre-research upcoming tasks:**
```
You: What tasks do I have coming up tomorrow? Can you help me prepare?

Agent: Let me check your tasks for tomorrow and gather some helpful resources.
[Calls get_tasks with start_date="2025-12-15", end_date="2025-12-15"]

You have 3 tasks tomorrow:

1. "Implement OAuth flow" - I found:
   - OAuth 2.0 spec: https://oauth.net/2/
   - Best practices article
   - Common pitfalls to avoid

   Updated task with these resources and suggested breaking it into:
   - Set up authorization endpoint
   - Implement token exchange
   - Add refresh token logic

2. "Team meeting prep"...
```

**Prioritize tasks:**
```
You: Can you prioritize all my work tasks?

Agent: I'll analyze and prioritize your work tasks based on urgency and dependencies.
[Calls get_tasks with category="work"]

Found 12 work tasks. Here's my suggested prioritization:

HIGH PRIORITY (8-10):
- "Fix production bug" (Priority 10) - Due today, blocking users
- "Deploy hotfix" (Priority 9) - Due tomorrow, dependency on bug fix
...

MEDIUM PRIORITY (5-7):
- "Refactor auth module" (Priority 6) - Due next week, technical debt
...

Shall I update these priorities in your task system?
```

## Architecture

This agent uses:
- **Claude Sonnet 4.5** for intelligent task analysis and decision-making
- **Remote MCP Client** to connect to your task management server via HTTP/SSE
- **Anthropic SDK** for Claude API integration
- **Async/await** for efficient I/O operations

The agent maintains conversation context across multiple turns and can execute multiple tool calls in sequence to accomplish complex goals.

## Configuration

### Environment Variables

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-...

# Optional
MCP_SERVER_URL=https://mcp.brooksmcmillin.com/mcp  # Default if not set
LOG_LEVEL=INFO  # DEBUG, INFO, WARNING, ERROR
```

### Customization

You can customize the agent's behavior by editing `agents/task_manager/prompts.py`:
- **SYSTEM_PROMPT**: Defines agent capabilities and behavior
- **USER_GREETING_PROMPT**: Initial greeting message

## Troubleshooting

### Connection Issues

```bash
# Test MCP server connectivity
curl https://mcp.brooksmcmillin.com/mcp/health

# Check server logs
# Ensure tools are properly exposed
```

### Missing Tools

If the agent reports missing tools:
1. Verify your MCP server exposes all required tools (see list above)
2. Use `reload` command to refresh tool list
3. Check MCP server logs for errors

### API Key Issues

```bash
# Verify API key is set
echo $ANTHROPIC_API_KEY

# Check .env file exists
cat .env | grep ANTHROPIC_API_KEY
```

## Development

### Adding New Capabilities

To add new task management features:

1. **Add MCP tool** to your remote server
2. **Update SYSTEM_PROMPT** in `prompts.py` to describe the new capability
3. Agent automatically discovers and uses new tools on next connection

### Testing

```bash
# Test MCP connection
uv run python -c "
import asyncio
from shared.remote_mcp_client import RemoteMCPClient

async def test():
    async with RemoteMCPClient('https://mcp.brooksmcmillin.com/mcp') as mcp:
        tools = await mcp.list_tools()
        print(f'Available tools: {[t[\"name\"] for t in tools]}')

asyncio.run(test())
"
```

## Related Documentation

- [Remote MCP Setup](../../REMOTE_MCP.md) - Remote MCP server architecture
- [CLAUDE.md](../../CLAUDE.md) - Project overview and development guide
- [MCP Tools](../../config/mcp_server/) - MCP server implementation examples
