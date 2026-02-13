# Observability with Langfuse

The agent framework includes built-in observability via [Langfuse](https://langfuse.com), providing:
- **Traces** for each conversation turn with full context
- **Spans** for individual tool calls with inputs/outputs
- **Automatic LLM call instrumentation** via OpenTelemetry
- **Token usage and latency tracking**
- **Dashboard and alerting capabilities**

## Setup

1. Sign up for [Langfuse Cloud](https://cloud.langfuse.com) or [self-host](https://langfuse.com/docs/deployment/self-host)
2. Get your API keys from Project Settings
3. Add to `.env`:
   ```
   LANGFUSE_ENABLED=true
   LANGFUSE_PUBLIC_KEY=pk-lf-...
   LANGFUSE_SECRET_KEY=sk-lf-...
   # Optional for self-hosted:
   # LANGFUSE_HOST=https://your-langfuse-instance.com
   ```
4. Restart your agent - traces will appear in the Langfuse dashboard

## What Gets Traced

| Event | Captured Data |
|-------|--------------|
| Message processing | Agent name, model, user/session IDs, iterations |
| Claude API calls | Full request/response (automatic via OpenTelemetry) |
| Tool executions | Tool name, arguments, output, errors, latency |
| Token usage | Input/output tokens per turn |

## Architecture

The observability module (`agent_framework/observability/`) uses:
- **Langfuse SDK** for trace management and span creation
- **OpenTelemetry Anthropic Instrumentor** for automatic Claude call tracing
- **Graceful degradation** - agents work normally if Langfuse is not configured

## Custom Tracing

For agents that extend the base `Agent` class, pass `user_id` and `session_id` to `process_message()` for better trace filtering:

```python
response = await agent.process_message(
    user_message,
    user_id="user-123",
    session_id="conv-456",
)
```
