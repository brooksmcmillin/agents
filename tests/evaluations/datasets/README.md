# Evaluation Datasets

Each file is a JSONL dataset (one JSON object per line) used by the evaluation runner.

## Format

```jsonl
{"input": "user message", "expected": "description of expected behavior", "tags": ["tag1"]}
```

## Files

- `chatbot.jsonl` — General chatbot agent test cases (greetings, memory, safety, self-awareness)
- `business.jsonl` — Business advisor guardrail enforcement (unvalidated claims, fictional social proof, legal flags, employment compliance, timelines, validation-before-building)
- `security.jsonl` — AI security research knowledge (RAG attacks, prompt injection, adversarial ML, deployment security, safety boundaries)
- `code-analysis.jsonl` — Code analysis methodology (security prioritization, SSRF, error handling, performance reasoning)
- `log-analysis.jsonl` — Log diagnostic reasoning (error investigation, pattern recognition, brute force, memory leaks, scope boundaries)

## Adding a Dataset

1. Create `<agent-name>.jsonl` matching the agent's registry name
2. Add 5-10 test cases covering core capabilities
3. Run: `uv run python -m tests.evaluations.runner --agent <agent-name>`
