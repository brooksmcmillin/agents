"""Automated website testing agent using headless Playwright browser.

Crawls websites and audits them for accessibility, performance, broken links,
JavaScript errors, SEO, and content quality — all without manual interaction.
"""

from shared import MEMORY_TOOLS, WEB_RESEARCH_TOOLS, create_simple_agent

from .prompts import SYSTEM_PROMPT, USER_GREETING_PROMPT

BROWSER_TESTING_TOOLS = [
    "browser_screenshot",
    "browser_accessibility_audit",
    "browser_performance_audit",
    "browser_console_errors",
    "browser_check_links",
    "browser_crawl_site",
]

WebsiteTesterAgent = create_simple_agent(
    name="WebsiteTesterAgent",
    system_prompt=SYSTEM_PROMPT,
    greeting=USER_GREETING_PROMPT,
    allowed_tools=(BROWSER_TESTING_TOOLS + WEB_RESEARCH_TOOLS + MEMORY_TOOLS),
)

if __name__ == "__main__":
    import sys

    print("Direct execution is not supported. Use bin/run-agent instead:")
    print("  uv run bin/run-agent website-tester")
    sys.exit(1)
