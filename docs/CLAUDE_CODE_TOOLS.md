# Claude Code Automation Tools

These MCP tools allow agents to spawn and manage headless Claude Code instances for meta-programming and code delegation tasks.

## Overview

The Claude Code tools enable agents to:
- Create isolated workspace directories
- Clone git repositories into workspaces
- Run headless Claude Code instances with specific commands
- Manage workspace lifecycle (create, delete, status)
- List available workspaces

## Environment Setup

### Workspace Directory

By default, workspaces are stored in `~/.claude_code_workspaces/`. You can customize this by setting the environment variable:

```bash
export CLAUDE_CODE_WORKSPACES_DIR="/path/to/your/workspaces"
```

### Prerequisites

- Claude Code CLI must be installed and available in PATH
- Git must be installed (for workspace management)

## Tools

### 1. `run_claude_code`

Run a headless Claude Code instance in a workspace.

**Parameters:**
- `folder_name` (required): Name of workspace folder
- `command` (required): Command/message to send to Claude Code
- `timeout` (optional): Maximum seconds to wait (default: 300)
- `max_turns` (optional): Maximum agentic turns (default: 10)
- `model` (optional): Claude model - "sonnet", "haiku", or "opus" (default: "sonnet")
- `working_dir_base` (optional): Custom workspace base directory
- `custom_instructions` (optional): Additional instructions to prepend

**Returns:**
```json
{
  "success": true,
  "output": "full conversation output",
  "final_response": "last response from Claude",
  "turns_used": 5,
  "workspace_path": "/path/to/workspace",
  "command": "the command executed",
  "exit_code": 0
}
```

**Example:**
```python
result = await run_claude_code(
    folder_name="my_project",
    command="Add type hints to all functions in utils.py",
    timeout=600,
    max_turns=15,
    model="sonnet"
)
```

### 2. `list_claude_code_workspaces`

List all available workspace folders.

**Parameters:**
- `working_dir_base` (optional): Custom workspace base directory

**Returns:**
```json
{
  "workspaces": [
    {
      "name": "project1",
      "path": "/home/user/.claude_code_workspaces/project1",
      "is_git_repo": true,
      "size_mb": 15.23
    }
  ],
  "base_dir": "/home/user/.claude_code_workspaces",
  "count": 1
}
```

### 3. `create_claude_code_workspace`

Create a new workspace folder, optionally cloning a git repository.

**Parameters:**
- `folder_name` (required): Name for the new workspace
- `git_repo_url` (optional): Git repository URL to clone
- `working_dir_base` (optional): Custom workspace base directory

**Returns:**
```json
{
  "success": true,
  "workspace_path": "/path/to/new/workspace",
  "is_git_repo": true,
  "message": "Workspace created successfully"
}
```

**Example:**
```python
# Create empty workspace
result = await create_claude_code_workspace(
    folder_name="new_project"
)

# Create workspace from git repo
result = await create_claude_code_workspace(
    folder_name="existing_project",
    git_repo_url="https://github.com/user/repo.git"
)
```

### 4. `delete_claude_code_workspace`

Delete a workspace folder.

**Parameters:**
- `folder_name` (required): Name of workspace to delete
- `working_dir_base` (optional): Custom workspace base directory
- `force` (optional): Force deletion even with uncommitted changes (default: false)

**Returns:**
```json
{
  "success": true,
  "workspace_path": "/path/to/deleted/workspace",
  "message": "Workspace deleted successfully",
  "had_uncommitted_changes": false
}
```

**Safety:** By default, refuses to delete workspaces with uncommitted git changes unless `force=true`.

### 5. `get_claude_code_workspace_status`

Get detailed status of a workspace.

**Parameters:**
- `folder_name` (required): Name of workspace
- `working_dir_base` (optional): Custom workspace base directory

**Returns:**
```json
{
  "workspace_path": "/path/to/workspace",
  "is_git_repo": true,
  "git_status": "M file.py\n?? new_file.txt",
  "has_uncommitted_changes": true,
  "current_branch": "main",
  "file_count": 42,
  "size_mb": 3.14
}
```

## Use Cases

### 1. Code Review and Refactoring

```python
# Create workspace from repo
await create_claude_code_workspace(
    folder_name="review_project",
    git_repo_url="https://github.com/user/project.git"
)

# Run Claude Code to refactor
result = await run_claude_code(
    folder_name="review_project",
    command="Refactor all database queries to use async/await",
    timeout=900,
    model="sonnet"
)

# Check what changed
status = await get_claude_code_workspace_status("review_project")
print(status['git_status'])
```

### 2. Multi-Project Analysis

```python
# List all workspaces
workspaces = await list_claude_code_workspaces()

# Run analysis on each
for ws in workspaces['workspaces']:
    result = await run_claude_code(
        folder_name=ws['name'],
        command="Generate a security audit report",
        model="sonnet"
    )
    print(f"{ws['name']}: {result['final_response']}")
```

### 3. Automated Testing

```python
# Create test workspace
await create_claude_code_workspace(
    folder_name="test_suite",
    git_repo_url="https://github.com/user/app.git"
)

# Run tests
result = await run_claude_code(
    folder_name="test_suite",
    command="Run all tests and fix any failures",
    max_turns=20,
    timeout=1200
)

# Check if tests passed
if "All tests passed" in result['output']:
    print("Success!")
```

### 4. Batch Processing

```python
# Create workspaces for multiple repos
repos = [
    ("app1", "https://github.com/org/app1.git"),
    ("app2", "https://github.com/org/app2.git"),
]

for name, url in repos:
    await create_claude_code_workspace(folder_name=name, git_repo_url=url)

    # Apply same change to all
    await run_claude_code(
        folder_name=name,
        command="Update all dependencies to latest versions",
        custom_instructions="Use caution with major version upgrades"
    )
```

## Security Considerations

### Path Traversal Prevention

Folder names are validated to prevent path traversal attacks:
- Must start with alphanumeric character
- Can only contain alphanumeric, hyphens, underscores, and dots
- Cannot contain `..`, `/`, or `\`

### Workspace Isolation

Each workspace is isolated in its own directory. Claude Code instances run with the workspace as their working directory and cannot access files outside the workspace.

### Git Safety

- Uncommitted changes are detected before deletion
- Force flag required to delete workspaces with uncommitted changes

## Best Practices

### 1. Use Descriptive Workspace Names

```python
# Good
create_claude_code_workspace("refactor_auth_module")
create_claude_code_workspace("security_audit_2024")

# Avoid
create_claude_code_workspace("temp")
create_claude_code_workspace("test123")
```

### 2. Set Appropriate Timeouts

```python
# Simple tasks
run_claude_code(command="Fix typo in README", timeout=60)

# Complex refactoring
run_claude_code(command="Refactor entire module", timeout=1800)
```

### 3. Check Status Before Deletion

```python
# Always check status first
status = await get_claude_code_workspace_status("my_workspace")
if status['has_uncommitted_changes']:
    print(f"Uncommitted changes: {status['git_status']}")
    # Decide whether to force delete or save changes
```

### 4. Clean Up After Use

```python
# Delete temporary workspaces when done
result = await run_claude_code(...)
if result['success']:
    await delete_claude_code_workspace(folder_name="temp_workspace", force=True)
```

## Troubleshooting

### "Claude Code CLI not found"

Install Claude Code CLI:
```bash
npm install -g @anthropics/claude-code
```

### "Workspace not found"

List available workspaces:
```python
workspaces = await list_claude_code_workspaces()
print(workspaces['workspaces'])
```

### Timeout Errors

Increase timeout for complex tasks:
```python
result = await run_claude_code(
    command="...",
    timeout=1800,  # 30 minutes
    max_turns=30
)
```

### Git Clone Failures

Check that:
- Repository URL is correct
- You have access (SSH keys or credentials)
- Network connectivity is working

## Advanced Usage

### Custom Workspace Directory

```python
# Use different base directory for different projects
result = await run_claude_code(
    folder_name="project",
    command="...",
    working_dir_base="/mnt/projects/claude_workspaces"
)
```

### Streaming Output (Future Enhancement)

Currently, output is returned after completion. Future versions may support streaming output for long-running tasks.

### Session Management (Future Enhancement)

Currently, each `run_claude_code` call creates a new session. Future versions may support persistent sessions across multiple commands.

## Integration with Other Tools

### Combined with RAG

```python
# Add codebase to RAG knowledge base
await add_document(
    content=result['output'],
    title=f"Claude Code Analysis: {folder_name}",
    category="code_analysis"
)
```

### Combined with Memory

```python
# Save important findings
await save_memory(
    key=f"refactoring_{folder_name}",
    value=result['final_response'],
    category="code_changes",
    importance=8
)
```

### Combined with Slack

```python
# Notify team of completion
await send_slack_message(
    message=f"Claude Code completed refactoring in {folder_name}:\n{result['final_response']}"
)
```

## Tool Count Update

With the addition of Claude Code tools, the system now has **34 MCP tools** across 9 categories:

1. Web Analysis (2 tools)
2. Memory (6 tools)
3. RAG Document Search (6 tools)
4. FastMail Email (8 tools)
5. Communication (1 tool)
6. Social Media (1 tool)
7. Content Suggestions (1 tool)
8. **Claude Code Automation (5 tools)** ← NEW
9. Time/System (4 tools via taskmanager MCP)
