"""Headless browser testing tools using Playwright.

Provides tools for automated website auditing: screenshots, accessibility checks,
performance metrics, broken link detection, and JavaScript console error capture.
Designed for headless operation so an agent can autonomously crawl and evaluate sites.
"""

import base64
import logging
from typing import Any
from urllib.parse import urlparse

from ..security import SSRFTransport, SSRFValidator
from ..utils.tool_decorators import handle_tool_errors

try:
    import playwright  # noqa: F401

    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False


def _require_playwright() -> None:
    """Raise a clear error if playwright is not installed."""
    if not _PLAYWRIGHT_AVAILABLE:
        raise RuntimeError(
            "Playwright is not installed. Install the browser extras with:\n"
            "  uv sync --group browser\n"
            "  uv run playwright install chromium"
        )


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_BROWSER_TIMEOUT_MS = 30_000  # per-page navigation timeout
_MAX_CRAWL_PAGES = 20  # safety cap for site crawl


def _validate_url(url: str) -> str:
    """Validate a URL against SSRF rules and return the safe final URL."""
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"Invalid URL (must start with http:// or https://): {url}")
    is_safe, reason = SSRFValidator.is_safe_url(url)
    if not is_safe:
        raise ValueError(f"URL rejected for security reasons: {reason}")
    return url


async def _new_page(browser_context: Any) -> Any:
    """Create a new page with sensible defaults."""
    page = await browser_context.new_page()
    page.set_default_navigation_timeout(_BROWSER_TIMEOUT_MS)
    return page


# ---------------------------------------------------------------------------
# Tool: browser_screenshot
# ---------------------------------------------------------------------------


@handle_tool_errors(operation="browser screenshot")
async def browser_screenshot(
    url: str,
    full_page: bool = True,
    viewport_width: int = 1280,
    viewport_height: int = 720,
) -> dict[str, Any]:
    """Take a screenshot of a webpage using a headless browser.

    Args:
        url: The URL to screenshot.
        full_page: Capture the full scrollable page (default True).
        viewport_width: Browser viewport width in pixels.
        viewport_height: Browser viewport height in pixels.

    Returns:
        Dictionary with base64-encoded PNG screenshot and page metadata.
    """
    _require_playwright()
    from playwright.async_api import async_playwright

    url = _validate_url(url)
    logger.info(f"Taking screenshot of {url}")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            context = await browser.new_context(
                viewport={"width": viewport_width, "height": viewport_height},
                user_agent="AgentFramework-WebsiteTester/1.0",
            )
            page = await _new_page(context)
            await page.goto(url, wait_until="networkidle")

            title = await page.title()
            screenshot_bytes = await page.screenshot(full_page=full_page)
            encoded = base64.b64encode(screenshot_bytes).decode()
        finally:
            await browser.close()

    result: dict[str, Any] = {
        "url": url,
        "title": title,
        "viewport": f"{viewport_width}x{viewport_height}",
        "full_page": full_page,
        "screenshot_size_bytes": len(screenshot_bytes),
    }

    # Omit base64 data if it would be too large (truncated base64 is useless)
    if len(encoded) > 50_000:
        result["screenshot_base64"] = None
        result["note"] = (
            f"Screenshot base64 omitted ({len(encoded):,} chars). "
            "Image too large to include in tool result."
        )
    else:
        result["screenshot_base64"] = encoded

    return result


# ---------------------------------------------------------------------------
# Tool: browser_accessibility_audit
# ---------------------------------------------------------------------------


@handle_tool_errors(operation="browser accessibility audit")
async def browser_accessibility_audit(url: str) -> dict[str, Any]:
    """Run an accessibility audit on a webpage.

    Checks heading hierarchy, image alt text, form labels, ARIA landmarks,
    link text quality, color-contrast indicators, and keyboard focus order.

    Args:
        url: The URL to audit.

    Returns:
        Dictionary with categorized accessibility findings and a summary score.
    """
    _require_playwright()
    from playwright.async_api import async_playwright

    url = _validate_url(url)
    logger.info(f"Running accessibility audit on {url}")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            context = await browser.new_context(user_agent="AgentFramework-WebsiteTester/1.0")
            page = await _new_page(context)
            await page.goto(url, wait_until="networkidle")

            title = await page.title()

            # Run all checks inside the browser
            results = await page.evaluate("""() => {
            const findings = {
                headings: [],
                images: [],
                forms: [],
                aria: [],
                links: [],
                misc: [],
            };
            let issues = 0;

            // --- Heading hierarchy ---
            const headings = document.querySelectorAll('h1,h2,h3,h4,h5,h6');
            let prevLevel = 0;
            const headingList = [];
            headings.forEach(h => {
                const level = parseInt(h.tagName[1]);
                headingList.push({level, text: h.textContent.trim().slice(0, 80)});
                if (level > prevLevel + 1 && prevLevel !== 0) {
                    findings.headings.push(
                        `Heading level skipped: h${prevLevel} -> h${level} ("${h.textContent.trim().slice(0, 40)}")`
                    );
                    issues++;
                }
                prevLevel = level;
            });
            const h1Count = document.querySelectorAll('h1').length;
            if (h1Count === 0) {
                findings.headings.push('No h1 element found');
                issues++;
            } else if (h1Count > 1) {
                findings.headings.push(`Multiple h1 elements found (${h1Count})`);
                issues++;
            }

            // --- Images ---
            document.querySelectorAll('img').forEach(img => {
                const alt = img.getAttribute('alt');
                const src = img.src || img.getAttribute('data-src') || '(unknown)';
                const shortSrc = src.slice(0, 60);
                if (alt === null) {
                    findings.images.push(`Missing alt attribute: ${shortSrc}`);
                    issues++;
                } else if (alt.trim() === '') {
                    // Empty alt is OK for decorative images, but flag it
                    findings.images.push(`Empty alt (decorative?): ${shortSrc}`);
                }
            });

            // --- Form labels ---
            document.querySelectorAll('input,select,textarea').forEach(el => {
                if (el.type === 'hidden' || el.type === 'submit' || el.type === 'button') return;
                const id = el.id;
                const hasLabel = id && document.querySelector(`label[for="${id}"]`);
                const hasAriaLabel = el.getAttribute('aria-label') || el.getAttribute('aria-labelledby');
                const wrappedInLabel = el.closest('label');
                if (!hasLabel && !hasAriaLabel && !wrappedInLabel) {
                    findings.forms.push(
                        `Input without label: <${el.tagName.toLowerCase()} type="${el.type || 'text'}" name="${el.name || ''}">`
                    );
                    issues++;
                }
            });

            // --- ARIA landmarks ---
            const landmarks = document.querySelectorAll(
                '[role="banner"],[role="navigation"],[role="main"],[role="contentinfo"],header,nav,main,footer'
            );
            if (landmarks.length === 0) {
                findings.aria.push('No ARIA landmarks or semantic landmark elements found');
                issues++;
            }
            const mainLandmarks = document.querySelectorAll('[role="main"],main');
            if (mainLandmarks.length === 0) {
                findings.aria.push('No <main> or role="main" landmark found');
                issues++;
            }

            // --- Link text quality ---
            document.querySelectorAll('a').forEach(a => {
                const text = a.textContent.trim().toLowerCase();
                const ariaLabel = a.getAttribute('aria-label');
                if (!text && !ariaLabel && !a.querySelector('img[alt]')) {
                    findings.links.push(`Empty link text: href="${(a.href || '').slice(0, 60)}"`);
                    issues++;
                } else if (['click here', 'here', 'read more', 'more', 'link'].includes(text) && !ariaLabel) {
                    findings.links.push(`Non-descriptive link text "${text}": href="${(a.href || '').slice(0, 60)}"`);
                    issues++;
                }
            });

            // --- Misc: lang attribute, skip links, viewport meta ---
            if (!document.documentElement.lang) {
                findings.misc.push('Missing lang attribute on <html>');
                issues++;
            }
            const skipLink = document.querySelector('a[href^="#main"],a[href^="#content"],.skip-link,.skip-nav');
            if (!skipLink) {
                findings.misc.push('No skip-navigation link detected');
                issues++;
            }
            const viewport = document.querySelector('meta[name="viewport"]');
            if (!viewport) {
                findings.misc.push('No viewport meta tag');
                issues++;
            } else {
                const content = viewport.getAttribute('content') || '';
                if (content.includes('user-scalable=no') || content.includes('maximum-scale=1')) {
                    findings.misc.push('Viewport meta prevents user zooming');
                    issues++;
                }
            }

            return {findings, issues, headingOutline: headingList};
        }""")
        finally:
            await browser.close()

    total_issues = results["issues"]
    # Simple score: 100 minus 5 per issue, floor at 0
    score = max(0, 100 - total_issues * 5)

    # Cap each findings category to prevent oversized results
    _MAX_FINDINGS_PER_CATEGORY = 25
    findings = results["findings"]
    for category, items in findings.items():
        if isinstance(items, list) and len(items) > _MAX_FINDINGS_PER_CATEGORY:
            omitted = len(items) - _MAX_FINDINGS_PER_CATEGORY
            findings[category] = items[:_MAX_FINDINGS_PER_CATEGORY] + [f"... and {omitted} more"]

    return {
        "url": url,
        "title": title,
        "accessibility_score": score,
        "total_issues": total_issues,
        "findings": findings,
        "heading_outline": results["headingOutline"],
    }


# ---------------------------------------------------------------------------
# Tool: browser_performance_audit
# ---------------------------------------------------------------------------


@handle_tool_errors(operation="browser performance audit")
async def browser_performance_audit(url: str) -> dict[str, Any]:
    """Collect performance metrics for a webpage.

    Uses the Navigation Timing API and resource counting to report load times,
    page weight, and resource breakdown.

    Args:
        url: The URL to audit.

    Returns:
        Dictionary with timing metrics, resource counts, and page weight.
    """
    _require_playwright()
    from playwright.async_api import async_playwright

    url = _validate_url(url)
    logger.info(f"Running performance audit on {url}")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            context = await browser.new_context(user_agent="AgentFramework-WebsiteTester/1.0")
            page = await _new_page(context)

            # Collect network requests for resource breakdown
            resources: list[dict[str, Any]] = []

            async def _on_response(response: Any) -> None:
                try:
                    size = int(response.headers.get("content-length", 0))
                except (ValueError, TypeError):
                    size = 0
                content_type = response.headers.get("content-type", "")
                resources.append(
                    {
                        "url": response.url[:120],
                        "status": response.status,
                        "content_type": content_type.split(";")[0].strip(),
                        "size": size,
                    }
                )

            page.on("response", _on_response)

            await page.goto(url, wait_until="networkidle")
            title = await page.title()

            # Navigation Timing API
            timing = await page.evaluate("""() => {
                const p = performance.getEntriesByType('navigation')[0] || {};
                return {
                    dns_ms: Math.round((p.domainLookupEnd || 0) - (p.domainLookupStart || 0)),
                    tcp_ms: Math.round((p.connectEnd || 0) - (p.connectStart || 0)),
                    ttfb_ms: Math.round((p.responseStart || 0) - (p.requestStart || 0)),
                    download_ms: Math.round((p.responseEnd || 0) - (p.responseStart || 0)),
                    dom_interactive_ms: Math.round(p.domInteractive || 0),
                    dom_complete_ms: Math.round(p.domComplete || 0),
                    load_event_ms: Math.round(p.loadEventEnd || 0),
                    transfer_size: p.transferSize || 0,
                    encoded_body_size: p.encodedBodySize || 0,
                    decoded_body_size: p.decodedBodySize || 0,
                };
            }""")

            # Core Web Vitals approximations
            cwv = await page.evaluate("""() => {
                const lcp = performance.getEntriesByType('largest-contentful-paint');
                const lcpValue = lcp.length ? Math.round(lcp[lcp.length - 1].startTime) : null;
                const cls = performance.getEntriesByType('layout-shift')
                    .filter(e => !e.hadRecentInput)
                    .reduce((sum, e) => sum + e.value, 0);
                return {
                    largest_contentful_paint_ms: lcpValue,
                    cumulative_layout_shift: Math.round(cls * 1000) / 1000,
                };
            }""")
        finally:
            await browser.close()

    # Categorize resources
    categories: dict[str, dict[str, int]] = {}
    for r in resources:
        ct = r["content_type"]
        if "javascript" in ct or "ecmascript" in ct:
            cat = "javascript"
        elif "css" in ct:
            cat = "css"
        elif ct.startswith("image/"):
            cat = "images"
        elif ct.startswith("font/") or "font" in ct:
            cat = "fonts"
        elif "html" in ct:
            cat = "html"
        else:
            cat = "other"
        if cat not in categories:
            categories[cat] = {"count": 0, "total_bytes": 0}
        categories[cat]["count"] += 1
        categories[cat]["total_bytes"] += r["size"]

    total_bytes = sum(c["total_bytes"] for c in categories.values())

    return {
        "url": url,
        "title": title,
        "timing": timing,
        "core_web_vitals": cwv,
        "total_requests": len(resources),
        "total_transfer_bytes": total_bytes,
        "total_transfer_kb": round(total_bytes / 1024, 1),
        "resource_breakdown": categories,
    }


# ---------------------------------------------------------------------------
# Tool: browser_console_errors
# ---------------------------------------------------------------------------


@handle_tool_errors(operation="browser console errors")
async def browser_console_errors(url: str) -> dict[str, Any]:
    """Capture JavaScript console errors and warnings from a webpage.

    Args:
        url: The URL to load.

    Returns:
        Dictionary with lists of console errors, warnings, and uncaught exceptions.
    """
    _require_playwright()
    from playwright.async_api import async_playwright

    url = _validate_url(url)
    logger.info(f"Capturing console errors on {url}")

    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    exceptions: list[str] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            context = await browser.new_context(user_agent="AgentFramework-WebsiteTester/1.0")
            page = await _new_page(context)

            def _on_console(msg: Any) -> None:
                entry = {"text": msg.text[:500], "url": str(msg.location.get("url", ""))[:120]}
                if msg.type == "error":
                    errors.append(entry)
                elif msg.type == "warning":
                    warnings.append(entry)

            def _on_pageerror(exc: Any) -> None:
                exceptions.append(str(exc)[:500])

            page.on("console", _on_console)
            page.on("pageerror", _on_pageerror)

            await page.goto(url, wait_until="networkidle")
            title = await page.title()

            # Scroll down to trigger lazy-loaded content errors
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(1000)
        finally:
            await browser.close()

    # Cap lists to prevent oversized results; preserve true counts
    _MAX_CONSOLE_ENTRIES = 50
    return {
        "url": url,
        "title": title,
        "errors": errors[:_MAX_CONSOLE_ENTRIES],
        "error_count": len(errors),
        "errors_omitted": max(0, len(errors) - _MAX_CONSOLE_ENTRIES),
        "warnings": warnings[:_MAX_CONSOLE_ENTRIES],
        "warning_count": len(warnings),
        "warnings_omitted": max(0, len(warnings) - _MAX_CONSOLE_ENTRIES),
        "uncaught_exceptions": exceptions[:_MAX_CONSOLE_ENTRIES],
        "exception_count": len(exceptions),
        "exceptions_omitted": max(0, len(exceptions) - _MAX_CONSOLE_ENTRIES),
    }


# ---------------------------------------------------------------------------
# Tool: browser_check_links
# ---------------------------------------------------------------------------


@handle_tool_errors(operation="browser check links")
async def browser_check_links(url: str, same_origin_only: bool = True) -> dict[str, Any]:
    """Check for broken links on a webpage.

    Extracts all <a href> links, then verifies each with a HEAD request.

    Args:
        url: The page to scan for links.
        same_origin_only: Only check links on the same origin (default True).

    Returns:
        Dictionary with broken, redirected, and healthy link counts plus details.
    """
    _require_playwright()
    from playwright.async_api import async_playwright

    url = _validate_url(url)
    logger.info(f"Checking links on {url}")

    parsed_origin = urlparse(url)
    origin = f"{parsed_origin.scheme}://{parsed_origin.netloc}"

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            context = await browser.new_context(user_agent="AgentFramework-WebsiteTester/1.0")
            page = await _new_page(context)
            await page.goto(url, wait_until="networkidle")

            title = await page.title()

            # Extract all links
            raw_links: list[dict[str, str]] = await page.evaluate("""() => {
                return Array.from(document.querySelectorAll('a[href]')).map(a => ({
                    href: a.href,
                    text: a.textContent.trim().slice(0, 80),
                }));
            }""")
        finally:
            await browser.close()

    # Deduplicate and filter
    seen: set[str] = set()
    links_to_check: list[dict[str, str]] = []
    for link in raw_links:
        href = link["href"]
        if href in seen or href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        seen.add(href)
        if same_origin_only and not (href.startswith(origin + "/") or href == origin):
            continue
        # SSRF-validate each extracted link before checking it
        safe, _ = SSRFValidator.is_safe_url(href)
        if not safe:
            continue
        links_to_check.append(link)

    # Check each link (HEAD request with httpx)
    import httpx

    broken: list[dict[str, Any]] = []
    redirected: list[dict[str, Any]] = []
    healthy = 0

    async with httpx.AsyncClient(
        transport=SSRFTransport(),
        timeout=10.0,
        follow_redirects=False,
    ) as client:
        for link in links_to_check[:100]:  # cap at 100 links
            href = link["href"]
            try:
                resp = await client.head(href)
                if resp.status_code >= 400:
                    broken.append(
                        {
                            "url": href,
                            "text": link["text"],
                            "status": resp.status_code,
                        }
                    )
                elif 300 <= resp.status_code < 400:
                    redirected.append(
                        {
                            "url": href,
                            "text": link["text"],
                            "status": resp.status_code,
                            "location": resp.headers.get("location", "")[:200],
                        }
                    )
                else:
                    healthy += 1
            except httpx.RequestError as exc:
                broken.append(
                    {
                        "url": href,
                        "text": link["text"],
                        "error": str(exc)[:200],
                    }
                )

    # Cap redirected list (broken links are typically few, redirects can be many)
    _MAX_REDIRECTED = 20
    return {
        "url": url,
        "title": title,
        "total_links_found": len(raw_links),
        "links_checked": len(links_to_check[:100]),
        "same_origin_only": same_origin_only,
        "healthy_count": healthy,
        "broken": broken,
        "broken_count": len(broken),
        "redirected": redirected[:_MAX_REDIRECTED],
        "redirected_count": len(redirected),
        "redirected_omitted": max(0, len(redirected) - _MAX_REDIRECTED),
    }


# ---------------------------------------------------------------------------
# Tool: browser_crawl_site
# ---------------------------------------------------------------------------


@handle_tool_errors(operation="browser crawl site")
async def browser_crawl_site(
    url: str,
    max_pages: int = 10,
) -> dict[str, Any]:
    """Crawl a website starting from a URL and discover internal pages.

    Follows same-origin links up to *max_pages*. Returns a list of discovered
    pages with their titles, status codes, and outbound link counts.

    Args:
        url: The starting URL for the crawl.
        max_pages: Maximum pages to visit (capped at 20).

    Returns:
        Dictionary with a list of discovered pages and crawl summary.
    """
    _require_playwright()
    from playwright.async_api import async_playwright

    url = _validate_url(url)
    max_pages = min(max_pages, _MAX_CRAWL_PAGES)
    logger.info(f"Crawling site {url} (max {max_pages} pages)")

    parsed_origin = urlparse(url)
    origin = f"{parsed_origin.scheme}://{parsed_origin.netloc}"

    visited: dict[str, dict[str, Any]] = {}
    queue: list[str] = [url]

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            context = await browser.new_context(user_agent="AgentFramework-WebsiteTester/1.0")

            while queue and len(visited) < max_pages:
                current = queue.pop(0)
                if current in visited:
                    continue

                # Normalize trailing slash for dedup
                normalized = current.rstrip("/")
                if any(v.rstrip("/") == normalized for v in visited):
                    continue

                page = await _new_page(context)
                try:
                    response = await page.goto(current, wait_until="networkidle")
                    status = response.status if response else 0
                    title = await page.title()

                    # Extract same-origin links (use origin + "/" to prevent subdomain bypass)
                    links: list[str] = await page.evaluate(
                        """(origin) => {
                        return Array.from(new Set(
                            Array.from(document.querySelectorAll('a[href]'))
                                .map(a => a.href.split('#')[0].split('?')[0])
                                .filter(href => href.startsWith(origin + '/') || href === origin)
                        ));
                    }""",
                        origin,
                    )

                    visited[current] = {
                        "url": current,
                        "title": title,
                        "status": status,
                        "outbound_links": len(links),
                    }

                    for link in links:
                        if link not in visited and link not in queue:
                            # SSRF-validate each discovered URL before queueing
                            safe, _ = SSRFValidator.is_safe_url(link)
                            if safe:
                                queue.append(link)

                except Exception as e:
                    visited[current] = {
                        "url": current,
                        "title": "(error)",
                        "status": 0,
                        "error": str(e)[:200],
                        "outbound_links": 0,
                    }
                finally:
                    await page.close()
        finally:
            await browser.close()

    pages = list(visited.values())

    return {
        "start_url": url,
        "origin": origin,
        "pages_visited": len(pages),
        "max_pages": max_pages,
        "pages": pages,
    }


# ---------------------------------------------------------------------------
# Tool schemas for MCP server auto-registration
# ---------------------------------------------------------------------------

TOOL_SCHEMAS = [
    {
        "name": "browser_screenshot",
        "description": (
            "Take a screenshot of a webpage using a headless Chromium browser. "
            "Returns a base64-encoded PNG image. Useful for visual inspection of "
            "page layout, design issues, and rendering problems."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to screenshot (must start with http:// or https://)",
                },
                "full_page": {
                    "type": "boolean",
                    "default": True,
                    "description": "Capture the full scrollable page (default: true)",
                },
                "viewport_width": {
                    "type": "integer",
                    "default": 1280,
                    "minimum": 320,
                    "maximum": 3840,
                    "description": "Browser viewport width in pixels",
                },
                "viewport_height": {
                    "type": "integer",
                    "default": 720,
                    "minimum": 240,
                    "maximum": 2160,
                    "description": "Browser viewport height in pixels",
                },
            },
            "required": ["url"],
        },
        "handler": browser_screenshot,
    },
    {
        "name": "browser_accessibility_audit",
        "description": (
            "Run an accessibility audit on a webpage using a headless browser. "
            "Checks heading hierarchy, image alt text, form labels, ARIA landmarks, "
            "link text quality, lang attribute, skip-navigation links, and viewport meta. "
            "Returns categorized findings and an overall score."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to audit (must start with http:// or https://)",
                },
            },
            "required": ["url"],
        },
        "handler": browser_accessibility_audit,
    },
    {
        "name": "browser_performance_audit",
        "description": (
            "Collect performance metrics for a webpage using the Navigation Timing API. "
            "Reports DNS, TCP, TTFB, DOM load times, approximate Core Web Vitals (LCP, CLS), "
            "total page weight, request count, and a resource breakdown by category "
            "(JS, CSS, images, fonts, etc.)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to audit (must start with http:// or https://)",
                },
            },
            "required": ["url"],
        },
        "handler": browser_performance_audit,
    },
    {
        "name": "browser_console_errors",
        "description": (
            "Capture JavaScript console errors, warnings, and uncaught exceptions "
            "from a webpage. Loads the page in a headless browser, scrolls to trigger "
            "lazy content, and records all console output."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to load (must start with http:// or https://)",
                },
            },
            "required": ["url"],
        },
        "handler": browser_console_errors,
    },
    {
        "name": "browser_check_links",
        "description": (
            "Check for broken links on a webpage. Extracts all <a href> links, "
            "then verifies each with a HEAD request. Reports broken (4xx/5xx), "
            "redirected (3xx), and healthy links."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The page to scan for links (must start with http:// or https://)",
                },
                "same_origin_only": {
                    "type": "boolean",
                    "default": True,
                    "description": "Only check links on the same origin (default: true)",
                },
            },
            "required": ["url"],
        },
        "handler": browser_check_links,
    },
    {
        "name": "browser_crawl_site",
        "description": (
            "Crawl a website starting from a URL and discover internal pages. "
            "Follows same-origin links up to max_pages. Returns discovered pages "
            "with titles, status codes, and outbound link counts. Useful for mapping "
            "a site before running audits on individual pages."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The starting URL for the crawl (must start with http:// or https://)",
                },
                "max_pages": {
                    "type": "integer",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 20,
                    "description": "Maximum number of pages to visit (capped at 20)",
                },
            },
            "required": ["url"],
        },
        "handler": browser_crawl_site,
    },
]
