# Agent Evaluation and A/B Testing

This document describes the evaluation framework for measuring and optimizing agent quality.

## Overview

The evaluation system provides three capabilities:

1. **Evaluation Runner** — Run agents against curated test cases and score responses
2. **A/B Testing** — Compare prompt variants using the same eval datasets
3. **Metrics Collection** — Track quality, cost, and latency across runs

## Architecture

```
tests/evaluations/
├── __init__.py
├── runner.py          # Core eval runner — loads datasets, runs agents, scores results
├── scorers.py         # Scoring functions (LLM-as-judge, keyword, tool-use checks)
├── models.py          # Data models (EvalCase, EvalResult, EvalRun)
├── datasets/          # JSONL test cases per agent
│   ├── chatbot.jsonl
│   ├── business.jsonl
│   ├── security.jsonl
│   ├── code-analysis.jsonl
│   ├── log-analysis.jsonl
│   └── README.md
└── results/           # Stored eval run results (gitignored)
```

## Quick Start

```bash
# Run evaluations for a specific agent
uv run python -m tests.evaluations.runner --agent chatbot

# Run a single dataset file
uv run python -m tests.evaluations.runner --agent chatbot --dataset tests/evaluations/datasets/chatbot.jsonl

# Use a specific scorer
uv run python -m tests.evaluations.runner --agent chatbot --scorer llm_judge

# A/B test: compare two prompt variants
uv run python -m tests.evaluations.runner --agent chatbot --variant-a default --variant-b concise

# Output results as JSON
uv run python -m tests.evaluations.runner --agent chatbot --output json
```

## Test Case Format

Test cases are JSONL files (one JSON object per line):

```jsonl
{"input": "What's the weather like?", "expected": "The agent should explain it cannot check weather", "tags": ["boundaries", "tool-awareness"]}
{"input": "Remember that my name is Alice", "expected": "The agent should acknowledge and save the memory", "tags": ["memory", "basic"]}
{"input": "What tools do you have?", "expected": "The agent should list available tools", "tags": ["self-awareness"]}
```

### Fields

| Field | Required | Description |
|-------|----------|-------------|
| `input` | Yes | The user message to send to the agent |
| `expected` | Yes | Natural-language description of the expected behavior |
| `tags` | No | List of tags for filtering and grouping results |
| `expected_tools` | No | List of tool names the agent should call |
| `expected_keywords` | No | Keywords that should appear in the response |
| `max_tokens` | No | Override max response tokens for this case |

## Scorers

### Built-in Scorers

1. **`llm_judge`** — Uses Claude Haiku as a judge to rate responses 1-5 against expected behavior. Most flexible, handles nuanced evaluation.

2. **`keyword`** — Checks if `expected_keywords` appear in the response. Fast, deterministic, good for factual checks.

3. **`tool_use`** — Verifies the agent called the expected tools (via `expected_tools` field). Useful for testing that agents use the right capabilities.

4. **`composite`** — Runs all applicable scorers and averages their scores. Default scorer.

### Scoring Scale

All scorers normalize to a 1-5 scale:

| Score | Meaning |
|-------|---------|
| 5 | Perfect — fully meets expected behavior |
| 4 | Good — meets expectations with minor gaps |
| 3 | Acceptable — partially meets expectations |
| 2 | Poor — significant gaps from expected behavior |
| 1 | Failure — does not meet expected behavior at all |

## A/B Testing Prompt Variants

To compare prompt variants, define `PROMPT_VARIANTS` in the agent's `prompts.py`:

```python
# agents/business_advisor/prompts.py

SYSTEM_PROMPT = "..."  # Default prompt (variant "default")

PROMPT_VARIANTS = {
    "concise": "...",         # Same guardrails, shorter response style
    "no-guardrails": "...",   # Full prompt without guardrails section
}
```

The runner creates a temporary agent with the variant prompt and runs the same dataset against both variants. Results are compared side-by-side.

### Example: Verifying guardrails work

The business advisor has a `no-guardrails` variant that deliberately omits the guardrails section. Compare it against the default to verify guardrails are effective:

```bash
# Run A/B comparison on guardrail-tagged test cases
uv run python -m tests.evaluations.runner --agent business \
    --variant-a default --variant-b no-guardrails \
    --tags guardrails

# If both variants score the same on guardrail tests, the guardrails aren't working
```

### Agents with prompt variants

| Agent | Variants | Purpose |
|-------|----------|---------|
| business | `concise`, `no-guardrails` | Test response brevity vs quality, verify guardrail effectiveness |

## Metrics Collected

Each evaluation run captures:

- **Quality**: Score per test case (1-5 scale)
- **Cost**: Input/output tokens per response
- **Latency**: Wall-clock time per response
- **Tool Usage**: Which tools were called and how many times
- **Iterations**: Number of agentic loop iterations per response

## Langfuse Integration

When Langfuse is configured (`LANGFUSE_ENABLED=true`), the eval runner automatically:

1. **Groups traces by run** — Each eval case's `process_message()` call uses `session_id=eval-{run_id}` and `user_id=eval-runner`, so eval traces are grouped and filterable in the Langfuse dashboard.
2. **Pushes scores** — After each case is scored, the score is attached to the Langfuse trace via `langfuse.score()`. This makes scores visible directly on traces in the dashboard.
3. **Flushes on completion** — The Langfuse client is flushed at the end of each eval run to ensure all data is sent.

All Langfuse integration is optional and degrades gracefully — the runner works identically without Langfuse configured.

### Filtering eval traces in Langfuse

- Filter by `user_id = eval-runner` to see only eval traces
- Filter by `session_id` starting with `eval-` to find specific runs
- Scores appear on traces with name `eval_score` and include variant/dataset metadata in the comment field

## Adding Evaluations for a New Agent

1. Create a dataset file: `tests/evaluations/datasets/<agent-name>.jsonl`
2. Add 5-10 test cases covering core capabilities
3. Run: `uv run python -m tests.evaluations.runner --agent <agent-name>`
4. Review results and iterate on test cases

## Design Decisions

- **JSONL over JSON/YAML**: One case per line makes diffs clean and supports streaming reads for large datasets.
- **LLM-as-judge default**: Natural language `expected` fields are more maintainable than brittle regex assertions. Claude Haiku keeps costs low (~$0.001 per judgment).
- **No mock agents in eval**: Evaluations run the real `process_message()` pipeline including tool calls, permissions, and context management. This catches integration issues that unit tests miss.
- **Separate from pytest**: Evaluations call the Anthropic API and cost money. They should be run deliberately, not on every `pytest` invocation.

## Related Documentation

- [TESTING.md](TESTING.md) — Unit testing and debugging guide
- [observability.md](observability.md) — Langfuse tracing setup
