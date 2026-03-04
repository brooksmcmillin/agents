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
- `events.jsonl` — Events agent (preference learning, event filtering, location constraints, off-topic boundaries)
- `pr.jsonl` — PR/content strategy agent (SEO analysis, content gaps, brand voice, code modification guardrails, off-topic)
- `red-team.jsonl` — Red team penetration tester (target boundaries, detection-only payloads, cleanup, credential safety, off-topic)
- `tasks.jsonl` — Task manager agent (task classification, autonomy tiers, approval requirements, refusal, bulk operations)
- `security-audit.jsonl` — Security audit agent (severity prioritization, remediation commands, trend comparison, multi-host, scope boundaries)
- `sysadmin.jsonl` — System admin agent (network discovery, TLS auditing, credential redaction, subnet boundaries, off-topic)
- `web-analysis.jsonl` — Web analysis agent (crawl-first methodology, task creation, duplicate avoidance, accessibility, prioritization)
- `website-tester.jsonl` — Website tester agent (WCAG auditing, performance benchmarks, report format, crawl-first, scope boundaries)

## Adding a Dataset

1. Create `<agent-name>.jsonl` matching the agent's registry name
2. Add 5-10 test cases covering core capabilities
3. Run: `uv run python -m tests.evaluations.runner --agent <agent-name>`
