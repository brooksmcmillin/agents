# Evaluation Datasets

Each file is a JSONL dataset (one JSON object per line) used by the evaluation runner.

## Format

```jsonl
{"input": "user message", "expected": "description of expected behavior", "tags": ["tag1"]}
```

## Files

- `chatbot.jsonl` — General chatbot agent test cases

## Adding a Dataset

1. Create `<agent-name>.jsonl` matching the agent's registry name
2. Add 5-10 test cases covering core capabilities
3. Run: `uv run python -m tests.evaluations.runner --agent <agent-name>`
