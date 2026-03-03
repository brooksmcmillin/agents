# Website Tester Agent

Automated website quality analyst using a headless Chromium browser (Playwright). Crawls sites and audits them for accessibility, performance, broken links, JavaScript errors, and SEO issues without any manual interaction.

## Features

- **Full site crawl** — discover all internal pages and map the site structure
- **Accessibility audits** — heading hierarchy, alt text, ARIA landmarks, form labels, link text quality (WCAG 2.1)
- **Performance audits** — load times, Core Web Vitals (LCP, CLS, TTFB), page weight, resource breakdown
- **Broken link detection** — find 4xx/5xx and redirected links across the site
- **JavaScript error capture** — console errors, warnings, and uncaught exceptions
- **Screenshots** — visual inspection of any page
- **SEO and content analysis** — tone, meta tags, heading structure, engagement scoring

## Quick Start

```bash
uv run bin/run-agent website-tester
```

Then give it a URL: "Audit https://example.com"

## MCP Tools

- `browser_crawl_site` — discover all internal pages on a site
- `browser_screenshot` — capture a page screenshot
- `browser_accessibility_audit` — check heading structure, alt text, ARIA, form labels
- `browser_performance_audit` — measure load times and Core Web Vitals
- `browser_check_links` — find broken and redirected links
- `browser_console_errors` — capture JavaScript errors and warnings
- `analyze_website` — tone, SEO, and engagement scoring
- `fetch_web_content` — read page content as markdown for deep content review
- `get_memories`, `save_memory`, `search_memories` — track findings across sessions

## Usage Examples

```
You: Audit https://example.com
Agent: [crawls the site, audits each page for accessibility/performance/links/errors,
        captures screenshots, presents prioritized findings with recommendations]

You: crawl https://example.com
Agent: [maps all internal pages, reports site structure]

You: check links on https://example.com
Agent: [scans all internal links for 4xx/5xx responses]

You: audit https://example.com/checkout
Agent: [full audit of a specific page: accessibility, performance, JS errors, SEO]
```

## Performance Benchmarks

The agent evaluates performance against these thresholds:

| Metric | Good | Needs Work | Poor |
|--------|------|------------|------|
| LCP | < 2.5s | < 4s | > 4s |
| CLS | < 0.1 | < 0.25 | > 0.25 |
| TTFB | < 800ms | < 1800ms | > 1800ms |

## Configuration

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-...

# Playwright requires a Chromium installation:
# uv run playwright install chromium
```

## Architecture

Uses `create_simple_agent()` with browser testing tools, web research tools, and memory tools. The Playwright browser tools run headless Chromium to perform real browser-based testing, capturing actual render performance and JavaScript execution rather than static HTML analysis.

## Related Documentation

- [CLAUDE.md](../../CLAUDE.md) — project overview
- [docs/tools.md](../../docs/tools.md) — MCP tools reference
- [agents/red_team/](../red_team/) — dynamic security testing of web applications
