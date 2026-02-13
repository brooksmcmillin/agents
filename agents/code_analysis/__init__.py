"""Code Analysis Agent.

An expert agent that critically examines repositories and suggests
actionable improvements across security, logic, performance, architecture,
and reliability. Connects to a remote MCP server to create tracked tasks
for significant findings.

Features:
- Security vulnerability detection (OWASP Top 10, CWE patterns)
- Logic and correctness analysis (race conditions, edge cases)
- Performance and efficiency review (complexity, I/O, memory)
- Architecture and design evaluation (SOLID, coupling, patterns)
- Reliability assessment (error handling, monitoring, tests)
- Automatic task creation for trackable remediation
"""

__version__ = "0.1.0"
