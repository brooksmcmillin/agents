# GitHub Actions Workflows

Automated CI/CD pipelines for the agents project.

## Workflows

### 1. Tests (`ci.yml`)

**Triggers:** Push to `main`/`develop`, Pull Requests

**Jobs:**
- **backend-tests** - Run Python tests with pytest
  - Sets up PostgreSQL service
  - Installs dependencies with `uv`
  - Runs tests with coverage
  - Uploads coverage to Codecov

- **lint** - Code quality checks
  - Python: ruff linter + formatter
  - Type checking: pyright

### 2. Security (`security.yml`)

**Triggers:** Push, Pull Requests, Schedule

**Jobs:**
- Security scanning for vulnerabilities

### 3. Deploy (`deploy.yml`)

**Triggers:** Tags (`v*`)

**Jobs:**
- Build and publish production artifacts
- Create GitHub releases

### 4. Claude Review (`claude-review.yml`)

**Triggers:** Pull Requests

**Jobs:**
- Automated code review gate using Claude

## Required Secrets

| Secret | Required | Description |
|--------|----------|-------------|
| `ANTHROPIC_API_KEY` | Optional | For Claude review gate |
| `CODECOV_TOKEN` | Optional | For coverage reports |

## Local Testing

```bash
# Run all checks locally
.github/workflows/test-local.sh

# Or individually:
uv run pytest -v --cov
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

## Resources

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [pytest Documentation](https://docs.pytest.org/)
