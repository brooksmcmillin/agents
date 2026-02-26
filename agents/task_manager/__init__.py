"""Task Manager Agent.

An intelligent assistant that helps manage and execute tasks by connecting
to a remote MCP server with task management tools.

Features:
- Reschedule overdue tasks to realistic timeframes
- Pre-research upcoming tasks and add helpful context
- Assign relative priorities based on urgency and dependencies
- Classify tasks by action type and autonomy tier
- Execute tasks via Claude Code, email, web research, and document generation
- Safety controls with propose-then-execute for destructive actions
"""

__version__ = "0.2.0"
