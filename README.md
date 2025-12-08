# PR Agent - LLM-Powered Content Strategy Assistant

An intelligent PR and content strategy assistant built with Claude (Anthropic SDK) and Model Context Protocol (MCP). This agent analyzes your blog and social media content, provides data-driven recommendations, and suggests content topics to improve your online presence.

## Architecture

The system consists of two main components:

### 1. MCP Server (`mcp_server/`)

Handles external API integrations and provides tools via the Model Context Protocol:

- **Web Analyzer**: Fetches and analyzes web content for tone, SEO, and engagement
- **Social Media Stats**: Retrieves performance metrics from Twitter and LinkedIn
- **Content Suggestions**: Generates topic ideas based on content analysis

Features:
- OAuth 2.0 flow implementation with auto-refresh
- Secure token storage with encryption
- Comprehensive error handling and logging
- Mock data for testing (ready for real API integration)

### 2. Agent Application (`agent/`)

Orchestrates the LLM using Claude Sonnet 4.5:

- Connects to MCP server for tool access
- Implements agentic loop with multi-turn conversations
- Handles tool calling and result processing
- Tracks token usage and provides statistics

## Features

- **Agentic Workflow**: Claude autonomously decides when to use tools
- **OAuth Support**: Ready for real social media API integration
- **Secure Token Management**: Encrypted storage with easy migration path
- **Comprehensive Logging**: Track all operations and debug issues
- **Type Safety**: Full type hints throughout
- **Async/Await**: Proper async handling for MCP operations
- **Error Handling**: Graceful handling of auth failures and API errors

## Installation

### Prerequisites

- Python 3.11 or higher
- Anthropic API key

### Setup

1. **Clone and navigate to the project:**
   ```bash
   cd pr_agent
   ```

2. **Create a virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables:**
   ```bash
   cp .env.example .env
   ```

   Edit `.env` and add your Anthropic API key:
   ```
   ANTHROPIC_API_KEY=your_api_key_here
   ```

## Usage

### Running the Agent

Start an interactive session with the PR assistant:

```bash
python -m agent.main
```

### Example Interactions

**Analyze a blog post:**
```
You: Analyze my blog post at https://example.com/my-post for tone