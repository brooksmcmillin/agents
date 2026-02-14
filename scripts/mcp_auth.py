#!/usr/bin/env python3
"""Authenticate with the remote MCP server and store the token.

Opens a browser for OAuth login. Once complete, the token is saved to
~/.agents/tokens/ and can be used by batch scripts like run-task-queue.

Usage:
    uv run python scripts/mcp_auth.py                              # Default server
    uv run python scripts/mcp_auth.py --mcp-url https://example.com/mcp
    uv run python scripts/mcp_auth.py --device                     # Headless/SSH
"""

import argparse
import asyncio
import os
import sys

# Remove scripts/ from sys.path — scripts/mcp/ shadows the real mcp package.
_scripts_dir = os.path.dirname(os.path.abspath(__file__))
sys.path = [p for p in sys.path if os.path.abspath(p) != _scripts_dir]

from agent_framework.core.remote_mcp_client import RemoteMCPClient  # noqa: E402

DEFAULT_MCP_SERVER_URL = "https://mcp.brooksmcmillin.com/mcp"
ENV_MCP_SERVER_URL = "MCP_SERVER_URL"


async def authenticate(mcp_url: str, device_flow: bool = False) -> None:
    """Run OAuth flow against the MCP server and persist the token."""
    print(f"MCP server: {mcp_url}")
    print()

    client = RemoteMCPClient(
        mcp_url,
        enable_oauth=True,
        prefer_device_flow=device_flow,
    )

    try:
        async with client:
            tools = await client.list_tools()
            print(f"Authenticated successfully. {len(tools)} tools available.")
    except Exception as e:
        print(f"Authentication failed: {e}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Authenticate with the remote MCP server.")
    parser.add_argument(
        "--mcp-url",
        default=os.getenv(ENV_MCP_SERVER_URL, DEFAULT_MCP_SERVER_URL),
        help="MCP server URL (default: from env or built-in default)",
    )
    parser.add_argument(
        "--device",
        action="store_true",
        help="Use device flow (for headless/SSH environments)",
    )
    args = parser.parse_args()
    asyncio.run(authenticate(args.mcp_url, device_flow=args.device))


if __name__ == "__main__":
    main()
