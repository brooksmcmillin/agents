# GitHub Actions Workflows

Automated CI/CD pipelines for the agents project.

## Workflows

### 1. CI (`ci.yml`)

**Triggers:** Push to `main`, Pull Requests, Merge groups

**Jobs:**
- **Lint** — ruff check + format
- **Dependency Audit** — pip-audit + safety
- **Unit Tests** (3.12, 3.13) — `tests/unit/` + `packages/agent-framework/tests/`
- **Database Tests** (3.12, 3.13) — PostgreSQL-dependent tests (conversation store, memory store, API conversations)
- **Eval Dataset Validation** — validates eval datasets and coverage
- **Prompt Change Gate** — checks eval baselines when prompts change (PRs only)
- **Rust Collector** — clippy, tests, and cargo audit for `security_audit/collector-rs`
- **Integration Tests** — starts API server with PostgreSQL, tests endpoints

### 2. Security (`security.yml`)

**Triggers:** Push, Pull Requests, Schedule

**Jobs:**
- CodeQL analysis, Semgrep, Trivy, dependency review

### 3. Claude Review (`claude-review.yml`)

**Triggers:** Pull Requests

**Jobs:**
- Code review, security review, and review gate

### 4. Deploy (`deploy.yml`)

**Triggers:** Tags (`v*`)

**Jobs:**
- Run unit tests, create release archive, publish GitHub release

## Local Testing

```bash
# Run all local checks
.github/workflows/test-local.sh

# Or individually:
uv run pytest tests/unit/ -v
uv run ruff check .
uv run ruff format --check .
```
