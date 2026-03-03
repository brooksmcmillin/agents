"""PR Shepherd — polls open PRs, fixes CI failures, and auto-merges.

Standalone async service. Does not use MCP — all GitHub interaction is via
the ``gh`` CLI, and CI fixes are done via Claude Code workspaces.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from agent_framework.tools.claude_code import (
    create_claude_code_workspace,
    run_claude_code,
)

from agents.orchestrator.models import validate_git_ref, validate_workspace_name

from . import github_ops
from .models import PRShepherdConfig, PRStatus, TrackedPR
from .prompts import FIX_CI_INSTRUCTIONS_TEMPLATE, REVIEW_COMMENTS_SECTION_TEMPLATE

logger = logging.getLogger(__name__)


class PRShepherd:
    """Watches PRs, ensures CI passes, and merges them."""

    def __init__(self, config: PRShepherdConfig) -> None:
        self.config = config

    async def run(self) -> None:
        """Main loop: poll, process, sleep, repeat."""
        logger.info(
            f"PR Shepherd starting — repos={self.config.repos}, "
            f"poll_interval={self.config.poll_interval}s, "
            f"dry_run={self.config.dry_run}"
        )
        while True:
            await self.run_once()
            logger.info(f"Sleeping {self.config.poll_interval}s before next poll")
            await asyncio.sleep(self.config.poll_interval)

    async def run_once(self) -> list[TrackedPR]:
        """Single pass over all configured repos. Returns tracked PRs."""
        all_tracked: list[TrackedPR] = []

        for repo in self.config.repos:
            prs = await github_ops.list_open_prs(repo, label=self.config.label_filter)
            logger.info(f"{repo}: found {len(prs)} open PR(s)")

            for pr_data in prs:
                pr = TrackedPR(
                    repo=repo,
                    number=int(pr_data["number"]),
                    title=str(pr_data["title"]),
                    head_branch=str(pr_data["headRefName"]),
                )
                # Recover fix attempt count from comment history (stateless)
                pr.fix_attempts = await github_ops.get_fix_attempt_count(repo, pr.number)

                try:
                    await self._process_pr(pr)
                except Exception:
                    logger.exception(f"Unhandled error processing {pr.repo}#{pr.number}, skipping")
                all_tracked.append(pr)

        return all_tracked

    async def _process_pr(self, pr: TrackedPR) -> None:
        """Check CI status and take appropriate action."""
        overall, failing = await github_ops.get_check_status(pr.repo, pr.number)
        logger.info(
            f"{pr.repo}#{pr.number} ({pr.title}): "
            f"checks={overall}, failing={failing}, attempts={pr.fix_attempts}"
        )

        if overall == "pass":
            pr.status = PRStatus.CHECKS_PASSING
            await self._merge_pr(pr)
        elif overall == "fail":
            pr.status = PRStatus.CHECKS_FAILING
            if pr.fix_attempts >= self.config.max_fix_attempts:
                logger.warning(
                    f"{pr.repo}#{pr.number}: max fix attempts "
                    f"({self.config.max_fix_attempts}) reached, abandoning"
                )
                pr.status = PRStatus.ABANDONED
                if not self.config.dry_run:
                    await github_ops.add_comment(
                        pr.repo,
                        pr.number,
                        f"[PR Shepherd] Giving up after {pr.fix_attempts} "
                        f"fix attempt(s). Remaining failures: {failing}",
                    )
                else:
                    print(f"  [dry-run] Would comment: abandoning after {pr.fix_attempts} attempts")
            else:
                await self._fix_pr(pr, failing)
        else:
            # pending — nothing to do yet
            pr.status = PRStatus.PENDING_CHECKS
            print(f"  {pr.repo}#{pr.number}: checks pending, skipping")

    async def _merge_pr(self, pr: TrackedPR) -> None:
        """Merge a PR whose checks are passing."""
        if self.config.dry_run:
            print(f"  [dry-run] Would merge {pr.repo}#{pr.number} via {self.config.merge_method}")
            return

        success = await github_ops.merge_pr(pr.repo, pr.number, method=self.config.merge_method)
        if success:
            pr.status = PRStatus.MERGED
            logger.info(f"Merged {pr.repo}#{pr.number}")
        else:
            logger.error(f"Failed to merge {pr.repo}#{pr.number}")

    async def _fix_pr(self, pr: TrackedPR, failing_checks: list[str]) -> None:
        """Attempt to fix CI failures using a Claude Code worker."""
        pr.status = PRStatus.FIXING
        attempt = pr.fix_attempts + 1

        if self.config.dry_run:
            print(
                f"  [dry-run] Would attempt fix #{attempt} for "
                f"{pr.repo}#{pr.number}: {failing_checks}"
            )
            return

        logger.info(f"Attempting fix #{attempt} for {pr.repo}#{pr.number}: {failing_checks}")

        # Comment on the PR
        await github_ops.add_comment(
            pr.repo,
            pr.number,
            f"[PR Shepherd] Fix attempt #{attempt} — failing checks: {', '.join(failing_checks)}",
        )

        # Get failing logs and review comments in parallel
        logs, review_comments = await asyncio.gather(
            github_ops.get_failing_logs(pr.repo, pr.number),
            github_ops.get_review_comments(pr.repo, pr.number),
        )
        if not logs:
            logger.warning(f"No CI logs found for {pr.repo}#{pr.number}, skipping fix")
            await github_ops.add_comment(
                pr.repo,
                pr.number,
                "[PR Shepherd] Could not retrieve CI logs. Skipping fix attempt.",
            )
            return
        if review_comments:
            logger.info(f"{pr.repo}#{pr.number}: found review comments to include")

        # Validate branch name before using in git commands
        try:
            validate_git_ref(pr.head_branch, "head branch")
        except ValueError:
            logger.error(f"Invalid branch name for {pr.repo}#{pr.number}: {pr.head_branch!r}")
            return

        # Ensure workspace exists (clone repo, checkout PR branch)
        workspace_name = f"pr-shepherd-{pr.repo.replace('/', '-')}-{pr.number}"
        try:
            validate_workspace_name(workspace_name)
        except ValueError:
            logger.error(f"Invalid workspace name: {workspace_name!r}")
            return

        git_url = f"git@github.com:{pr.repo}.git"

        ws_result = await create_claude_code_workspace(
            folder_name=workspace_name,
            git_repo_url=git_url,
        )

        if not ws_result.get("success") and "already exists" not in str(ws_result.get("error", "")):
            logger.error(f"Failed to create workspace: {ws_result.get('error')}")
            return

        workspace_path = ws_result.get("workspace_path")
        if not workspace_path:
            workspace_path = str(
                Path(
                    os.environ.get(
                        "CLAUDE_CODE_WORKSPACES_DIR",
                        str(Path.home() / ".claude_code_workspaces"),
                    )
                )
                / workspace_name
            )
            logger.warning(f"workspace_path not in result, reconstructed: {workspace_path}")

        # Checkout the PR branch
        try:
            fetch_proc = await asyncio.create_subprocess_exec(
                "git",
                "fetch",
                "origin",
                pr.head_branch,
                cwd=workspace_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(fetch_proc.communicate(), timeout=60)

            checkout_proc = await asyncio.create_subprocess_exec(
                "git",
                "checkout",
                pr.head_branch,
                cwd=workspace_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(checkout_proc.communicate(), timeout=30)

            pull_proc = await asyncio.create_subprocess_exec(
                "git",
                "pull",
                "origin",
                pr.head_branch,
                cwd=workspace_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(pull_proc.communicate(), timeout=60)
        except TimeoutError:
            logger.error(f"Git operation timed out for {pr.repo}#{pr.number}")
            await github_ops.add_comment(
                pr.repo,
                pr.number,
                f"[PR Shepherd] Fix attempt #{attempt} aborted: git operation timed out.",
            )
            return

        # Build worker instructions.
        # Escape curly braces in user-controlled content so str.format()
        # doesn't choke on code snippets like {variable} in logs/comments.
        def _escape(s: str) -> str:
            return s.replace("{", "{{").replace("}", "}}")

        review_section = ""
        if review_comments:
            review_section = REVIEW_COMMENTS_SECTION_TEMPLATE.format(
                review_comments=_escape(review_comments),
            )

        # Query feedback store for known patterns in this repo.
        # Feedback originates from CI logs which could contain adversarial
        # content, so we sanitize it with a character allowlist before
        # injecting into the worker prompt.
        feedback_section = ""
        try:
            from shared.outcome_store import get_relevant_feedback

            feedback = await get_relevant_feedback(repo=pr.repo, limit=5)
            if feedback:
                # Strip chars outside the safe set (same approach as orchestrator workers)
                import re as _re

                _safe_re = _re.compile(r"[^a-zA-Z0-9 _.,'\"()\-:;!?@#/\n\r\t*`]+")
                sanitized = _safe_re.sub("", feedback)[:5000]
                feedback_section = f"\n{_escape(sanitized)}\n"
        except Exception as e:
            logger.debug(f"Could not fetch feedback for PR fix: {e}")

        instructions = FIX_CI_INSTRUCTIONS_TEMPLATE.format(
            title=_escape(pr.title),
            branch=_escape(pr.head_branch),
            repo=_escape(pr.repo),
            failing_checks=_escape(", ".join(failing_checks)),
            logs=_escape(logs),
            review_comments_section=review_section,
            feedback_section=feedback_section,
        )

        # Run Claude Code worker
        result = await run_claude_code(
            folder_name=workspace_name,
            command=instructions,
            timeout=self.config.worker_timeout,
            max_turns=30,
            model=self.config.worker_model,
        )

        if not result.get("success"):
            error = result.get("error_output") or result.get("error", "unknown")
            logger.warning(f"Worker failed for {pr.repo}#{pr.number}: {error}")
            await github_ops.add_comment(
                pr.repo,
                pr.number,
                f"[PR Shepherd] Fix attempt #{attempt} failed: worker error.",
            )
            return

        # Push the fix
        pushed = await github_ops.push_branch(workspace_path, pr.head_branch)
        if pushed:
            logger.info(f"Pushed fix for {pr.repo}#{pr.number}")
            await github_ops.add_comment(
                pr.repo,
                pr.number,
                f"[PR Shepherd] Fix attempt #{attempt} pushed. Waiting for CI.",
            )
        else:
            logger.error(f"Failed to push fix for {pr.repo}#{pr.number}")
            await github_ops.add_comment(
                pr.repo,
                pr.number,
                f"[PR Shepherd] Fix attempt #{attempt}: push failed.",
            )
