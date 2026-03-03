"""Evaluation runner — runs agents against test datasets and scores results.

Usage:
    uv run python -m tests.evaluations.runner --agent chatbot
    uv run python -m tests.evaluations.runner --agent chatbot --scorer llm_judge
    uv run python -m tests.evaluations.runner --agent chatbot --output json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path

from .models import EvalCase, EvalResult, EvalRun, load_dataset
from .scorers import (
    CompositeScorer,
    KeywordScorer,
    LLMJudgeScorer,
    Scorer,
    ToolUseScorer,
)

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATASETS_DIR = Path(__file__).resolve().parent / "datasets"
RESULTS_DIR = Path(__file__).resolve().parent / "results"


def _get_scorer(name: str) -> Scorer:
    """Get a scorer by name."""
    scorers: dict[str, Scorer] = {
        "llm_judge": LLMJudgeScorer(),
        "keyword": KeywordScorer(),
        "tool_use": ToolUseScorer(),
        "composite": CompositeScorer(),
    }
    if name not in scorers:
        raise ValueError(f"Unknown scorer: {name!r}. Available: {', '.join(scorers)}")
    return scorers[name]


def _find_dataset(agent_name: str, dataset_path: str | None = None) -> Path:
    """Resolve the dataset path for an agent."""
    if dataset_path:
        path = Path(dataset_path)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        if not path.exists():
            raise FileNotFoundError(f"Dataset not found: {path}")
        return path

    path = DATASETS_DIR / f"{agent_name}.jsonl"
    if not path.exists():
        raise FileNotFoundError(
            f"No dataset found for agent {agent_name!r} at {path}. "
            f"Create one or pass --dataset explicitly."
        )
    return path


def _create_agent(agent_name: str, variant: str | None = None):
    """Create an agent instance from the registry, optionally with a prompt variant."""
    from shared.registry import GITHUB_MCP_AGENTS, build_agent_registry, github_mcp_config

    registry = build_agent_registry()

    if agent_name not in registry:
        available = ", ".join(sorted(registry.keys()))
        raise ValueError(f"Unknown agent: {agent_name!r}. Available: {available}")

    agent_class, kwargs, _desc = registry[agent_name]
    kwargs = dict(kwargs) if kwargs else {}

    # Inject GitHub MCP config lazily for agents that need it
    if agent_name in GITHUB_MCP_AGENTS and "mcp_urls" not in kwargs:
        try:
            kwargs.update(github_mcp_config())
        except ValueError:
            pass  # Skip GitHub MCP if PAT not set

    agent = agent_class(**kwargs)

    # Apply prompt variant if specified
    if variant and variant != "default":
        prompts_module = _load_prompts_module(agent_name)
        if prompts_module is None:
            raise ValueError(f"No prompts module found for agent {agent_name!r}")

        variants = getattr(prompts_module, "PROMPT_VARIANTS", None)
        if variants is None or variant not in variants:
            available = list((variants or {}).keys())
            raise ValueError(
                f"Variant {variant!r} not found for {agent_name}. "
                f"Available: {available}. "
                f"Define PROMPT_VARIANTS in agents/{agent_name.replace('-', '_')}/prompts.py"
            )

        variant_prompt = variants[variant]
        # Override the system prompt method
        agent.get_system_prompt = lambda: variant_prompt  # type: ignore[method-assign]

    return agent


def _load_prompts_module(agent_name: str):
    """Try to import the prompts module for an agent."""
    # Convert kebab-case to module path
    module_name = agent_name.replace("-", "_")
    try:
        import importlib

        return importlib.import_module(f"agents.{module_name}.prompts")
    except (ImportError, ModuleNotFoundError):
        return None


async def evaluate_case(
    agent, case: EvalCase, scorer: Scorer
) -> EvalResult:
    """Run a single evaluation case against an agent."""
    tools_called: list[str] = []

    def on_tool_start(tool_name: str) -> None:
        tools_called.append(tool_name)

    # Track tokens before and after
    tokens_before_in = agent.total_input_tokens
    tokens_before_out = agent.total_output_tokens

    start_time = time.monotonic()
    error: str | None = None
    response = ""

    try:
        response = await agent.process_message(
            case.input,
            on_tool_start=on_tool_start,
        )
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
        response = f"[ERROR] {error}"

    elapsed_ms = (time.monotonic() - start_time) * 1000

    input_tokens = agent.total_input_tokens - tokens_before_in
    output_tokens = agent.total_output_tokens - tokens_before_out

    # Score the response
    if isinstance(scorer, CompositeScorer):
        score, score_details = await scorer.score_detailed(case, response, tools_called)
    else:
        score_val, scorer_name = await scorer.score(case, response, tools_called)
        score = score_val
        score_details = {scorer_name: score_val}

    if error:
        score = min(score, 2.0)  # Cap score on errors

    return EvalResult(
        case=case,
        response=response,
        score=score,
        score_details=score_details,
        tools_called=tools_called,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=elapsed_ms,
        error=error,
    )


async def run_evaluation(
    agent_name: str,
    dataset_path: str | None = None,
    scorer_name: str = "composite",
    variant: str = "default",
    tags_filter: list[str] | None = None,
) -> EvalRun:
    """Run a full evaluation and return aggregated results.

    Args:
        agent_name: Name of the agent (from registry).
        dataset_path: Path to JSONL dataset file. If None, uses default for agent.
        scorer_name: Scorer to use (llm_judge, keyword, tool_use, composite).
        variant: Prompt variant name. "default" uses the standard prompt.
        tags_filter: If provided, only run cases matching these tags.

    Returns:
        EvalRun with all results.
    """
    path = _find_dataset(agent_name, dataset_path)
    cases = load_dataset(path)

    if tags_filter:
        filter_set = set(tags_filter)
        cases = [c for c in cases if filter_set & set(c.tags)]
        if not cases:
            raise ValueError(f"No cases match tags: {tags_filter}")

    scorer = _get_scorer(scorer_name)
    agent = _create_agent(agent_name, variant)

    run = EvalRun(
        agent_name=agent_name,
        variant=variant,
        dataset_path=str(path),
    )

    total = len(cases)
    for i, case in enumerate(cases, 1):
        print(f"  [{i}/{total}] {case.input[:60]}...", end="", flush=True)

        # Reset conversation history between test cases for isolation
        agent.messages.clear()

        result = await evaluate_case(agent, case, scorer)
        run.results.append(result)

        status = "OK" if result.score >= 3 else "FAIL"
        print(f" -> {result.score}/5 [{status}]")

    run.completed_at = datetime.now(UTC).isoformat()
    return run


def _print_results_table(run: EvalRun) -> None:
    """Print a human-readable results table."""
    print(f"\n{'=' * 70}")
    print(f"Evaluation: {run.agent_name} (variant: {run.variant})")
    print(f"{'=' * 70}")

    for i, r in enumerate(run.results, 1):
        status = "PASS" if r.score >= 3 else "FAIL"
        print(f"  {i:3d}. [{status}] {r.score}/5  {r.case.input[:50]}")
        if r.error:
            print(f"       ERROR: {r.error[:60]}")
        if r.tools_called:
            print(f"       Tools: {', '.join(r.tools_called)}")

    summary = run.summary()
    print(f"\n{'─' * 70}")
    print(f"  Cases: {summary['num_cases']}  |  "
          f"Avg Score: {summary['avg_score']}  |  "
          f"Pass Rate: {summary['pass_rate']}  |  "
          f"Tokens: {summary['total_tokens']}  |  "
          f"Avg Latency: {summary['avg_latency_ms']}ms")
    print(f"{'─' * 70}\n")


def _print_comparison(run_a: EvalRun, run_b: EvalRun) -> None:
    """Print a side-by-side comparison of two eval runs."""
    print(f"\n{'=' * 70}")
    print(f"A/B Comparison: {run_a.agent_name}")
    print(f"  Variant A: {run_a.variant}  |  Variant B: {run_b.variant}")
    print(f"{'=' * 70}")

    summary_a = run_a.summary()
    summary_b = run_b.summary()

    rows = [
        ("Avg Score", summary_a["avg_score"], summary_b["avg_score"]),
        ("Pass Rate", summary_a["pass_rate"], summary_b["pass_rate"]),
        ("Total Tokens", summary_a["total_tokens"], summary_b["total_tokens"]),
        ("Avg Latency (ms)", summary_a["avg_latency_ms"], summary_b["avg_latency_ms"]),
    ]

    print(f"  {'Metric':<20} {'Variant A':>12} {'Variant B':>12}")
    print(f"  {'─' * 46}")
    for label, val_a, val_b in rows:
        print(f"  {label:<20} {str(val_a):>12} {str(val_b):>12}")
    print()


async def _main() -> None:
    parser = argparse.ArgumentParser(
        description="Run agent evaluations against test datasets.",
        prog="python -m tests.evaluations.runner",
    )
    parser.add_argument(
        "--agent", required=True, help="Agent name from the registry (e.g., chatbot)"
    )
    parser.add_argument(
        "--dataset", default=None, help="Path to JSONL dataset file (defaults to datasets/<agent>.jsonl)"
    )
    parser.add_argument(
        "--scorer",
        default="composite",
        choices=["composite", "llm_judge", "keyword", "tool_use"],
        help="Scoring method (default: composite)",
    )
    parser.add_argument(
        "--variant-a",
        default=None,
        help="First prompt variant for A/B testing",
    )
    parser.add_argument(
        "--variant-b",
        default=None,
        help="Second prompt variant for A/B testing",
    )
    parser.add_argument(
        "--tags",
        nargs="*",
        default=None,
        help="Only run cases matching these tags",
    )
    parser.add_argument(
        "--output",
        choices=["table", "json"],
        default="table",
        help="Output format (default: table)",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save results to tests/evaluations/results/",
    )

    args = parser.parse_args()

    # A/B testing mode
    if args.variant_a and args.variant_b:
        print(f"Running A/B evaluation for {args.agent}...")
        run_a = await run_evaluation(
            agent_name=args.agent,
            dataset_path=args.dataset,
            scorer_name=args.scorer,
            variant=args.variant_a,
            tags_filter=args.tags,
        )
        run_b = await run_evaluation(
            agent_name=args.agent,
            dataset_path=args.dataset,
            scorer_name=args.scorer,
            variant=args.variant_b,
            tags_filter=args.tags,
        )

        if args.output == "json":
            print(json.dumps({
                "variant_a": {**run_a.summary(), "results": [r.to_dict() for r in run_a.results]},
                "variant_b": {**run_b.summary(), "results": [r.to_dict() for r in run_b.results]},
            }, indent=2))
        else:
            _print_results_table(run_a)
            _print_results_table(run_b)
            _print_comparison(run_a, run_b)

        if args.save:
            path_a = run_a.save(RESULTS_DIR)
            path_b = run_b.save(RESULTS_DIR)
            print(f"Results saved: {path_a}, {path_b}")

    # Single evaluation mode
    else:
        variant = args.variant_a or "default"
        print(f"Running evaluation for {args.agent} (variant: {variant})...")
        run = await run_evaluation(
            agent_name=args.agent,
            dataset_path=args.dataset,
            scorer_name=args.scorer,
            variant=variant,
            tags_filter=args.tags,
        )

        if args.output == "json":
            print(json.dumps(
                {**run.summary(), "results": [r.to_dict() for r in run.results]},
                indent=2,
            ))
        else:
            _print_results_table(run)

        if args.save:
            path = run.save(RESULTS_DIR)
            print(f"Results saved: {path}")


if __name__ == "__main__":
    asyncio.run(_main())
