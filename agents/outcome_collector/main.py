"""Outcome collector — polls GitHub for PR outcomes and records them.

A BatchAgent that runs on a schedule (or one-shot) to:
1. Poll configured repos for merged, closed, and failing PRs
2. Extract CI failure patterns from logs
3. Correlate PRs back to orchestrator tasks via branch names
4. Save structured outcomes to the feedback memory store
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re

from agents.pr_shepherd import github_ops
from shared.gh import run_gh, validate_repo
from shared.outcome_store import TaskOutcome, save_outcome

from .ci_patterns import extract_failure_patterns

logger = logging.getLogger(__name__)

# Branch name format used by the orchestrator: orchestrator/{task_id_hex}-{slug}
_ORCHESTRATOR_BRANCH_RE = re.compile(r"^orchestrator/([a-fA-F0-9]+)-")

# Task link pattern in PR body
_TASK_LINK_RE = re.compile(r"/task/(\d+)")


class OutcomeCollector:
    """Polls GitHub repos and records PR outcomes in the feedback store."""

    def __init__(
        self,
        repos: list[str] | None = None,
        dry_run: bool = False,
    ) -> None:
        self.repos = repos or self._repos_from_env()
        self.dry_run = dry_run

    def _repos_from_env(self) -> list[str]:
        """Get repos from environment variable."""
        raw = os.getenv("OUTCOME_COLLECTOR_REPOS", "")
        if not raw:
            logger.warning("No repos configured — set OUTCOME_COLLECTOR_REPOS")
            return []
        repos = [r.strip() for r in raw.split(",") if r.strip()]
        for r in repos:
            validate_repo(r)
        return repos

    async def run(self) -> list[TaskOutcome]:
        """Run the collection pass across all configured repos."""
        all_outcomes: list[TaskOutcome] = []

        for repo in self.repos:
            try:
                outcomes = await self._collect_repo(repo)
                all_outcomes.extend(outcomes)
            except Exception:
                logger.exception(f"Error collecting outcomes for {repo}")

        logger.info(f"Collected {len(all_outcomes)} outcome(s) across {len(self.repos)} repo(s)")
        return all_outcomes

    async def _collect_repo(self, repo: str) -> list[TaskOutcome]:
        """Collect outcomes for a single repository."""
        validate_repo(repo)
        outcomes: list[TaskOutcome] = []

        # Fetch merged, closed, and failing PRs in parallel
        merged, closed, failing = await asyncio.gather(
            self._fetch_merged_prs(repo),
            self._fetch_closed_prs(repo),
            self._fetch_failing_prs(repo),
        )

        for pr in merged:
            try:
                outcome = self._pr_to_outcome(pr, repo, "merged")
                outcomes.append(outcome)
            except (ValueError, KeyError) as e:
                logger.warning(f"Skipping malformed merged PR in {repo}: {e}")

        for pr in closed:
            try:
                outcome = self._pr_to_outcome(pr, repo, "closed")
                outcomes.append(outcome)
            except (ValueError, KeyError) as e:
                logger.warning(f"Skipping malformed closed PR in {repo}: {e}")

        for pr, failing_checks in failing:
            try:
                outcome = self._pr_to_outcome(pr, repo, "ci_failing")
                outcome.ci_failures = failing_checks
                # Fetch CI logs and extract patterns
                logs = await github_ops.get_failing_logs(repo, int(pr["number"]))
                if logs:
                    outcome.failure_patterns = extract_failure_patterns(logs)
                outcomes.append(outcome)
            except (ValueError, KeyError) as e:
                logger.warning(f"Skipping malformed failing PR in {repo}: {e}")

        # Save all outcomes
        for outcome in outcomes:
            if self.dry_run:
                logger.info(
                    f"[dry-run] Would save: {outcome.repo}#{outcome.pr_number} → {outcome.pr_status}"
                )
            else:
                await save_outcome(outcome)

        return outcomes

    async def _fetch_merged_prs(self, repo: str) -> list[dict]:
        """Fetch recently merged PRs."""
        rc, out, err = await run_gh(
            [
                "pr",
                "list",
                "--repo",
                repo,
                "--state",
                "merged",
                "--json",
                "number,title,headRefName,mergedAt,body",
                "--limit",
                "20",
            ]
        )
        if rc != 0:
            logger.error(f"Failed to fetch merged PRs for {repo}: {err}")
            return []
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            return []

    async def _fetch_closed_prs(self, repo: str) -> list[dict]:
        """Fetch recently closed (not merged) PRs."""
        rc, out, err = await run_gh(
            [
                "pr",
                "list",
                "--repo",
                repo,
                "--state",
                "closed",
                "--json",
                "number,title,headRefName,closedAt,body,mergedAt",
                "--limit",
                "10",
            ]
        )
        if rc != 0:
            logger.error(f"Failed to fetch closed PRs for {repo}: {err}")
            return []
        try:
            prs = json.loads(out)
        except json.JSONDecodeError:
            return []
        # Filter out merged ones (they'll be in the merged list)
        return [pr for pr in prs if not pr.get("mergedAt")]

    async def _fetch_failing_prs(self, repo: str) -> list[tuple[dict, list[str]]]:
        """Fetch open PRs with failing CI checks."""
        prs = await github_ops.list_open_prs(repo)
        failing: list[tuple[dict, list[str]]] = []

        for pr in prs:
            overall, checks = await github_ops.get_check_status(repo, int(pr["number"]))
            if overall == "fail":
                failing.append((pr, checks))

        return failing

    def _pr_to_outcome(self, pr: dict, repo: str, status: str) -> TaskOutcome:
        """Convert a PR dict to a TaskOutcome.

        Raises:
            ValueError: If pr["number"] is missing or non-numeric.
        """
        branch = pr.get("headRefName", "")
        task_id = self._extract_task_id(branch, pr.get("body", ""))

        raw_number = pr.get("number")
        if raw_number is None:
            raise ValueError(f"PR dict missing 'number' field: {pr}")
        pr_number = int(raw_number)

        return TaskOutcome(
            task_id=task_id or f"{repo}-{pr_number}",
            task_title=pr.get("title", ""),
            repo=repo,
            pr_number=pr_number,
            pr_url=f"https://github.com/{repo}/pull/{pr_number}",
            pr_status=status,
        )

    def _extract_task_id(self, branch: str, body: str) -> str | None:
        """Extract orchestrator task ID from branch name or PR body."""
        # Try branch name first
        match = _ORCHESTRATOR_BRANCH_RE.match(branch)
        if match:
            return match.group(1)

        # Try PR body for task links
        if body:
            match = _TASK_LINK_RE.search(body)
            if match:
                return match.group(1)

        return None
