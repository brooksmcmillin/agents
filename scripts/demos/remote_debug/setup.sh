#!/usr/bin/env bash
# Set up the remote-debug demo environment.
#
# Creates /tmp/remote-debug-demo/ with a buggy service, config, and sample logs.
# Run from the agents repo root:
#   bash scripts/demos/remote_debug/setup.sh

set -euo pipefail

DEMO_DIR="/tmp/remote-debug-demo"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Creating demo environment at ${DEMO_DIR}..."

rm -rf "${DEMO_DIR}"
mkdir -p "${DEMO_DIR}/logs" "${DEMO_DIR}/output"

# Copy the buggy service
cp "${SCRIPT_DIR}/demo_service.py" "${DEMO_DIR}/service.py"

# Create config (note: log_dir has NO trailing slash — this matters for bug 1)
cat > "${DEMO_DIR}/config.json" << 'EOF'
{
  "log_dir": "/tmp/remote-debug-demo/logs",
  "output_dir": "/tmp/remote-debug-demo/output"
}
EOF

# Create sample log files with realistic timestamps and mixed severity levels
# app-2024-01-15.log: 3 ERROR, 2 WARN, 5 INFO, 2 DEBUG = 12 lines
cat > "${DEMO_DIR}/logs/app-2024-01-15.log" << 'EOF'
2024-01-15 08:00:01 INFO  Application started on port 8080
2024-01-15 08:00:02 INFO  Connected to database (pool_size=5)
2024-01-15 08:01:15 INFO  Health check passed
2024-01-15 08:05:30 WARN  Connection pool nearly exhausted (4/5 in use)
2024-01-15 08:05:31 ERROR Failed to acquire connection: pool timeout after 30s
2024-01-15 08:05:32 ERROR Retry 1/3 failed: connection refused
2024-01-15 08:05:45 INFO  Connection pool recovered
2024-01-15 08:10:00 DEBUG Request processed in 142ms (path=/api/users)
2024-01-15 08:15:22 WARN  Slow query detected: SELECT * FROM orders took 2100ms
2024-01-15 08:20:00 INFO  Scheduled cleanup: removed 47 expired sessions
2024-01-15 08:30:05 ERROR Unhandled exception in worker-3: ValueError('invalid literal')
2024-01-15 08:30:06 DEBUG Worker-3 restarted successfully
EOF

# app-2024-01-16.log: 2 ERROR, 1 WARN, 4 INFO, 1 DEBUG = 8 lines
cat > "${DEMO_DIR}/logs/app-2024-01-16.log" << 'EOF'
2024-01-16 08:00:01 INFO  Application started on port 8080
2024-01-16 08:00:02 INFO  Connected to database (pool_size=5)
2024-01-16 08:03:10 ERROR TLS handshake failed: certificate expired for upstream.internal
2024-01-16 08:03:11 WARN  Falling back to HTTP for upstream.internal
2024-01-16 08:03:12 INFO  Upstream connection established (insecure)
2024-01-16 08:10:00 DEBUG Cache hit ratio: 73.2% (last 5 minutes)
2024-01-16 08:25:44 ERROR OOM kill: worker-2 exceeded 512MB limit
2024-01-16 08:25:45 INFO  Worker-2 respawned with increased limit (768MB)
EOF

echo ""
echo "Demo environment ready:"
echo "  Service:  ${DEMO_DIR}/service.py"
echo "  Config:   ${DEMO_DIR}/config.json"
echo "  Logs:     ${DEMO_DIR}/logs/ (2 files, 20 lines)"
echo "  Output:   ${DEMO_DIR}/output/"
echo ""
echo "Expected totals after both bugs are fixed:"
echo "  Errors:   5"
echo "  Warnings: 3"
echo "  Info:     9"
echo ""
echo "Next: start remote-agent, then debug from Claude Code."
echo "  See scripts/demos/remote_debug/README.md for instructions."
