# Web Analysis Agent

Website auditing agent that crawls sites with a headless Chromium browser (Playwright) and creates tracked tasks in TaskManager for every significant finding. Covers accessibility, performance, broken links, JavaScript errors, SEO, and content quality.

## Features

- **Full site crawl** — discover all internal pages and map the site structure
- **Accessibility audits** — heading hierarchy, alt text, ARIA landmarks, form labels (WCAG 2.1)
- **Performance audits** — load times, Core Web Vitals (LCP, CLS, TTFB), page weight
- **Broken link detection** — find 4xx/5xx and redirected links across the site
- **JavaScript error capture** — console errors, warnings, and uncaught exceptions
- **Automatic task creation** — files tracked issues in TaskManager with priority and tags
- **Duplicate detection** — checks for existing tasks before creating new ones
- **Screenshots** — visual inspection of any page

## Quick Start

```bash
# Requires remote MCP server for task creation
uv run bin/run-agent web-analysis
```

Give it a URL (and optionally a TaskManager category) and it will run a full audit.

## MCP Tools

### Browser Tools
- `browser_crawl_site` — discover all internal pages on a site
- `browser_screenshot` — capture a page screenshot
- `browser_accessibility_audit` — check heading structure, alt text, ARIA, form labels
- `browser_performance_audit` — measure load times and Core Web Vitals
- `browser_check_links` — find broken and redirected links
- `browser_console_errors` — capture JavaScript errors and warnings

### Analysis Tools
- `analyze_website` — tone, SEO, and engagement scoring
- `fetch_web_content` — read page content as markdown for deep content review

### Task Management (via Remote MCP Server)
- `get_tasks`, `search_tasks` — check for duplicate issues before creating tasks
- `create_task`, `create_tasks` — file findings as tracked tasks with priority and tags

### Memory Tools
- `get_memories`, `save_memory`, `search_memories` — persist findings across sessions

## Task Priority Mapping

| Priority | Severity | Examples |
|----------|----------|---------|
| 9–10 | Critical | Site-breaking issues, security vulnerabilities, major a11y failures |
| 7–8 | High | Performance failures, broken links, WCAG AA violations |
| 5–6 | Medium | SEO issues, minor a11y concerns, performance warnings |
| 1–4 | Low | Style suggestions, minor optimizations, informational findings |

**Tags used:** `accessibility`, `performance`, `seo`, `broken-links`, `javascript-errors`, `content-quality`

## Usage Examples

```
You: Audit https://example.com
Agent: [crawls the site, audits each page for accessibility/performance/links/errors,
        checks for duplicate tasks, creates tasks for each finding, presents summary]

You: Audit https://example.com/checkout with category "website"
Agent: [full audit of the checkout page, files tasks under the "website" category]

You: crawl https://example.com
Agent: [maps all internal pages, reports site structure]
```

## Configuration

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-...

# Required for task creation
MCP_SERVER_URL=https://mcp.brooksmcmillin.com/mcp

# Playwright requires a Chromium installation:
# uv run playwright install chromium
```

## Performance Benchmarks

| Metric | Good | Needs Work | Poor |
|--------|------|------------|------|
| LCP | < 2.5s | < 4s | > 4s |
| CLS | < 0.1 | < 0.25 | > 0.25 |
| TTFB | < 800ms | < 1800ms | > 1800ms |

## Difference from Website Tester

`web-analysis` and `website-tester` both use the same Playwright browser tools, but differ in output:

- **web-analysis** (`web-analysis`): Creates tracked TaskManager tasks for every finding. Best for ongoing quality tracking where findings need to be assigned and resolved.
- **Website Tester** (`website-tester`): Produces a one-time audit report without task creation. Best for ad-hoc spot checks or sites not managed through TaskManager.

## Architecture

Uses `create_simple_agent()` with browser testing tools, web research tools, memory tools, and remote task management tools (via `MCP_SERVER_URL`). The agent always checks for duplicate tasks before filing new ones to avoid cluttering the task board.

## Related Documentation

- [CLAUDE.md](../../CLAUDE.md) — project overview
- [docs/tools.md](../../docs/tools.md) — MCP tools reference
- [agents/website_tester/](../website_tester/) — website auditing without task creation
- [agents/task_manager/](../task_manager/) — interactive task management
