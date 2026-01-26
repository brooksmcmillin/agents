#!/usr/bin/env python3
"""Test memory tools directly without MCP overhead.

Usage:
    # Get all memories
    uv run python scripts/test_memory.py get

    # Search memories
    uv run python scripts/test_memory.py search "user"

    # Save a memory
    uv run python scripts/test_memory.py save test_key "test value" --category fact --importance 7

    # Get memory stats
    uv run python scripts/test_memory.py stats
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Ensure we're in the project root
project_root = Path(__file__).parent.parent
import os

os.chdir(project_root)

from agent_framework.tools.memory import (
    get_memories,
    save_memory,
    search_memories,
    get_memory_stats,
    delete_memory,
)


async def main():
    parser = argparse.ArgumentParser(
        description="Test memory tools directly",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Get memories
    get_parser = subparsers.add_parser("get", help="Get all memories")
    get_parser.add_argument("--category", help="Filter by category")
    get_parser.add_argument("--min-importance", type=int, help="Min importance level")
    get_parser.add_argument("--limit", type=int, default=20, help="Max results")

    # Search memories
    search_parser = subparsers.add_parser("search", help="Search memories")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument("--limit", type=int, default=10, help="Max results")

    # Save memory
    save_parser = subparsers.add_parser("save", help="Save a memory")
    save_parser.add_argument("key", help="Memory key")
    save_parser.add_argument("value", help="Memory value")
    save_parser.add_argument("--category", help="Category")
    save_parser.add_argument("--tags", nargs="+", help="Tags")
    save_parser.add_argument(
        "--importance", type=int, default=5, help="Importance (1-10)"
    )

    # Delete memory
    delete_parser = subparsers.add_parser("delete", help="Delete a memory")
    delete_parser.add_argument("key", help="Memory key to delete")

    # Stats
    subparsers.add_parser("stats", help="Get memory statistics")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    try:
        if args.command == "get":
            result = await get_memories(
                category=args.category,
                min_importance=args.min_importance,
                limit=args.limit,
            )
        elif args.command == "search":
            result = await search_memories(query=args.query, limit=args.limit)
        elif args.command == "save":
            result = await save_memory(
                key=args.key,
                value=args.value,
                category=args.category,
                tags=args.tags,
                importance=args.importance,
            )
        elif args.command == "delete":
            result = await delete_memory(key=args.key)
        elif args.command == "stats":
            result = await get_memory_stats()
        else:
            parser.print_help()
            return

        print(json.dumps(result, indent=2, default=str))

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
