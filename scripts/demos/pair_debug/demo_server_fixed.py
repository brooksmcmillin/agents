"""Fixed endpoint monitor MCP server — reference solution for the pair-debug demo.

Both bugs from demo_server.py are fixed:
1. Validate URL scheme before accessing hostname
2. Use json.dumps() instead of str() for output
"""

import json
import time
from urllib.parse import urlparse

from mcp.server.fastmcp import FastMCP

server = FastMCP("endpoint-monitor")

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

    # FIX 1: Validate URL has a real scheme and hostname
    # urlparse("localhost:8080") sets scheme="localhost", hostname=None
    if parsed.scheme not in ("http", "https") or parsed.hostname is None:
        return json.dumps(
            {
                "url": url,
                "error": "Invalid URL: must start with http:// or https://",
            }
        )

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

    # FIX 2: json.dumps() produces valid JSON
    return json.dumps(result)


if __name__ == "__main__":
    server.run(transport="stdio")
