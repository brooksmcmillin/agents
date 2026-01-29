#!/usr/bin/env python3
"""Test script for Claude Code automation tools.

This script demonstrates and tests the Claude Code MCP tools:
- create_claude_code_workspace
- list_claude_code_workspaces
- get_claude_code_workspace_status
- run_claude_code
- delete_claude_code_workspace
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from agent_framework.tools.claude_code import (
    create_claude_code_workspace,
    delete_claude_code_workspace,
    get_claude_code_workspace_status,
    list_claude_code_workspaces,
    run_claude_code,
)


async def test_list_workspaces():
    """Test listing workspaces."""
    print("\n=== Testing list_claude_code_workspaces ===")
    result = await list_claude_code_workspaces()
    print(f"Base directory: {result['base_dir']}")
    print(f"Workspace count: {result['count']}")
    for ws in result["workspaces"]:
        print(f"  - {ws['name']}: {ws['size_mb']} MB (git: {ws['is_git_repo']})")
    return result


async def test_create_workspace(folder_name: str, git_repo_url: str | None = None):
    """Test creating a workspace."""
    print(f"\n=== Testing create_claude_code_workspace: {folder_name} ===")
    result = await create_claude_code_workspace(folder_name=folder_name, git_repo_url=git_repo_url)
    print(f"Success: {result['success']}")
    print(f"Path: {result['workspace_path']}")
    print(f"Git repo: {result['is_git_repo']}")
    print(f"Message: {result['message']}")
    return result


async def test_workspace_status(folder_name: str):
    """Test getting workspace status."""
    print(f"\n=== Testing get_claude_code_workspace_status: {folder_name} ===")
    result = await get_claude_code_workspace_status(folder_name=folder_name)
    print(f"Path: {result['workspace_path']}")
    print(f"Git repo: {result['is_git_repo']}")
    print(f"Branch: {result['current_branch']}")
    print(f"Files: {result['file_count']}")
    print(f"Size: {result['size_mb']} MB")
    print(f"Uncommitted changes: {result['has_uncommitted_changes']}")
    if result["git_status"]:
        print(f"Git status:\n{result['git_status']}")
    return result


async def test_run_claude_code(
    folder_name: str, command: str, timeout: int = 300, model: str = "sonnet"
):
    """Test running Claude Code in a workspace."""
    print(f"\n=== Testing run_claude_code: {folder_name} ===")
    print(f"Command: {command}")
    print(f"Timeout: {timeout}s, Model: {model}")
    result = await run_claude_code(
        folder_name=folder_name, command=command, timeout=timeout, model=model
    )
    print(f"Success: {result['success']}")
    print(f"Exit code: {result['exit_code']}")
    print(f"Turns used: {result['turns_used']}")
    print(f"Final response: {result['final_response'][:200]}...")
    if result.get("error"):
        print(f"Error: {result['error']}")
    return result


async def test_delete_workspace(folder_name: str, force: bool = False):
    """Test deleting a workspace."""
    print(f"\n=== Testing delete_claude_code_workspace: {folder_name} ===")
    result = await delete_claude_code_workspace(folder_name=folder_name, force=force)
    print(f"Success: {result['success']}")
    print(f"Message: {result['message']}")
    if result.get("error"):
        print(f"Error: {result['error']}")
    return result


async def run_basic_tests():
    """Run basic test suite."""
    print("=" * 60)
    print("Claude Code Tools - Basic Test Suite")
    print("=" * 60)

    # List existing workspaces
    await test_list_workspaces()

    # Create a test workspace
    test_ws_name = "test_workspace_basic"
    create_result = await test_create_workspace(test_ws_name)

    if create_result["success"]:
        # Get status
        await test_workspace_status(test_ws_name)

        # Run a simple command (NOTE: This will fail if claude CLI is not installed)
        try:
            await test_run_claude_code(
                folder_name=test_ws_name,
                command="List all files in the current directory",
                timeout=60,
            )
        except Exception as e:
            print(f"Note: Claude Code execution failed (expected if CLI not installed): {e}")

        # Delete workspace
        await test_delete_workspace(test_ws_name, force=True)

    # List workspaces again
    await test_list_workspaces()

    print("\n" + "=" * 60)
    print("Basic tests completed!")
    print("=" * 60)


async def run_git_tests():
    """Run tests with git repository."""
    print("=" * 60)
    print("Claude Code Tools - Git Repository Test")
    print("=" * 60)

    test_ws_name = "test_workspace_git"

    # Create workspace from a small public repo
    create_result = await test_create_workspace(
        folder_name=test_ws_name,
        git_repo_url="https://github.com/octocat/Hello-World.git",
    )

    if create_result["success"]:
        # Get status
        await test_workspace_status(test_ws_name)

        # Delete workspace
        await test_delete_workspace(test_ws_name, force=True)

    print("\n" + "=" * 60)
    print("Git tests completed!")
    print("=" * 60)


async def main():
    """Main test runner."""
    if len(sys.argv) > 1:
        test_type = sys.argv[1]
        if test_type == "basic":
            await run_basic_tests()
        elif test_type == "git":
            await run_git_tests()
        elif test_type == "list":
            await test_list_workspaces()
        else:
            print(f"Unknown test type: {test_type}")
            print("Usage: python test_claude_code_tools.py [basic|git|list]")
    else:
        # Run all tests
        await run_basic_tests()
        await run_git_tests()


if __name__ == "__main__":
    asyncio.run(main())
