"""Web content analysis tool.

This tool fetches and analyzes web content for tone, style, SEO, and engagement.
Uses real web scraping with BeautifulSoup and text analysis.
"""

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import httpx
from bs4 import BeautifulSoup

from ..security import SSRFValidator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HTTPConfig:
    """HTTP request settings for web fetching."""

    timeout_seconds: float = 10.0
    max_redirects: int = 5


@dataclass(frozen=True)
class ReadabilityConfig:
    """Flesch Reading Ease formula coefficients and level thresholds."""

    # Formula coefficients
    intercept: float = 206.835
    sentence_coeff: float = 1.015
    syllable_coeff: float = 84.6

    # Reading level thresholds (Flesch score)
    level_elementary: int = 90
    level_middle_school: int = 70
    level_high_school: int = 60
    level_college: int = 50

    # Words per minute for reading time estimates
    reading_speed_wpm: int = 200


@dataclass(frozen=True)
class ToneConfig:
    """Tone analysis thresholds and settings."""

    # Formality thresholds (average word length in characters)
    formal_threshold: float = 5.5
    moderate_threshold: float = 4.5

    # Emotional marker normalization (expected markers per N words)
    marker_words_per_expected: int = 100

    # Recommendation thresholds
    long_sentence_threshold: int = 25
    low_enthusiasm_threshold: float = 0.3
    high_authority_threshold: float = 0.8

    # Sample excerpt settings
    min_paragraph_length: int = 50
    excerpt_max_length: int = 150
    sample_paragraphs: int = 3


@dataclass(frozen=True)
class SEOConfig:
    """SEO analysis scoring thresholds and weights."""

    # Title length thresholds (characters)
    title_min_good: int = 30
    title_max_good: int = 60
    title_min_ok: int = 20
    title_max_ok: int = 70

    # Meta description length thresholds (characters)
    meta_min_good: int = 120
    meta_max_good: int = 160
    meta_min_ok: int = 80
    meta_max_ok: int = 200

    # Scoring weights (points)
    title_points_good: int = 25
    title_points_ok: int = 15
    title_points_poor: int = 5
    meta_points_good: int = 20
    meta_points_ok: int = 10
    meta_points_poor: int = 5
    content_points_excellent: int = 30
    content_points_good: int = 20
    content_points_ok: int = 10
    content_points_poor: int = 5
    heading_weight: float = 0.25

    # Heading structure penalties (subtracted from 100)
    penalty_no_h1: int = 30
    penalty_multiple_h1: int = 20
    penalty_no_h2: int = 20

    # Content length thresholds (word count)
    words_excellent: int = 2000
    words_good: int = 1000
    words_ok: int = 500
    words_min_recommended: int = 1000

    # Score display thresholds
    title_score_good: int = 100
    title_score_present: int = 70
    meta_score_good: int = 100
    meta_score_present: int = 70


@dataclass(frozen=True)
class EngagementConfig:
    """Engagement analysis scoring thresholds and weights."""

    # Readability thresholds (Flesch Reading Ease score)
    readability_good: int = 60
    readability_ok: int = 40
    difficulty_easy: int = 70
    difficulty_moderate: int = 50

    # Scoring weights (points)
    readability_points_good: int = 30
    readability_points_ok: int = 20
    readability_points_poor: int = 10
    images_many_points: int = 15
    images_some_points: int = 10
    video_points: int = 10
    lists_points: int = 10
    cta_points: int = 10
    social_points: int = 15
    wordcount_points_good: int = 10
    wordcount_points_ok: int = 5

    # Image thresholds
    images_many: int = 3

    # CTA threshold
    cta_min: int = 2

    # Ideal word count range
    words_min_ideal: int = 800
    words_max_ideal: int = 2500
    words_min_ok: int = 500
    words_max_ok: int = 3500

    # Readability recommendation threshold
    simplify_threshold: int = 50


# Singleton configuration instances
HTTP = HTTPConfig()
READABILITY = ReadabilityConfig()
TONE = ToneConfig()
SEO = SEOConfig()
ENGAGEMENT = EngagementConfig()


def _extract_text_content(soup: BeautifulSoup) -> str:
    """Extract clean text content from parsed HTML."""
    # Remove script and style elements
    for script in soup(["script", "style", "nav", "footer", "header"]):
        script.decompose()

    # Get text and clean it up
    text = soup.get_text()
    lines = (line.strip() for line in text.splitlines())
    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
    text = " ".join(chunk for chunk in chunks if chunk)

    return text


def _calculate_readability(text: str) -> dict[str, Any]:
    """Calculate readability metrics using Flesch Reading Ease approximation."""
    sentences = re.split(r"[.!?]+", text)
    sentences = [s.strip() for s in sentences if s.strip()]

    words = text.split()
    word_count = len(words)
    sentence_count = len(sentences)

    if sentence_count == 0 or word_count == 0:
        return {
            "flesch_reading_ease": 0,
            "avg_sentence_length": 0,
            "avg_word_length": 0,
        }

    # Count syllables (simple approximation)
    syllable_count = sum(_count_syllables(word) for word in words)

    # Flesch Reading Ease formula
    avg_sentence_length = word_count / sentence_count
    avg_syllables_per_word = syllable_count / word_count
    flesch_score = (
        READABILITY.intercept
        - READABILITY.sentence_coeff * avg_sentence_length
        - READABILITY.syllable_coeff * avg_syllables_per_word
    )
    flesch_score = max(0, min(100, flesch_score))  # Clamp to 0-100

    avg_word_length = sum(len(word) for word in words) / word_count

    return {
        "flesch_reading_ease": round(flesch_score, 1),
        "avg_sentence_length": round(avg_sentence_length, 1),
        "avg_word_length": round(avg_word_length, 1),
    }


def _count_syllables(word: str) -> int:
    """Count syllables in a word (simple approximation)."""
    word = word.lower()
    vowels = "aeiouy"
    syllable_count = 0
    previous_was_vowel = False

    for char in word:
        is_vowel = char in vowels
        if is_vowel and not previous_was_vowel:
            syllable_count += 1
        previous_was_vowel = is_vowel

    # Adjust for silent e
    if word.endswith("e"):
        syllable_count -= 1

    # Every word has at least one syllable
    return max(1, syllable_count)


def _analyze_tone(text: str, readability: dict[str, Any]) -> dict[str, Any]:
    """Analyze tone and style of the text."""
    words = text.split()
    word_count = len(words)

    # Detect formality based on word length and complexity
    avg_word_length = readability["avg_word_length"]
    if avg_word_length > TONE.formal_threshold:
        formality = "formal"
    elif avg_word_length > TONE.moderate_threshold:
        formality = "moderate"
    else:
        formality = "casual"

    # Detect reading level based on Flesch score
    flesch = readability["flesch_reading_ease"]
    if flesch >= READABILITY.level_elementary:
        reading_level = "elementary"
    elif flesch >= READABILITY.level_middle_school:
        reading_level = "middle school"
    elif flesch >= READABILITY.level_high_school:
        reading_level = "high school"
    elif flesch >= READABILITY.level_college:
        reading_level = "college"
    else:
        reading_level = "graduate"

    # Simple sentiment markers (count occurrences)
    enthusiasm_words = [
        "great",
        "excellent",
        "amazing",
        "fantastic",
        "awesome",
        "love",
        "best",
    ]
    authority_words = [
        "research",
        "study",
        "data",
        "proven",
        "evidence",
        "expert",
        "professional",
    ]
    empathy_words = [
        "understand",
        "feel",
        "help",
        "support",
        "care",
        "listen",
        "together",
    ]

    text_lower = text.lower()
    enthusiasm = sum(text_lower.count(word) for word in enthusiasm_words)
    authority = sum(text_lower.count(word) for word in authority_words)
    empathy = sum(text_lower.count(word) for word in empathy_words)

    # Normalize to 0-1 scale
    max_markers = max(1, word_count / TONE.marker_words_per_expected)

    return {
        "formality_level": formality,
        "reading_level": reading_level,
        "avg_sentence_length": readability["avg_sentence_length"],
        "vocabulary_complexity": "advanced"
        if avg_word_length > TONE.formal_threshold
        else "intermediate"
        if avg_word_length > TONE.moderate_threshold
        else "simple",
        "emotional_markers": {
            "enthusiasm": min(1.0, round(enthusiasm / max_markers, 2)),
            "authority": min(1.0, round(authority / max_markers, 2)),
            "empathy": min(1.0, round(empathy / max_markers, 2)),
        },
    }


def _analyze_seo(soup: BeautifulSoup, text: str) -> dict[str, Any]:
    """Analyze SEO elements of the webpage."""
    # Extract title
    title_tag = soup.find("title")
    title = title_tag.get_text().strip() if title_tag else ""

    # Extract meta description
    meta_desc_tag = soup.find("meta", attrs={"name": "description"})
    meta_desc = ""
    if meta_desc_tag:
        content = meta_desc_tag.get("content", "")
        if isinstance(content, str):
            meta_desc = content.strip()
        elif isinstance(content, list) and content:
            meta_desc = str(content[0]).strip()

    # Count headings
    h1_count = len(soup.find_all("h1"))
    h2_count = len(soup.find_all("h2"))
    h3_count = len(soup.find_all("h3"))

    # Heading structure score
    structure_score = 100
    if h1_count == 0:
        structure_score -= SEO.penalty_no_h1
    elif h1_count > 1:
        structure_score -= SEO.penalty_multiple_h1
    if h2_count == 0:
        structure_score -= SEO.penalty_no_h2

    # Word count
    word_count = len(text.split())

    # Calculate SEO score
    seo_score = 0

    # Title optimization (0-25 points)
    if title:
        if SEO.title_min_good <= len(title) <= SEO.title_max_good:
            seo_score += SEO.title_points_good
        elif SEO.title_min_ok <= len(title) <= SEO.title_max_ok:
            seo_score += SEO.title_points_ok
        else:
            seo_score += SEO.title_points_poor

    # Meta description (0-20 points)
    if meta_desc:
        if SEO.meta_min_good <= len(meta_desc) <= SEO.meta_max_good:
            seo_score += SEO.meta_points_good
        elif SEO.meta_min_ok <= len(meta_desc) <= SEO.meta_max_ok:
            seo_score += SEO.meta_points_ok
        else:
            seo_score += SEO.meta_points_poor

    # Headings (0-25 points)
    seo_score += int(structure_score * SEO.heading_weight)

    # Content length (0-30 points)
    if word_count >= SEO.words_excellent:
        seo_score += SEO.content_points_excellent
    elif word_count >= SEO.words_good:
        seo_score += SEO.content_points_good
    elif word_count >= SEO.words_ok:
        seo_score += SEO.content_points_ok
    else:
        seo_score += SEO.content_points_poor

    return {
        "seo_score": min(100, seo_score),
        "title_optimization": {
            "score": SEO.title_score_good
            if (SEO.title_min_good <= len(title) <= SEO.title_max_good)
            else (SEO.title_score_present if title else 0),
            "length": len(title),
            "present": bool(title),
        },
        "meta_description": {
            "score": SEO.meta_score_good
            if (SEO.meta_min_good <= len(meta_desc) <= SEO.meta_max_good)
            else (SEO.meta_score_present if meta_desc else 0),
            "length": len(meta_desc),
            "present": bool(meta_desc),
        },
        "headings": {
            "h1_count": h1_count,
            "h2_count": h2_count,
            "h3_count": h3_count,
            "structure_score": structure_score,
        },
        "content_quality": {
            "word_count": word_count,
            "readability_score": _calculate_readability(text)["flesch_reading_ease"],
        },
    }


def _analyze_engagement(
    soup: BeautifulSoup, text: str, readability: dict[str, Any]
) -> dict[str, Any]:
    """Analyze engagement potential of the webpage."""
    # Count images
    images = soup.find_all("img")
    image_count = len(images)

    # Count videos
    videos = soup.find_all(["video", "iframe"])
    video_count = len(
        [v for v in videos if "youtube" in str(v) or "vimeo" in str(v) or v.name == "video"]
    )

    # Check for CTAs (call-to-action)
    cta_keywords = [
        "subscribe",
        "download",
        "buy",
        "get started",
        "sign up",
        "learn more",
        "click here",
        "contact",
    ]
    text_lower = text.lower()
    cta_count = sum(text_lower.count(keyword) for keyword in cta_keywords)

    # Check for lists
    has_bullet_points = len(soup.find_all("ul")) > 0
    has_numbered_lists = len(soup.find_all("ol")) > 0

    # Check for social sharing
    has_share_buttons = any(
        keyword in text_lower for keyword in ["share", "tweet", "facebook", "linkedin"]
    )

    # Calculate engagement score
    engagement_score = 0

    # Readability (0-30 points)
    flesch = readability["flesch_reading_ease"]
    if flesch >= ENGAGEMENT.readability_good:
        engagement_score += ENGAGEMENT.readability_points_good
    elif flesch >= ENGAGEMENT.readability_ok:
        engagement_score += ENGAGEMENT.readability_points_ok
    else:
        engagement_score += ENGAGEMENT.readability_points_poor

    # Visual elements (0-25 points)
    if image_count >= ENGAGEMENT.images_many:
        engagement_score += ENGAGEMENT.images_many_points
    elif image_count >= 1:
        engagement_score += ENGAGEMENT.images_some_points
    if video_count >= 1:
        engagement_score += ENGAGEMENT.video_points

    # Interactive elements (0-20 points)
    if has_bullet_points or has_numbered_lists:
        engagement_score += ENGAGEMENT.lists_points
    if cta_count >= ENGAGEMENT.cta_min:
        engagement_score += ENGAGEMENT.cta_points

    # Social proof (0-15 points)
    if has_share_buttons:
        engagement_score += ENGAGEMENT.social_points

    # Word count appropriateness (0-10 points)
    word_count = len(text.split())
    if ENGAGEMENT.words_min_ideal <= word_count <= ENGAGEMENT.words_max_ideal:
        engagement_score += ENGAGEMENT.wordcount_points_good
    elif ENGAGEMENT.words_min_ok <= word_count <= ENGAGEMENT.words_max_ok:
        engagement_score += ENGAGEMENT.wordcount_points_ok

    return {
        "engagement_score": min(100, engagement_score),
        "readability": {
            "flesch_reading_ease": readability["flesch_reading_ease"],
            "avg_time_to_read": f"{max(1, len(text.split()) // READABILITY.reading_speed_wpm)} minutes",
            "difficulty_level": "easy"
            if flesch >= ENGAGEMENT.difficulty_easy
            else "moderate"
            if flesch >= ENGAGEMENT.difficulty_moderate
            else "difficult",
        },
        "engagement_elements": {
            "has_images": image_count > 0,
            "image_count": image_count,
            "has_videos": video_count > 0,
            "video_count": video_count,
            "has_interactive_elements": has_bullet_points or has_numbered_lists,
            "has_call_to_action": cta_count > 0,
            "cta_count": cta_count,
        },
        "content_structure": {
            "has_bullet_points": has_bullet_points,
            "has_numbered_lists": has_numbered_lists,
            "has_share_buttons": has_share_buttons,
        },
    }


async def analyze_website(
    url: str,
    analysis_type: Literal["tone", "seo", "engagement"],
) -> dict[str, Any]:
    """
    Fetch and analyze web content.

    This tool analyzes a website or blog post for various characteristics
    including tone, SEO optimization, and engagement potential.

    Args:
        url: The URL to analyze
        analysis_type: Type of analysis to perform
            - "tone": Analyze writing style and tone
            - "seo": Analyze SEO optimization
            - "engagement": Analyze engagement potential

    Returns:
        Dictionary containing analysis results and recommendations

    Raises:
        ValueError: If URL is invalid or analysis_type is unsupported
        httpx.HTTPError: If website cannot be fetched
    """
    logger.info(f"Analyzing website: {url} (type: {analysis_type})")

    # Validate URL format
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"Invalid URL: {url}")

    # SSRF protection: validate URL before fetching
    is_safe, reason = SSRFValidator.is_safe_url(url)
    if not is_safe:
        raise ValueError(f"URL rejected for security reasons: {reason}")

    try:
        # Fetch the webpage (without automatic redirect following for security)
        async with httpx.AsyncClient(
            timeout=HTTP.timeout_seconds, follow_redirects=False
        ) as client:
            response = await client.get(url)

            # Handle redirects manually with SSRF validation
            redirects_followed = 0
            while (
                response.status_code in (301, 302, 303, 307, 308)
                and redirects_followed < HTTP.max_redirects
            ):
                redirect_url = response.headers.get("Location")
                if not redirect_url:
                    raise ValueError("Redirect without Location header")

                # Validate redirect target
                is_safe, reason = SSRFValidator.is_safe_url(redirect_url)
                if not is_safe:
                    raise ValueError(f"Redirect rejected for security reasons: {reason}")

                response = await client.get(redirect_url)
                redirects_followed += 1

            if redirects_followed >= HTTP.max_redirects:
                raise ValueError(f"Too many redirects (>{HTTP.max_redirects})")

            response.raise_for_status()
            html_content = response.text

        # Parse HTML
        soup = BeautifulSoup(html_content, "lxml")

        # Extract clean text content
        text = _extract_text_content(soup)

        if not text.strip():
            raise ValueError("No text content found on the page")

        # Calculate readability metrics (used by all analysis types)
        readability = _calculate_readability(text)

        # Perform analysis based on type
        if analysis_type == "tone":
            tone_analysis = _analyze_tone(text, readability)

            # Extract sample excerpts from first few paragraphs
            paragraphs = soup.find_all("p")
            sample_excerpts = []
            for p in paragraphs[: TONE.sample_paragraphs]:
                p_text = p.get_text().strip()
                if len(p_text) > TONE.min_paragraph_length:
                    sample_excerpts.append(
                        {
                            "text": p_text[: TONE.excerpt_max_length] + "..."
                            if len(p_text) > TONE.excerpt_max_length
                            else p_text,
                            "tone_label": tone_analysis["formality_level"],
                        }
                    )

            # Generate recommendations
            recommendations = []
            if readability["avg_sentence_length"] > TONE.long_sentence_threshold:
                recommendations.append("Consider shortening sentences for better readability")
            if tone_analysis["emotional_markers"]["enthusiasm"] < TONE.low_enthusiasm_threshold:
                recommendations.append("Add more engaging language to capture reader interest")
            if tone_analysis["emotional_markers"]["authority"] > TONE.high_authority_threshold:
                recommendations.append("Balance authoritative tone with more accessible language")

            result = {
                "url": url,
                "analysis_type": "tone",
                "analyzed_at": datetime.now(UTC).isoformat(),
                "results": tone_analysis,
                "recommendations": recommendations
                if recommendations
                else ["Content tone is well-balanced"],
                "sample_excerpts": sample_excerpts,
            }

        elif analysis_type == "seo":
            seo_analysis = _analyze_seo(soup, text)

            # Generate recommendations
            recommendations = []
            if seo_analysis["title_optimization"]["length"] < SEO.title_min_good:
                recommendations.append(
                    f"Lengthen page title to {SEO.title_min_good}-{SEO.title_max_good} characters for better SEO"
                )
            elif seo_analysis["title_optimization"]["length"] > SEO.title_max_good:
                recommendations.append(
                    f"Shorten page title to under {SEO.title_max_good} characters"
                )

            if not seo_analysis["meta_description"]["present"]:
                recommendations.append(
                    f"Add a meta description ({SEO.meta_min_good}-{SEO.meta_max_good} characters)"
                )
            elif seo_analysis["meta_description"]["length"] < SEO.meta_min_good:
                recommendations.append(
                    f"Expand meta description to {SEO.meta_min_good}-{SEO.meta_max_good} characters"
                )

            if seo_analysis["headings"]["h1_count"] == 0:
                recommendations.append("Add an H1 heading to improve SEO structure")
            elif seo_analysis["headings"]["h1_count"] > 1:
                recommendations.append("Use only one H1 heading per page")

            if seo_analysis["content_quality"]["word_count"] < SEO.words_min_recommended:
                recommendations.append(
                    f"Increase content length to {SEO.words_min_recommended}+ words for better ranking"
                )

            # Check for images with alt text
            images_without_alt = len([img for img in soup.find_all("img") if not img.get("alt")])
            if images_without_alt > 0:
                recommendations.append(
                    f"Add alt text to {images_without_alt} images for better SEO"
                )

            result = {
                "url": url,
                "analysis_type": "seo",
                "analyzed_at": datetime.now(UTC).isoformat(),
                "results": seo_analysis,
                "recommendations": recommendations
                if recommendations
                else ["SEO is well-optimized"],
            }

        elif analysis_type == "engagement":
            engagement_analysis = _analyze_engagement(soup, text, readability)

            # Generate recommendations
            recommendations = []
            if engagement_analysis["engagement_elements"]["image_count"] == 0:
                recommendations.append("Add images to make content more visually appealing")
            if engagement_analysis["engagement_elements"]["video_count"] == 0:
                recommendations.append("Consider adding video content to increase engagement")
            if not engagement_analysis["content_structure"]["has_bullet_points"]:
                recommendations.append(
                    "Use bullet points to break up text and improve scannability"
                )
            if engagement_analysis["engagement_elements"]["cta_count"] < ENGAGEMENT.cta_min:
                recommendations.append("Add clear calls-to-action throughout the content")
            if readability["flesch_reading_ease"] < ENGAGEMENT.simplify_threshold:
                recommendations.append("Simplify language to improve readability")

            result = {
                "url": url,
                "analysis_type": "engagement",
                "analyzed_at": datetime.now(UTC).isoformat(),
                "results": engagement_analysis,
                "recommendations": recommendations
                if recommendations
                else ["Content is highly engaging"],
            }

        else:
            raise ValueError(f"Unsupported analysis type: {analysis_type}")

        logger.info(f"Successfully analyzed {url}")
        return result

    except httpx.HTTPError as e:
        logger.error(f"Failed to fetch URL {url}: {e}")
        raise ValueError(f"Failed to fetch URL: {e}")

    except Exception as e:
        logger.error(f"Analysis failed for {url}: {e}")
        raise


# ---------------------------------------------------------------------------
# Tool schema for MCP server auto-registration
# ---------------------------------------------------------------------------

TOOL_SCHEMAS = [
    {
        "name": "analyze_website",
        "description": (
            "Fetch and analyze web content for tone, style, SEO, and engagement. "
            "Useful for understanding the characteristics of existing content "
            "and identifying opportunities for improvement."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to analyze (must start with http:// or https://)",
                },
                "analysis_type": {
                    "type": "string",
                    "enum": ["tone", "seo", "engagement"],
                    "description": (
                        "Type of analysis to perform:\n"
                        "- tone: Analyze writing style and tone\n"
                        "- seo: Analyze SEO optimization\n"
                        "- engagement: Analyze engagement potential"
                    ),
                },
            },
            "required": ["url", "analysis_type"],
        },
        "handler": analyze_website,
    },
]
