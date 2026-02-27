# Events Agent

Local events discovery assistant that fetches calendar pages, parses event information, and learns user preferences over time.

## Features

- **Calendar scraping** — fetch and parse event listings from venue and calendar websites
- **Preference learning** — remembers liked/disliked event types, timing, budget, and location preferences
- **Smart recommendations** — ranks and filters events based on stored preferences
- **Location awareness** — respects distance and area constraints

## Quick Start

```bash
uv run bin/run-agent events
```

## MCP Tools

- `fetch_web_content` — scrape calendar pages and event listings
- `save_memory`, `get_memories`, `search_memories` — store and recall event preferences

## Usage Examples

```
You: Check https://venue.com/calendar for upcoming events
Agent: [fetches page, parses events, presents recommendations]

You: I love jazz but don't like country music
Agent: [saves preferences, adjusts future recommendations]

You: What's happening this weekend?
Agent: [checks saved calendar sources, filters by preferences]
```

## Configuration

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-...
```

No additional configuration needed. The agent learns preferences through conversation and stores them in memory.

## Architecture

Uses `create_simple_agent()` with web fetching and memory tools. Preferences are stored as memories with structured key patterns (`pref_likes_*`, `pref_dislikes_*`, `source_*`, `location_*`) for reliable retrieval.

## Related Documentation

- [CLAUDE.md](../../CLAUDE.md) — project overview
- [docs/GUIDES.md](../../docs/GUIDES.md) — memory system guide
