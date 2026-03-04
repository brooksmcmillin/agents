# Remote Debug Demo: Claude Code Debugs a Server via remote-agent

One Claude Code session debugs a failing service on a remote server by sending shell commands through mcp-relay to a `remote-agent` process.

**Terminal 1** runs `remote-agent` on the "remote server". **Terminal 2** runs Claude Code, which investigates and fixes bugs by sending commands through the relay.

## Prerequisites

- Built `remote-agent` binary (from `remote-agent/`)
- mcp-relay configured in Claude Code
- Python 3 on the machine running remote-agent

## Setup

### 1. Build remote-agent (if not already built)

```bash
cd remote-agent && cargo build --release
```

### 2. Create the demo environment

```bash
bash scripts/demos/remote_debug/setup.sh
```

This creates `/tmp/remote-debug-demo/` with a buggy log-analyzer service, config, and sample log files.

### 3. Start remote-agent (Terminal 1)

```bash
./remote-agent/target/release/remote-agent --name demo-server
```

It will print:
```
remote-agent 'demo-server'
  commands: demo-server-commands
  output:   demo-server-output
```

### 4. Start Claude Code (Terminal 2)

```bash
claude
```

## Debugging Prompt

Paste this into Claude Code:

```
A log-analyzer service on the remote server "demo-server" is failing. The service
is at /tmp/remote-debug-demo/service.py and should be run with:

    python3 /tmp/remote-debug-demo/service.py /tmp/remote-debug-demo/config.json

Use mcp-relay to send shell commands and read output:
- Send commands to the "demo-server-commands" channel
- Read results from the "demo-server-output" channel

Your workflow:
1. Run the service to see the error
2. Investigate the crash (read source, check the file paths, examine config)
3. Fix the bug using sed or similar
4. Re-run — the output will be wrong (all zeros). There's a second bug.
5. Compare the log files against the reported counts to understand the issue
6. Fix the second bug and verify correct output

The log files have 5 ERRORs, 3 WARNs, and 9 INFOs across two files.
```

## Expected Debug Flow

### Phase 1 — Run and crash

Claude sends `python3 /tmp/remote-debug-demo/service.py /tmp/remote-debug-demo/config.json` to the commands channel.

Output shows a traceback:

```
FileNotFoundError: [Errno 2] No such file or directory:
  '/tmp/remote-debug-demo/logsapp-2024-01-15.log'
```

### Phase 2 — First diagnosis

Claude reads the source code and config. The config has `"log_dir": "/tmp/remote-debug-demo/logs"` (no trailing slash). The script joins paths with `filepath = log_dir + filename` — string concatenation produces `/tmp/remote-debug-demo/logsapp-...` instead of `/tmp/remote-debug-demo/logs/app-...`.

Fix: replace `log_dir + filename` with `os.path.join(log_dir, filename)`.

### Phase 3 — Wrong output

Claude re-runs. No crash, but the report shows all zeros:

```
  Errors:   0
  Warnings: 0
  Info:     0
```

### Phase 4 — Second diagnosis

Claude checks the log files (`grep ERROR /tmp/remote-debug-demo/logs/*.log`) and sees plenty of ERROR lines. The script uses `re.match(r"ERROR", line)` — but `re.match` only checks the **start** of the string. Log lines start with timestamps (`2024-01-15 08:05:31 ERROR ...`), so `re.match` never matches.

Fix: change `re.match` to `re.search` (three occurrences: ERROR, WARN, INFO).

### Phase 5 — Verify

Claude re-runs. Output now shows the correct counts:

```
  Errors:   5
  Warnings: 3
  Info:     9
```

## Message Flow

```
Claude Code                  mcp-relay                    remote-agent
   |                            |                              |
   |-- send_message ----------->|                              |
   |   "python3 service.py .."  |--- demo-server-commands ---->|
   |                            |                              |-- execute
   |                            |<--- demo-server-output ------|
   |<-- read_messages ----------|   "FileNotFoundError:        |
   |                            |    .../logsapp-2024..."      |
   |                            |                              |
   |-- send_message ----------->|                              |
   |   "cat service.py"         |--- demo-server-commands ---->|
   |                            |                              |
   |                            |<--- demo-server-output ------|
   |<-- read_messages ----------|   [source code]              |
   |                            |                              |
   |-- send_message ----------->|                              |
   |   "sed -i ... service.py"  |--- demo-server-commands ---->|
   |                            |                              |
   |-- send_message ----------->|                              |
   |   "python3 service.py .."  |--- demo-server-commands ---->|
   |                            |                              |
   |                            |<--- demo-server-output ------|
   |<-- read_messages ----------|   "Errors: 0, Warnings: 0"  |
   |                            |                              |
   |-- send_message ----------->|                              |
   |   "grep ERROR logs/*.log"  |--- demo-server-commands ---->|
   |                            |                              |
   |                            |<--- demo-server-output ------|
   |<-- read_messages ----------|   [matching ERROR lines]     |
   |                            |                              |
   |-- send_message ----------->|                              |
   |   "sed -i 's/match/search  |--- demo-server-commands ---->|
   |         /g' service.py"    |                              |
   |                            |                              |
   |-- send_message ----------->|                              |
   |   "python3 service.py .."  |--- demo-server-commands ---->|
   |                            |                              |
   |                            |<--- demo-server-output ------|
   |<-- read_messages ----------|   "Errors: 5, Warnings: 3"  |
   |                            |                              |
   |--- Both bugs fixed ✓      |                    Done ✓    |
```

## Cleanup

```bash
rm -rf /tmp/remote-debug-demo

# Clear the relay channels (from Claude Code via mcp-relay)
# clear_channel("demo-server-commands")
# clear_channel("demo-server-output")
```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| remote-agent won't start | Check `cargo build --release` succeeded. Run with `RUST_LOG=debug` for more output. |
| OAuth device flow prompt | Follow the URL printed to authorize. Token is cached after first use. |
| Claude can't find relay tools | Verify mcp-relay is configured. Run `/mcp` in Claude Code to check. |
| Messages not arriving | Both sides must use the same relay URL. Check channel names match exactly. |
| remote-agent shows 401 errors | Token may be expired. Delete `~/.remote-agent/token.json` and restart to re-auth. |

## Files

| File | Purpose |
|------|---------|
| `demo_service.py` | Buggy log analyzer (deployed by setup.sh) |
| `demo_service_fixed.py` | Reference fix with both bugs resolved |
| `setup.sh` | Creates the demo environment at `/tmp/remote-debug-demo/` |
| `README.md` | This guide |
