"""Web analysis agent with automatic task creation for issues found.

Crawls websites using a headless Playwright browser, audits them for
accessibility, performance, broken links, JavaScript errors, SEO, and
content quality, then creates tracked tasks in TaskManager for remediation.
"""

from shared import BROWSER_TESTING_TOOLS, MEMORY_TOOLS, WEB_RESEARCH_TOOLS, create_simple_agent

from .prompts import SYSTEM_PROMPT, USER_GREETING_PROMPT

WebAnalysisAgent = create_simple_agent(
    name="WebAnalysisAgent",
    system_prompt=SYSTEM_PROMPT,
    greeting=USER_GREETING_PROMPT,
    allowed_tools=(BROWSER_TESTING_TOOLS + WEB_RESEARCH_TOOLS + MEMORY_TOOLS),
)

if __name__ == "__main__":
    import sys

    print("Direct execution is not supported. Use bin/run-agent instead:")
    print("  uv run bin/run-agent web-analysis")
    sys.exit(1)
