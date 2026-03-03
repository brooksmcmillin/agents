"""Web Analysis Agent.

Automated website auditing agent that crawls sites, runs accessibility,
performance, and SEO audits using a headless Playwright browser, then
creates tracked tasks in TaskManager for issues found.

Features:
- Headless Chromium browser for crawling, screenshots, and auditing
- Accessibility audit (WCAG 2.1 compliance)
- Performance audit (Core Web Vitals)
- Broken link detection
- JavaScript error capture
- SEO and content quality analysis
- Automatic task creation for trackable remediation
"""

__version__ = "0.1.0"
