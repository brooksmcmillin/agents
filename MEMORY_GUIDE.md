# Memory System Guide

The PR Agent now has persistent memory! It can save and recall important information across conversations, providing continuity and a personalized experience.

## What Gets Remembered

The agent automatically saves:
- **User Preferences** - Blog URLs, social media handles, posting schedules
- **Brand Voice** - Tone, style, messaging discovered from content analysis
- **Goals** - "Increase Twitter engagement", "Post twice weekly"
- **Insights** - "Video performs best", "SEO needs work on titles"
- **Facts** - Company name, industry, target audience

## How It Works

### Storage
- Memories are stored in `memories/memories.json` (created automatically)
- Persists across agent restarts
- Encrypted option available (see `memory_store.py`)
- Can be easily migrated to a database (see migration notes in code)

### Memory Structure

Each memory has:
- **key**: Unique identifier (e.g., "user_blog_url")
- **value**: The information to remember
- **category**: Optional grouping ("user_preference", "fact", "goal", "insight")
- **tags**: List of tags for filtering (e.g., ["seo", "twitter"])
- **importance**: 1-10 scale (7+ = critical, 4-6 = context, 1-3 = minor)
- **created_at**: When first saved
- **updated_at**: When last modified

## Agent Behavior

### First Conversation
```
You: Help me with my blog at https://example.com

Agent:
1. Analyzes your blog
2. Saves: blog URL, brand voice, SEO insights
3. Provides recommendations
4. Remembers everything for next time
```

### Returning Conversation
```
You: I'm back!

Agent:
1. Retrieves all saved memories
2. Greets with context: "Welcome back! Last time we worked on improving your SEO..."
3. Continues where you left off
4. Updates memories as needed
```

## MCP Tools

### save_memory
Save or update information:

```python
save_memory(
    key="user_blog_url",
    value="https://example.com/blog",
    category="user_preference",
    tags=["blog", "website"],
    importance=8
)
```

### get_memories
Retrieve saved information:

```python
# Get all memories
get_memories()

# Get high-importance items only
get_memories(min_importance=7)

# Get all goals
get_memories(category="goal")

# Get Twitter-related memories
get_memories(tags=["twitter"])
```

### search_memories
Search by keyword:

```python
search_memories(query="blog")
# Returns all memories containing "blog" in key or value
```

## Example Memory Store

After a few conversations, your memories might look like:

```json
{
  "user_blog_url": {
    "key": "user_blog_url",
    "value": "https://example.com/blog",
    "category": "user_preference",
    "tags": ["blog", "website"],
    "importance": 9,
    "created_at": "2025-01-15T10:30:00",
    "updated_at": "2025-01-15T10:30:00"
  },
  "brand_voice": {
    "key": "brand_voice",
    "value": "Professional but conversational, explains technical concepts clearly",
    "category": "insight",
    "tags": ["branding", "tone"],
    "importance": 8,
    "created_at": "2025-01-15T10:35:00",
    "updated_at": "2025-01-15T10:35:00"
  },
  "twitter_goal": {
    "key": "twitter_goal",
    "value": "Increase engagement by posting video content during peak hours (9-11 AM)",
    "category": "goal",
    "tags": ["twitter", "engagement", "video"],
    "importance": 10,
    "created_at": "2025-01-15T10:40:00",
    "updated_at": "2025-01-16T14:20:00"
  }
}
```

## Managing Memories

### View Memories Manually

```bash
cat memories/memories.json | python -m json.tool
```

### Edit Memories

Simply edit `memories/memories.json` with a text editor. The agent will load changes on next tool call.

### Delete All Memories

```bash
rm memories/memories.json
```

### Backup Memories

```bash
cp memories/memories.json memories/backup_$(date +%Y%m%d).json
```

## Privacy & Security

- Memories are stored locally in `memories/`
- Not sent anywhere except when the agent uses them
- Can be encrypted (set encryption key in `memory_store.py`)
- Add to `.gitignore` (already done) to avoid committing to git

## Migration to Database

The memory system is designed for easy migration. See `mcp_server/memory_store.py` for:
- Example SQL schema
- Interface documentation
- Migration guide

To switch to PostgreSQL/MySQL:
1. Create database table (schema in comments)
2. Implement same interface (`save_memory`, `get_memory`, etc.)
3. Update `memory_store.py` to use database instead of files
4. No changes needed to tools or agent!

## Best Practices

### For Users
- Be explicit about what you want remembered
- Tell the agent about goal changes
- Review important memories periodically

### For Developers
- Keep keys consistent and descriptive
- Use categories and tags for organization
- Set importance thoughtfully (helps retrieval)
- Update rather than create duplicates

## Hot Reload Support

Memory tools support hot reload! While the agent is running:

```bash
# Edit memory storage code
vim mcp_server/memory_store.py

# Or edit the memory tools
vim mcp_server/tools/memory.py

# Changes apply on next tool call!
```

## Troubleshooting

**Q: Agent doesn't remember anything**
- Check if `memories/memories.json` exists
- Verify JSON is valid: `python -m json.tool < memories/memories.json`
- Check logs: `tail -f pr_agent.log`

**Q: Want to start fresh**
- Delete `memories/memories.json`
- Or move it to a backup location

**Q: Memories growing too large**
- Filter by importance when retrieving: `get_memories(min_importance=7)`
- Delete low-importance items manually
- Archive old memories to separate file

## Examples

### Save a user preference
```python
save_memory(
    key="posting_schedule",
    value="Monday, Wednesday, Friday at 9 AM EST",
    category="user_preference",
    tags=["schedule", "twitter"],
    importance=7
)
```

### Remember an insight
```python
save_memory(
    key="seo_weakness",
    value="Title tags are too short, averaging 35 characters. Should be 50-60.",
    category="insight",
    tags=["seo", "titles"],
    importance=8
)
```

### Track a goal
```python
save_memory(
    key="q1_2025_goal",
    value="Publish 8 blog posts and increase organic traffic by 25%",
    category="goal",
    tags=["blog", "seo", "2025"],
    importance=10
)
```

### Update existing memory
```python
# Same key = update, not duplicate
save_memory(
    key="twitter_goal",
    value="Achieved 20% engagement increase! New goal: 30% by end of quarter",
    importance=10
)
```

## Architecture

```
User Question
     ↓
Agent checks memories (get_memories)
     ↓
Agent uses context to provide personalized response
     ↓
Agent saves new insights (save_memory)
     ↓
Memories persist to disk
     ↓
Next conversation starts with full context!
```

The memory system makes the agent truly useful over time - it learns about you and your goals, providing increasingly personalized and relevant advice.
