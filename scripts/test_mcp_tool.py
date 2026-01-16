#!/usr/bin/env python3
"""Direct MCP tool testing script.

This script allows you to call MCP tools directly without going through
the full agent pipeline, useful for debugging.

Usage:
    # List available tools
    uv run python scripts/test_mcp_tool.py --list

    # Call a tool with arguments
    uv run python scripts/test_mcp_tool.py get_memories --args '{"limit": 10}'

    # Call a tool with no arguments
    uv run python scripts/test_mcp_tool.py get_memory_stats

    # Pretty print the output
    uv run python scripts/test_mcp_tool.py get_memories --pretty
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from agent_framework.core.mcp_client import create_mcp_client

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def list_tools(mcp_server_path: str) -> None:
    """List all available MCP tools."""
    print("🔧 Connecting to MCP server...")

    async with create_mcp_client(mcp_server_path) as mcp_client:
        # Get tools from the client's available_tools dict
        tools = list(mcp_client.available_tools.values())
        print(f"\n✅ Connected! Found {len(tools)} tools:\n")

        for tool in tools:
            print(f"  📌 {tool.name}")
            if tool.description:
                # Indent description
                desc_lines = tool.description.strip().split("\n")
                for line in desc_lines:
                    print(f"     {line}")

            # Show input schema if available
            if hasattr(tool, "inputSchema") and tool.inputSchema:
                schema = tool.inputSchema
                if "properties" in schema:
                    print("     Parameters:")
                    for param, details in schema["properties"].items():
                        param_type = details.get("type", "any")
                        required = param in schema.get("required", [])
                        req_marker = " (required)" if required else ""
                        print(f"       - {param}: {param_type}{req_marker}")
            print()


async def call_tool(
    mcp_server_path: str,
    tool_name: str,
    args: dict[str, any],
    pretty: bool = False,
) -> None:
    """Call an MCP tool with the given arguments."""
    print(f"🔧 Connecting to MCP server...")

    async with create_mcp_client(mcp_server_path) as mcp_client:
        # Check if tool exists
        tool_names = list(mcp_client.available_tools.keys())
        if tool_name not in tool_names:
            print(f"\n❌ Tool '{tool_name}' not found!")
            print(f"Available tools: {', '.join(tool_names)}")
            return

        print(f"🔧 Calling tool: {tool_name}")
        if args:
            print(f"📝 Arguments: {json.dumps(args, indent=2)}")

        try:
            result = await mcp_client.call_tool(tool_name, args)

            print("\n✅ Tool executed successfully!\n")
            print("📊 Result:")
            print("-" * 80)

            if pretty:
                # Pretty print JSON if possible
                try:
                    if hasattr(result, "content"):
                        # Handle MCP response objects
                        content = result.content
                        if isinstance(content, list) and len(content) > 0:
                            for item in content:
                                if hasattr(item, "text"):
                                    try:
                                        parsed = json.loads(item.text)
                                        print(json.dumps(parsed, indent=2))
                                    except json.JSONDecodeError:
                                        print(item.text)
                                else:
                                    print(item)
                        else:
                            print(content)
                    else:
                        print(json.dumps(result, indent=2, default=str))
                except Exception:
                    print(result)
            else:
                print(result)

            print("-" * 80)

        except Exception as e:
            print(f"\n❌ Tool execution failed: {e}")
            import traceback
            traceback.print_exc()


def main():
    # Change to project root directory so MCP server can be found
    # The MCP server needs to be run as a module from the project root
    project_root = Path(__file__).parent.parent
    import os
    os.chdir(project_root)

    parser = argparse.ArgumentParser(
        description="Test MCP tools directly",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # List all available tools
    uv run python scripts/test_mcp_tool.py --list

    # Call get_memories with default limit
    uv run python scripts/test_mcp_tool.py get_memories

    # Call get_memories with specific limit
    uv run python scripts/test_mcp_tool.py get_memories --args '{"limit": 5}'

    # Search memories
    uv run python scripts/test_mcp_tool.py search_memories --args '{"query": "user"}'

    # Fetch web content
    uv run python scripts/test_mcp_tool.py fetch_web_content --args '{"url": "https://example.com"}'

    # Pretty print output
    uv run python scripts/test_mcp_tool.py get_memories --pretty
""",
    )

    parser.add_argument(
        "tool",
        nargs="?",
        help="Name of the tool to call",
    )
    parser.add_argument(
        "--args",
        "-a",
        type=str,
        default="{}",
        help="JSON string of arguments to pass to the tool",
    )
    parser.add_argument(
        "--list",
        "-l",
        action="store_true",
        help="List all available tools",
    )
    parser.add_argument(
        "--pretty",
        "-p",
        action="store_true",
        help="Pretty print JSON output",
    )
    parser.add_argument(
        "--server",
        "-s",
        type=str,
        default=None,
        help="Relative path to MCP server script (default: mcp_server/server.py)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Determine MCP server path
    # The MCP client expects a relative path that it converts to a module name
    # e.g., "mcp_server/server.py" -> "mcp_server.server" for python -m
    if args.server:
        mcp_server_path = args.server
    else:
        # Default to local MCP server (relative path)
        mcp_server_path = "mcp_server/server.py"

    # Validate the server module exists
    # Convert path to module name for validation
    module_path = mcp_server_path.replace("/", ".").replace(".py", "")
    module_file = Path(project_root) / mcp_server_path

    if not module_file.exists():
        print(f"❌ MCP server not found at: {module_file}")
        print(f"   (Looking for module: {module_path})")
        print("Specify path with --server flag (use relative path like 'mcp_server/server.py')")
        sys.exit(1)

    print(f"📂 Using MCP server module: {module_path}")
    print(f"   (File: {module_file})\n")

    # List tools or call tool
    if args.list:
        asyncio.run(list_tools(mcp_server_path))
    elif args.tool:
        try:
            tool_args = json.loads(args.args)
        except json.JSONDecodeError as e:
            print(f"❌ Invalid JSON in --args: {e}")
            print(f"Received: {args.args}")
            sys.exit(1)

        asyncio.run(call_tool(mcp_server_path, args.tool, tool_args, args.pretty))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
