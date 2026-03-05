"""PR Shepherd — polls open PRs, fixes CI failures, and auto-merges.

Standalone async service built on the PollingAgent base class.
Does not use MCP — all GitHub interaction is via the ``gh`` CLI,
and CI fixes are done via Claude Code workspaces.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from agent_framework.core.polling_agent import PollingAgent
from agent_framework.tools.claude_code import (
    create_claude_code_workspace,
    run_claude_code,
)

from agents.orchestrator.models import validate_git_ref, validate_workspace_name

from . import github_ops
from .models import PRActionResult, PRDiagnosis, PRShepherdConfig, PRStatus, TrackedPR
from .prompts import FIX_CI_INSTRUCTIONS_TEMPLATE, REVIEW_COMMENTS_SECTION_TEMPLATE

logger = logging.getLogger(__name__)


class PRShepherd(PollingAgent[TrackedPR, PRDiagnosis, PRActionResult]):
    """Watches PRs, ensures CI passes, and merges them.

    Implements the PollingAgent pipeline:
    - poll: list open PRs from configured repos
    - diagnose: check CI status for each PR
    - act: merge if passing, fix if failing
    - escalate: comment on PR when max retries exceeded
    """

    def __init__(self, config: PRShepherdConfig) -> None:
        super().__init__(config)
        self.config: PRShepherdConfig = config

    # ── PollingAgent abstract method implementations ─────────────────

    async def poll(self) -> list[TrackedPR]:
        """List open PRs across all configured repos."""
        all_prs: list[TrackedPR] = []
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
                all_prs.append(pr)
        return all_prs

    def get_item_id(self, item: TrackedPR) -> str:
        """Return a unique identifier like 'owner/repo#123'."""
        return f"{item.repo}#{item.number}"

    async def diagnose(self, item: TrackedPR) -> PRDiagnosis:
        """Check CI status for a PR."""
        overall, failing = await github_ops.get_check_status(item.repo, item.number)
        logger.info(
            f"{item.repo}#{item.number} ({item.title}): "
            f"checks={overall}, failing={failing}, attempts={item.fix_attempts}"
        )
        return PRDiagnosis(overall_status=overall, failing_checks=failing)

    async def should_skip(self, item: TrackedPR, diagnosis: PRDiagnosis) -> bool:
        """Skip PRs whose checks are still pending."""
        if diagnosis.overall_status == "pending":
            logger.info(f"{item.repo}#{item.number}: checks pending, skipping")
            item.status = PRStatus.PENDING_CHECKS
            return True
        return False

    async def get_attempt_count(self, item: TrackedPR) -> int:
        """Return the number of previous fix attempts (already loaded in poll)."""
        return item.fix_attempts

    async def act(self, item: TrackedPR, diagnosis: PRDiagnosis) -> PRActionResult:
        """Merge passing PRs or attempt to fix failing ones."""
        if diagnosis.overall_status == "pass":
            item.status = PRStatus.CHECKS_PASSING
            return await self._merge_pr(item)
        else:
            item.status = PRStatus.CHECKS_FAILING
            return await self._fix_pr(item, diagnosis.failing_checks)

    async def should_escalate(self, item: TrackedPR, result: PRActionResult) -> bool:
        """Escalate if an action failed (but not for successful merges/fixes)."""
        return not result.success

    async def escalate(self, item: TrackedPR, result: PRActionResult) -> None:
        """Post a comment about the failure."""
        if result.action == "abandoned":
            item.status = PRStatus.ABANDONED
            await github_ops.add_comment(
                item.repo,
                item.number,
                f"[PR Shepherd] {result.message}",
            )
        elif result.message:
            logger.warning(f"{item.repo}#{item.number}: {result.message}")

    async def on_max_retries_exceeded(
        self, item: TrackedPR, diagnosis: PRDiagnosis
    ) -> PRActionResult:
        """Create a result for when max fix attempts are exhausted."""
        return PRActionResult(
            success=False,
            action="abandoned",
            message=(
                f"Giving up after {item.fix_attempts} fix attempt(s). "
                f"Remaining failures: {diagnosis.failing_checks}"
            ),
        )

    # ── Private implementation details ───────────────────────────────

    async def _merge_pr(self, pr: TrackedPR) -> PRActionResult:
        """Merge a PR whose checks are passing."""
        success = await github_ops.merge_pr(pr.repo, pr.number, method=self.config.merge_method)
        if success:
            pr.status = PRStatus.MERGED
            logger.info(f"Merged {pr.repo}#{pr.number}")
            return PRActionResult(success=True, action="merged")
        else:
            logger.error(f"Failed to merge {pr.repo}#{pr.number}")
            return PRActionResult(
                success=False, action="merge_failed", message="merge command failed"
            )

    async def _fix_pr(self, pr: TrackedPR, failing_checks: list[str]) -> PRActionResult:
        """Attempt to fix CI failures using a Claude Code worker."""
        pr.status = PRStatus.FIXING
        attempt = pr.fix_attempts + 1

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
            return PRActionResult(
                success=False, action="no_logs", message="could not retrieve CI logs"
            )
        if review_comments:
            logger.info(f"{pr.repo}#{pr.number}: found review comments to include")

        # Validate branch name before using in git commands
        try:
            validate_git_ref(pr.head_branch, "head branch")
        except ValueError:
            logger.error(f"Invalid branch name for {pr.repo}#{pr.number}: {pr.head_branch!r}")
            return PRActionResult(success=False, action="fix_failed", message="invalid branch name")

        # Ensure workspace exists (clone repo, checkout PR branch)
        workspace_name = f"pr-shepherd-{pr.repo.replace('/', '-')}-{pr.number}"
        try:
            validate_workspace_name(workspace_name)
        except ValueError:
            logger.error(f"Invalid workspace name: {workspace_name!r}")
            return PRActionResult(
                success=False, action="fix_failed", message="invalid workspace name"
            )

        git_url = f"git@github.com:{pr.repo}.git"

        ws_result = await create_claude_code_workspace(
            folder_name=workspace_name,
            git_repo_url=git_url,
        )

        if not ws_result.get("success") and "already exists" not in str(ws_result.get("error", "")):
            logger.error(f"Failed to create workspace: {ws_result.get('error')}")
            return PRActionResult(
                success=False, action="fix_failed", message="workspace creation failed"
            )

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
            return PRActionResult(
                success=False, action="fix_failed", message="git operation timed out"
            )

        # Build worker instructions.
        def _escape(s: str) -> str:
            return s.replace("{", "{{").replace("}", "}}")

        review_section = ""
        if review_comments:
            review_section = REVIEW_COMMENTS_SECTION_TEMPLATE.format(
                review_comments=_escape(review_comments),
            )

        # Query feedback store for known patterns in this repo.
        feedback_section = ""
        try:
            from shared.outcome_store import get_relevant_feedback

            feedback = await get_relevant_feedback(repo=pr.repo, limit=5)
            if feedback:
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
            return PRActionResult(success=False, action="fix_failed", message="worker error")

        # Push the fix
        pushed = await github_ops.push_branch(workspace_path, pr.head_branch)
        if pushed:
            logger.info(f"Pushed fix for {pr.repo}#{pr.number}")
            await github_ops.add_comment(
                pr.repo,
                pr.number,
                f"[PR Shepherd] Fix attempt #{attempt} pushed. Waiting for CI.",
            )
            return PRActionResult(success=True, action="fix_pushed")
        else:
            logger.error(f"Failed to push fix for {pr.repo}#{pr.number}")
            await github_ops.add_comment(
                pr.repo,
                pr.number,
                f"[PR Shepherd] Fix attempt #{attempt}: push failed.",
            )
            return PRActionResult(success=False, action="push_failed", message="git push failed")
