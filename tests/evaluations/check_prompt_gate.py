"""CI gate: require eval baselines when prompts.py files change.

Checks if any agents/*/prompts.py files changed in the current branch
relative to a base ref, and verifies that corresponding eval baseline
results were also updated in tests/evaluations/results/{agent_name}.json.

Usage:
    # In CI (GitHub Actions passes the base ref)
    uv run python -m tests.evaluations.check_prompt_gate origin/main

    # Locally — check your branch against main
    uv run python -m tests.evaluations.check_prompt_gate main

Exit codes:
    0: All changed agents have updated baselines (or no prompts changed).
    1: Missing eval baselines for agents with prompt changes.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Reverse mapping: module directory name → registry name.
# Must stay in sync with shared/registry.py build_agent_registry().
_MODULE_TO_REGISTRY: dict[str, str] = {
    "chatbot": "chatbot",
    "code_analysis": "code-analysis",
    "log_analysis": "log-analysis",
    "red_team": "red-team",
    "security_researcher": "security",
    "security_audit": "security-audit",
    "system_admin": "sysadmin",
    "task_manager": "tasks",
    "web_analysis": "web-analysis",
    "website_tester": "website-tester",
}

RESULTS_DIR = Path(__file__).resolve().parent / "results"


def get_changed_files(base_ref: str) -> list[str]:
    """Get files changed between base_ref and HEAD."""
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}...HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.strip().splitlines() if line]


def extract_changed_agents(changed_files: list[str]) -> list[str]:
    """Find agent registry names whose prompts.py files changed."""
    agents: list[str] = []
    for filepath in changed_files:
        parts = Path(filepath).parts
        # Match agents/<module_dir>/prompts.py
        if len(parts) >= 3 and parts[0] == "agents" and parts[2] == "prompts.py":
            module_name = parts[1]
            registry_name = _MODULE_TO_REGISTRY.get(module_name)
            if registry_name:
                agents.append(registry_name)
    return sorted(set(agents))


def extract_changed_baselines(changed_files: list[str]) -> set[str]:
    """Find agent names whose baseline result files changed."""
    baselines: set[str] = set()
    for filepath in changed_files:
        parts = Path(filepath).parts
        # Match tests/evaluations/results/<name>.json
        if (
            len(parts) >= 4
            and parts[0] == "tests"
            and parts[1] == "evaluations"
            and parts[2] == "results"
            and filepath.endswith(".json")
        ):
            baselines.add(Path(filepath).stem)
    return baselines


def check_prompt_gate(base_ref: str) -> int:
    """Run the prompt change detection gate.

    Returns:
        0 if gate passes, 1 if eval baselines are missing.
    """
    changed_files = get_changed_files(base_ref)
    changed_agents = extract_changed_agents(changed_files)

    if not changed_agents:
        print("No prompts.py changes detected. Gate passes.")
        return 0

    changed_baselines = extract_changed_baselines(changed_files)
    missing = [a for a in changed_agents if a not in changed_baselines]

    if missing:
        print(f"FAIL: Prompt changes detected but eval baselines missing for: {', '.join(missing)}")
        print()
        print("Run evals and commit baselines:")
        for agent in missing:
            print(f"  uv run python -m tests.evaluations.runner --agent {agent} --save-baseline")
        print()
        print("Then commit the result files in tests/evaluations/results/")
        return 1

    print(f"OK: Eval baselines updated for all changed agents: {', '.join(changed_agents)}")
    return 0


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m tests.evaluations.check_prompt_gate <base-ref>")
        print("Example: python -m tests.evaluations.check_prompt_gate origin/main")
        sys.exit(2)

    base_ref = sys.argv[1]
    sys.exit(check_prompt_gate(base_ref))


if __name__ == "__main__":
    main()
