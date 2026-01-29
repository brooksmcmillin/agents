# GitHub Actions Workflows

Automated CI/CD pipelines for the Agents Web UI project.

## Workflows

### 1. Tests (`tests.yml`)

**Triggers:** Push to `main`/`develop`, Pull Requests

**Jobs:**
- **backend-tests** - Run Python tests with pytest
  - Sets up PostgreSQL service
  - Installs dependencies with `uv`
  - Runs backend API tests with coverage
  - Uploads coverage to Codecov

- **frontend-tests** - Run TypeScript tests with Vitest
  - Installs dependencies with npm
  - Runs frontend unit/component tests
  - Generates coverage report
  - Uploads coverage to Codecov

- **build-frontend** - Verify production build works
  - Builds frontend with Vite
  - Verifies output files exist
  - Uploads build artifacts (7 day retention)

- **lint** - Code quality checks
  - Python: ruff linter + formatter
  - TypeScript: ESLint

- **type-check** - TypeScript type checking
  - Runs `tsc --noEmit` to catch type errors

**Status Badge:**
```markdown
![Tests](https://github.com/YOUR_USERNAME/agents/workflows/Tests/badge.svg)
```

### 2. Integration Tests (`integration.yml`)

**Triggers:** Push to `main`, Pull Requests to `main`, Manual

**Jobs:**
- **integration-tests** - Full integration tests
  - Sets up PostgreSQL
  - Builds frontend
  - Starts API server
  - Tests API endpoints with curl
  - Runs database integration tests

- **e2e-tests** - End-to-end tests (placeholder)
  - Currently disabled
  - Ready for Playwright integration

**Status Badge:**
```markdown
![Integration](https://github.com/YOUR_USERNAME/agents/workflows/Integration%20Tests/badge.svg)
```

### 3. Deploy (`deploy.yml`)

**Triggers:** Push to `main`, Tags (`v*`)

**Jobs:**
- **build-and-publish** - Build production artifacts
  - Builds optimized frontend bundle
  - Creates build metadata
  - Uploads artifacts (30 day retention)
  - Creates GitHub release on tags
  - Attaches tarball to release

**Status Badge:**
```markdown
![Deploy](https://github.com/YOUR_USERNAME/agents/workflows/Deploy/badge.svg)
```

## Required Secrets

Configure these in **Settings → Secrets and variables → Actions**:

| Secret | Required | Description |
|--------|----------|-------------|
| `ANTHROPIC_API_KEY` | Optional | For testing agent functionality (not required for most tests) |
| `CODECOV_TOKEN` | Optional | For uploading coverage reports to Codecov |

## Workflow Status

```
┌─────────────┐
│ Push/PR     │
└──────┬──────┘
       │
       ├──────────────────────┬─────────────────┬────────────────┐
       ▼                      ▼                 ▼                ▼
┌──────────────┐    ┌──────────────┐   ┌──────────────┐  ┌──────────────┐
│ Backend      │    │ Frontend     │   │ Build        │  │ Lint         │
│ Tests        │    │ Tests        │   │ Frontend     │  │ & Type Check │
│ (pytest)     │    │ (vitest)     │   │ (vite)       │  │              │
└──────┬───────┘    └──────┬───────┘   └──────┬───────┘  └──────┬───────┘
       │                   │                  │                 │
       └───────────────────┴──────────────────┴─────────────────┘
                                    │
                                    ▼
                            ┌──────────────┐
                            │ All Checks   │
                            │ Pass ✅      │
                            └──────────────┘
```

## Local Testing

Run the same checks locally before pushing:

```bash
# Backend tests
uv run pytest agents/api/test_server.py -v --cov

# Frontend tests
cd agents/webui/frontend
npm test -- --run
npm run lint
npx tsc --noEmit

# Build check
npm run build

# Python linting
uv run ruff check .
uv run ruff format --check .
```

## Continuous Integration Best Practices

1. **Run tests locally first** - Don't rely on CI to catch issues
2. **Keep tests fast** - Current runtime: <2min total
3. **Fix failing tests immediately** - Don't let them linger
4. **Review coverage reports** - Maintain >80% backend, >70% frontend
5. **Use draft PRs** - For work-in-progress that shouldn't block CI

## Caching Strategy

**Python dependencies:**
- Cached by uv hash of `pyproject.toml`
- Stored in `~/.cache/uv`

**Node dependencies:**
- Cached by npm using `package-lock.json` hash
- Stored in npm cache directory

**Benefits:**
- Faster CI runs (30-60s faster)
- Reduced network usage
- More reliable builds

## Troubleshooting

### Tests pass locally but fail in CI

**Common causes:**
1. **Different Python/Node versions** - Check versions match
2. **Missing dependencies** - Ensure `package-lock.json` is committed
3. **Environment variables** - Check secrets are configured
4. **Timezone issues** - Use UTC in date tests
5. **File paths** - Use path.join for cross-platform compatibility

### Build artifacts not uploaded

**Check:**
- Build completed successfully
- `dist/` directory was created
- Upload artifact step didn't fail

### Coverage upload fails

**Solutions:**
- Check `CODECOV_TOKEN` is configured (optional)
- Set `fail_ci_if_error: false` in workflow (already done)
- Coverage upload is non-blocking

## Monitoring

**View workflow runs:**
- Go to **Actions** tab in GitHub
- Click on workflow name
- View logs for each job

**Status checks:**
- Required checks appear on PRs
- Can't merge until checks pass
- Can override in emergency (admin only)

## Future Enhancements

**Planned:**
- [ ] E2E tests with Playwright
- [ ] Visual regression tests
- [ ] Performance testing
- [ ] Security scanning (Dependabot, Snyk)
- [ ] Automated dependency updates

**Nice to have:**
- [ ] Parallel test execution
- [ ] Test result annotations
- [ ] Slack/Discord notifications
- [ ] Auto-merge for passing Dependabot PRs

## Resources

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [pytest Documentation](https://docs.pytest.org/)
- [Vitest Documentation](https://vitest.dev/)
- [Codecov Documentation](https://docs.codecov.com/)
