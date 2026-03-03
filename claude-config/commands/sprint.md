---
description: Pull tasks from TaskManager and implement them in parallel worktrees
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Task, ToolSearch, mcp__taskmanager__*
---

# Sprint: Parallel Task Implementation

You are about to pull tasks from the TaskManager MCP server and implement each one in an isolated git worktree with a sub-agent.

## 1. Fetch tasks

Use the TaskManager MCP tools to find tasks matching the user's criteria:

**User's query:** $ARGUMENTS

Interpret the query to determine how to fetch tasks:
- "tagged X" or "tag X" → use `search_tasks` filtering by tag
- "category X" → use `search_tasks` or `get_tasks` filtering by category
- "priority X" → filter by priority level
- "task IDs X, Y, Z" → use `get_task` for each specific ID
- "due this week" → filter by due date within the current week
- Combine filters as needed (e.g., "category blog with priority high" → filter by both)

Load the TaskManager tools with `ToolSearch` first, then fetch the matching tasks.

If no tasks match, stop and tell me.

## 2. Triage and model selection

For each task, quickly assess:
- **Skip** if the description is too vague or the scope is too large for automated implementation. Flag these for manual review.
- **Proceed** if the task has a clear, implementable description.

For each task you'll proceed with, choose a model for the sub-agent based on complexity:
- **haiku** — trivial tasks: typo fixes, config changes, simple one-file edits, documentation updates
- **sonnet** — moderate tasks: single-feature implementation, bug fixes with clear reproduction, tests, straightforward refactors
- **opus** — complex tasks: multi-file architectural changes, ambiguous requirements needing judgment, tasks requiring deep codebase understanding or careful design decisions

Show me the list of tasks you found, which ones you'll attempt, which you're skipping (with reasons), and the model you've chosen for each (with a brief justification). Then proceed without waiting.

## 3. Set up worktrees and spawn sub-agents

For each task you're proceeding with:

1. Slugify the task title (lowercase, hyphens, no special chars, max 50 chars)
2. Create a worktree:
   ```
   git worktree add ../worktrees/feat/<slug> -b feat/<slug>
   ```
3. Spawn a sub-agent using the `Task` tool with `subagent_type: "general-purpose"` and `model` set to the model you chose during triage. Pass it these instructions:

   ```
   You are implementing a task from the TaskManager system and shepherding it through to merge.

   **Working directory:** <absolute path to worktree>
   **Task ID:** <id>
   **Task title:** <title>
   **Task description:** <description>
   **Linked wiki pages:** <content from any linked wiki pages, fetched beforehand>

   ## Phase 1: Implement

   1. cd into the worktree directory. All work happens there.
   2. Read the task description carefully. Explore the codebase to understand where changes are needed.
   3. Implement the fix or feature.
   4. Run tests (`make test`, `npm test`, `cargo test`, `pytest`, or whatever the project uses). Fix failures.
   5. Run linting if available. Fix issues.
   6. Stage and commit with a conventional commit message:
      - Format: `feat(scope): description (task #<ID>)` or `fix(scope): description (task #<ID>)`
      - Include `Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>`
   7. Push the branch: `git push -u origin feat/<slug>`
   8. Create a PR: `gh pr create --fill`
   9. Capture the PR URL from the output.
   10. Add the PR URL as a comment on the TaskManager task.

   ## Phase 2: Monitor and fix until CI passes

   After the PR is created, enter a fix loop:

   1. Wait ~30 seconds, then check CI status with `gh pr checks`.
   2. If checks are still pending, wait another 30 seconds and check again. Repeat up to 10 times (5 minutes max).
   3. If any checks fail:
      a. Fetch failed logs: `gh run view <run-id> --log-failed`
      b. Fix the issue in the worktree.
      c. Run tests locally to verify.
      d. Commit, push.
      e. Restart the fix loop from step 1.
   4. Check for CI reviewer feedback (the Review Gate is a required status check that fails when issues exist):
      a. Fetch CI reviewer issue comments (these are posted by the Claude Review workflow):
         ```
         gh api repos/{owner}/{repo}/issues/{number}/comments --paginate \
           --jq '.[] | select(.body | test("<!-- claude-(code|security)-review -->")) | .body'
         ```
      b. The "Review Gate" check in `gh pr checks` will show as failed if either reviewer flagged issues.
      c. If the Review Gate failed (or CI reviewer comments contain "### New Issues" or "### Still Open"):
         - Parse the CI reviewer issue comments to understand what needs fixing
         - Address each flagged issue in the worktree
         - Commit, push
         - Restart the fix loop from step 1 (pushing will trigger re-review and a new Review Gate verdict)
   5. Also check for line-level review comments: `gh api repos/{owner}/{repo}/pulls/{number}/comments`
      If there are review comments requesting changes, address them, commit, push, and restart from step 1.
   6. If all checks pass (including the Review Gate) and no unaddressed review comments remain, proceed to Phase 3.

   **Guardrails:**
   - Maximum 5 fix iterations total. If still failing after 5 rounds, stop and report the failure.
   - If a failure looks unrelated to your changes (flaky test, infra issue), note it and proceed.

   ## Phase 3: Merge

   If ALL of the following are true:
   - All CI checks are passing (including the Review Gate status check)
   - No unaddressed review comments

   Then merge: `gh pr merge --squash --auto`

   If required approvals are pending, do NOT merge. Note that the PR is ready for review.

   ## Phase 4: Complete

   - Use the TaskManager MCP tools to mark the task as completed.
   - Report back: what was implemented, PR URL, merge status, and any issues encountered.

   If you hit a blocker you can't resolve, stop and report the failure clearly. Do not mark the task as completed.
   ```

**Spawn all sub-agents in parallel** — include all Task tool calls in a single message.

Before spawning, fetch any linked wiki pages for each task using `get_task_wiki_pages` and `get_wiki_page` so you can pass that context to the sub-agent.

## 4. Clean up worktrees and branches

After all sub-agents finish, for each worktree:
```
git worktree remove ../worktrees/feat/<slug>
git branch -D feat/<slug>
git push origin --delete feat/<slug>
```

If worktree removal fails (uncommitted changes etc.), leave it and note it in the summary.
Only delete branches for tasks that were successfully merged. Skip branch deletion for tasks that are awaiting review or failed.

## 5. Summary

Report:

| Task | Title | Status | PR | Merged? | Notes |
|------|-------|--------|----|---------|-------|
| #ID  | title | merged/awaiting-review/ci-failing/failed/skipped | PR URL or — | yes/no | details |

Statuses:
- **merged** — PR created, CI passed, merged successfully
- **awaiting-review** — PR created, CI passes, but required approvals are pending
- **ci-failing** — PR created but CI failures couldn't be resolved after 5 attempts
- **failed** — hit a blocker during implementation
- **skipped** — triaged out as too vague or too large

Then list any tasks that were skipped or failed with your reasoning.
