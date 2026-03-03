---
description: Check CI tests and PR comments, fix issues, and merge
---

# Fix CI / Address PR Feedback / Merge

You are working on a PR in the current repository. Do the following steps in order:

## 1. Identify the PR

Use `gh pr view` to find the current branch's PR. If there's no PR, stop and tell me.

## 2. Gather CI and review status (in parallel)

Run these in parallel:
- `gh pr checks` to get CI/check status
- `gh pr view --json reviews,comments,reviewRequests` to get review comments and feedback
- `gh api repos/{owner}/{repo}/pulls/{number}/comments` to get inline review comments
- Check for any failing CI logs: for each failed check, fetch its logs with `gh run view <id> --log-failed`

## 3. Assess and fix

For each issue found (test failure, linter error, review comment requesting a change):
- If it's something you can fix: fix it, commit the change, and push.
- If it's something you decide NOT to fix: add it to a "not fixing" list with clear reasoning.

When fixing, work through issues iteratively - fix, run relevant tests locally to verify, then move on.

## 4. Report

After addressing everything, give me a summary:
- What you fixed (with brief descriptions)
- What you chose not to fix and why
- Current CI/review status

## 5. Merge (if appropriate)

If ALL of the following are true, merge the PR using `gh pr merge --squash --auto`:
- All CI checks are passing (or were passing before your fixes and you've pushed)
- All review comments have been addressed
- There are no unresolved items in your "not fixing" list that are blockers

If you cannot merge, explain what's still blocking.

Do NOT merge if there are required review approvals still pending - just tell me it's ready for re-review.

## 6. Clean up branches (after merge)

If the PR was merged, clean up the feature branch:
1. Switch to main and pull: `git checkout main && git pull`
2. Delete the local branch: `git branch -d <branch-name>`
3. Delete the remote branch: `git push origin --delete <branch-name>`
