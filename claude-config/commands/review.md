# Full Codebase Review

Run all 5 review agents **in parallel** using the Task tool:

1. **code-optimizer** - Analyze code for maintainability, duplication, and complexity
2. **security-code-reviewer** - Scan for vulnerabilities and insecure patterns
3. **doc-auditor** - Check documentation for staleness and gaps
4. **dependency-auditor** - Audit dependencies for CVEs and license issues
5. **test-coverage-checker** - Identify untested code paths

Launch all 5 agents simultaneously in a single message with 5 Task tool calls. Each agent should analyze the current working directory.

After all agents complete, provide a consolidated summary with:
- Critical issues requiring immediate attention
- High-priority recommendations
- Lower-priority suggestions for future improvement
