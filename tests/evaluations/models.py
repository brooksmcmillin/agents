"""Data models for the evaluation framework."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path


@dataclass
class EvalCase:
    """A single evaluation test case loaded from a JSONL dataset."""

    input: str
    expected: str
    tags: list[str] = field(default_factory=list)
    expected_tools: list[str] = field(default_factory=list)
    expected_keywords: list[str] = field(default_factory=list)
    max_tokens: int | None = None

    @classmethod
    def from_dict(cls, data: dict) -> EvalCase:
        return cls(
            input=data["input"],
            expected=data["expected"],
            tags=data.get("tags", []),
            expected_tools=data.get("expected_tools", []),
            expected_keywords=data.get("expected_keywords", []),
            max_tokens=data.get("max_tokens"),
        )


@dataclass
class EvalResult:
    """Result of evaluating a single test case."""

    case: EvalCase
    response: str
    score: float
    score_details: dict[str, float] = field(default_factory=dict)
    tools_called: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "input": self.case.input,
            "expected": self.case.expected,
            "tags": self.case.tags,
            "response": self.response,
            "score": self.score,
            "score_details": self.score_details,
            "tools_called": self.tools_called,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "latency_ms": self.latency_ms,
            "error": self.error,
        }


@dataclass
class EvalRun:
    """Aggregated results from a full evaluation run."""

    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    agent_name: str = ""
    variant: str = "default"
    dataset_path: str = ""
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    completed_at: str | None = None
    results: list[EvalResult] = field(default_factory=list)

    @property
    def avg_score(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.score for r in self.results) / len(self.results)

    @property
    def total_tokens(self) -> int:
        return sum(r.input_tokens + r.output_tokens for r in self.results)

    @property
    def avg_latency_ms(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.latency_ms for r in self.results) / len(self.results)

    @property
    def pass_rate(self) -> float:
        """Fraction of results scoring >= 3 (acceptable or better)."""
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if r.score >= 3) / len(self.results)

    def summary(self) -> dict:
        return {
            "run_id": self.run_id,
            "agent_name": self.agent_name,
            "variant": self.variant,
            "dataset": self.dataset_path,
            "num_cases": len(self.results),
            "avg_score": round(self.avg_score, 2),
            "pass_rate": f"{self.pass_rate:.0%}",
            "total_tokens": self.total_tokens,
            "avg_latency_ms": round(self.avg_latency_ms, 0),
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }

    def save(self, output_dir: Path) -> Path:
        """Save run results to a JSON file."""
        output_dir.mkdir(parents=True, exist_ok=True)
        safe_variant = re.sub(r"[^\w\-]", "_", self.variant)
        filename = f"{self.agent_name}_{safe_variant}_{self.run_id}.json"
        path = output_dir / filename
        data = {
            **self.summary(),
            "results": [r.to_dict() for r in self.results],
        }
        path.write_text(json.dumps(data, indent=2))
        return path


def load_dataset(path: Path) -> list[EvalCase]:
    """Load evaluation cases from a JSONL file."""
    cases: list[EvalCase] = []
    with open(path) as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                data = json.loads(line)
                cases.append(EvalCase.from_dict(data))
            except (json.JSONDecodeError, KeyError) as e:
                raise ValueError(f"{path}:{line_num}: invalid test case: {e}") from e
    return cases
