"""Prompts for the PR Shepherd's Claude Code workers."""

FIX_CI_INSTRUCTIONS_TEMPLATE = """\
You are fixing a CI failure on an open pull request.

## PR
Title: {title}
Branch: {branch}
Repository: {repo}

## Failing checks
{failing_checks}

## CI logs (from the failing run)
```
{logs}
```

## Instructions
- Diagnose the failure from the CI logs above.
- Fix the issue in the code. Common failures: lint errors, type errors,
  test failures, build errors.
- IMPORTANT: When you are done, you MUST stage and commit ALL your changes:
  1. `git add -A`
  2. `git commit -m "fix: <describe what you fixed>"`
  Without a commit, your work will be lost.
- Do NOT push to remote. The shepherd handles that.
- If the failure cannot be fixed (e.g. flaky infrastructure, external service
  down), explain why in your output and do not commit.
"""
