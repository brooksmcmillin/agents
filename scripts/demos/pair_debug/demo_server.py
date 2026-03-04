"""Buggy endpoint monitor MCP server for the pair-debug demo.

This FastMCP stdio server has two intentional bugs in `check_endpoint`:

1. Crash: `parsed.hostname.lower()` when hostname is None (schemeless URLs)
2. Garbled output: `str(result)` produces Python repr, not valid JSON

Run via stdio (hangs waiting for input — that's correct):
    uv run python scripts/demos/pair_debug/demo_server.py
"""

import json
import time
from urllib.parse import urlparse

from mcp.server.fastmcp import FastMCP

server = FastMCP("endpoint-monitor")

# Simulated endpoint database — no real HTTP requests needed
_ENDPOINTS: dict[str, dict] = {
    "example.com": {"status": 200, "latency_ms": 42, "healthy": True},
    "api.example.com": {"status": 200, "latency_ms": 87, "healthy": True},
    "slow.example.com": {"status": 200, "latency_ms": 3200, "healthy": False},
    "broken.example.com": {"status": 503, "latency_ms": 12, "healthy": False},
}

_start_time = time.time()


@server.tool()
def ping() -> str:
    """Health check — always returns OK."""
    return json.dumps({"status": "ok", "server": "endpoint-monitor"})


@server.tool()
def server_stats() -> str:
    """Return server uptime and number of known endpoints."""
    uptime = round(time.time() - _start_time, 1)
    return json.dumps(
        {
            "uptime_seconds": uptime,
            "known_endpoints": len(_ENDPOINTS),
            "version": "0.1.0",
        }
    )


@server.tool()
def check_endpoint(url: str) -> str:
    """Check the health of a URL endpoint.

    Args:
        url: The URL to check (e.g. "https://example.com")
    """
    parsed = urlparse(url)

    # BUG 1: parsed.hostname is None for schemeless URLs
    # urlparse("localhost:8080") -> scheme="localhost", hostname=None
    # This line crashes with: AttributeError: 'NoneType' object has no attribute 'lower'
    hostname = parsed.hostname.lower()

    endpoint_data = _ENDPOINTS.get(hostname)

    if endpoint_data is None:
        result = {
            "url": url,
            "hostname": hostname,
            "status": "unknown",
            "message": f"No data for {hostname}",
        }
    else:
        result = {
            "url": url,
            "hostname": hostname,
            **endpoint_data,
        }

    # BUG 2: str() produces Python repr with single quotes — not valid JSON
    # e.g. "{'url': 'https://example.com', 'status': 200}"
    # Should be: json.dumps(result)
    return str(result)


if __name__ == "__main__":
    server.run(transport="stdio")
