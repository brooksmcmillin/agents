# Quick Start Guide

Get up and running with PR Agent in 5 minutes!

## 1. Install Dependencies

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install packages
pip install -r requirements.txt
```

## 2. Configure API Key

```bash
# Copy example env file
cp .env.example .env

# Edit .env and add your Anthropic API key
# ANTHROPIC_API_KEY=your_key_here
```

## 3. Run the Demo

Test that everything works with mock data:

```bash
python demo.py
```

This will:
- Connect to the MCP server
- Call all three tools (analyze_website, get_social_media_stats, suggest_content_topics)
- Display mock results

## 4. Try the Interactive Agent

Start a conversation with the PR assistant:

```bash
python -m agent.main
```

Example prompts to try:
- "Analyze https://example.com/blog for SEO"
- "Get my Twitter stats for the last 30 days"
- "Suggest 5 blog post ideas"
- "What should I post on LinkedIn this week?"

## 5. Check Token Usage

While in interactive mode, type `stats` to see token usage.

## Project Structure

```
pr_agent/
├── mcp_server/          # MCP server with tools
│   ├── server.py        # Main MCP server
│   ├── tools/           # Tool implementations
│   │   ├── web_analyzer.py
│   │   ├── social_media.py
│   │   └── content_suggestions.py
│   └── auth/            # OAuth handling
│       ├── oauth_handler.py
│       └── token_store.py
├── agent/               # Agent application
│   ├── main.py          # Main agent orchestrator
│   ├── mcp_client.py    # MCP client connection
│   └── prompts.py       # System prompts
├── demo.py              # Demo script
├── .env                 # Your config (create this)
└── README.md            # Full documentation
```

## Available MCP Tools

The MCP server provides these tools:

### `analyze_website`
Analyzes web content for tone, SEO, or engagement.

**Parameters:**
- `url` (string): URL to analyze
- `analysis_type` (enum): "tone", "seo", or "engagement"

### `get_social_media_stats`
Retrieves social media performance metrics.

**Parameters:**
- `platform` (enum): "twitter" or "linkedin"
- `timeframe` (enum): "7d", "30d", or "90d"

### `suggest_content_topics`
Generates content topic suggestions.

**Parameters:**
- `content_type` (enum): "blog", "twitter", or "linkedin"
- `count` (integer): Number of suggestions (1-10)

## Current Status

**Working:**
- ✅ MCP server with 3 tools
- ✅ OAuth handler with token storage
- ✅ Agent with Claude integration
- ✅ Mock data for all tools
- ✅ Error handling and logging
- ✅ Token usage tracking

**Next Steps (for production):**
- Implement real web scraping
- Integrate Twitter/LinkedIn APIs
- Set up OAuth consent flow
- Add database token storage
- Deploy MCP server

## Troubleshooting

**Error: "ANTHROPIC_API_KEY not found"**
- Make sure you created `.env` file
- Add `ANTHROPIC_API_KEY=your_key_here`
- Restart the application

**Error: "ModuleNotFoundError"**
- Make sure virtual environment is activated
- Run `pip install -r requirements.txt`

**MCP connection issues:**
- Check that `python -m mcp_server.server` runs without errors
- Review logs in `pr_agent.log`

## Need Help?

- Check `README.md` for full documentation
- Review code comments for implementation details
- Check `pr_agent.log` for debugging information
