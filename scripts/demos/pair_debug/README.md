# Pair Debug Demo: Two Claude Code Sessions Fix a Broken MCP Tool

Two Claude Code CLI instances collaborate to debug a broken MCP tool, communicating in real time through mcp-relay.

**Session A (Client)** connects to a buggy MCP server and hits errors it can't explain. **Session B (Operator)** has access to the source code and diagnoses the bugs remotely. They coordinate on the `#pair-debug` mcp-relay channel.

## Prerequisites

- Two terminal windows
- Claude Code CLI in both
- mcp-relay configured in both sessions (see [mcp-relay docs](https://github.com/anthropics/mcp-relay) for setup)

## Setup

### 1. Add the buggy server to Session A's MCP config

Create or edit `.mcp.json` **in the directory where you'll launch Session A** (or use `--mcp-config`).

Replace `<AGENTS_REPO>` with the absolute path to your checkout of this repo:

```json
{
  "mcpServers": {
    "endpoint-monitor": {
      "command": "uv",
      "args": ["run", "--directory", "<AGENTS_REPO>", "python", "scripts/demos/pair_debug/demo_server.py"]
    }
  }
}
```

Session B needs no extra config — just mcp-relay and file access.

### 2. Start both sessions

**Terminal 1 (Session A):**
```bash
cd /tmp/pair-debug-demo   # or anywhere with the .mcp.json above
claude
```

**Terminal 2 (Session B):**
```bash
cd <AGENTS_REPO>
claude
```

## Role Instructions

Paste these prompts to set up each session.

### Session A — Client

```
You are debugging a buggy MCP server called "endpoint-monitor". You have three
tools: ping, server_stats, and check_endpoint(url).

Your workflow:
1. Call ping and server_stats to verify the server is running
2. Call check_endpoint("localhost:8080") — this will fail
3. Report the error to #pair-debug via mcp-relay and wait for advice
4. Follow any fix suggestions from Session B
5. Try check_endpoint("https://example.com") — the output will look wrong
6. Report the new issue to #pair-debug and wait for the final fix

Always share the exact error messages and tool output on the channel.
```

### Session B — Operator

```
You are helping Session A debug a buggy MCP server. You have access to the
source code at scripts/demos/pair_debug/demo_server.py.

Your workflow:
1. Monitor #pair-debug via mcp-relay for messages from Session A
2. When Session A reports an error, read the source code to find the bug
3. Explain the root cause and fix on #pair-debug
4. There are TWO bugs — the first causes a crash, the second causes garbled output
5. Wait for Session A to confirm each fix before moving on

The fixed reference is at scripts/demos/pair_debug/demo_server_fixed.py
(but try to diagnose from the buggy source first).
```

## Expected Debug Flow

### Phase 1 — Baseline

Session A calls `ping` and `server_stats`. Both return valid JSON.

### Phase 2 — Crash

Session A calls `check_endpoint("localhost:8080")`. It crashes:

```
AttributeError: 'NoneType' object has no attribute 'lower'
```

Session A sends the error to `#pair-debug`.

### Phase 3 — First diagnosis

Session B reads `demo_server.py`, finds the bug at the `parsed.hostname.lower()` line. `urlparse("localhost:8080")` sets `scheme="localhost"` and `hostname=None`. Session B explains the fix on `#pair-debug`: validate that the URL has an `http://` or `https://` scheme before accessing `hostname`.

### Phase 4 — Garbled output

Session A retries with `check_endpoint("https://example.com")`. No crash, but the output looks wrong:

```
{'url': 'https://example.com', 'hostname': 'example.com', 'status': 200, ...}
```

Single quotes — that's Python `str()` repr, not JSON. Session A reports this on `#pair-debug`.

### Phase 5 — Second diagnosis

Session B finds the `return str(result)` line and explains it should be `json.dumps(result)`. Both bugs are now identified.

## Message Flow

```
Session A                     #pair-debug                    Session B
   |                              |                              |
   |--- ping ✓ ------------------>|                              |
   |--- server_stats ✓ ---------->|                              |
   |                              |                              |
   |--- check_endpoint            |                              |
   |    ("localhost:8080") ✗      |                              |
   |                              |                              |
   |-------- "AttributeError:  -->|                              |
   |          NoneType...lower"   |                              |
   |                              |<-- reads demo_server.py -----|
   |                              |                              |
   |                              |<-- "urlparse treats      ----|
   |                              |     localhost as scheme,      |
   |<-----------------------------     hostname is None.          |
   |                              |     Add scheme validation."  |
   |                              |                              |
   |--- check_endpoint            |                              |
   |    ("https://example.com") ⚠ |                              |
   |                              |                              |
   |-------- "Output has       -->|                              |
   |          single quotes,      |                              |
   |          not valid JSON"     |                              |
   |                              |<-- "str(result) produces ----|
   |                              |     Python repr. Use          |
   |<-----------------------------     json.dumps(result)."      |
   |                              |                              |
   |--- Both bugs found ✓        |                    Done ✓    |
```

## Cleanup

```bash
# Clear the relay channel
# (from either session, via mcp-relay's clear_channel tool)

# Remove the MCP config you created for Session A
rm /tmp/pair-debug-demo/.mcp.json   # or wherever you placed it
```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `endpoint-monitor` tools don't appear in Session A | Check `.mcp.json` path and that `uv` is on `$PATH`. Run `/mcp` in Claude Code to verify. |
| mcp-relay messages not arriving | Both sessions must have mcp-relay configured. Check with `/mcp`. |
| Session B can't read the source | Make sure Session B is launched from the `agents` repo root. |
| Server crashes on startup | Run `uv run python scripts/demos/pair_debug/demo_server.py` directly to see the error. |

## Files

| File | Purpose |
|------|---------|
| `demo_server.py` | Buggy MCP server (the thing being debugged) |
| `demo_server_fixed.py` | Reference fix with both bugs resolved |
| `README.md` | This guide |
