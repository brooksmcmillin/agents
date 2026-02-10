"""Web content analysis tool.

This tool fetches and analyzes web content for tone, style, SEO, and engagement.
Uses real web scraping with BeautifulSoup and text analysis.
"""

import logging
import re
from datetime import UTC, datetime
from typing import Any, Literal

import httpx
from bs4 import BeautifulSoup

from ..security import SSRFValidator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# HTTP settings
HTTP_TIMEOUT_SECONDS = 10.0
MAX_REDIRECTS = 5

# Flesch Reading Ease formula coefficients
FLESCH_INTERCEPT = 206.835
FLESCH_SENTENCE_COEFF = 1.015
FLESCH_SYLLABLE_COEFF = 84.6

# Readability level thresholds (Flesch Reading Ease score)
READING_LEVEL_ELEMENTARY = 90
READING_LEVEL_MIDDLE_SCHOOL = 70
READING_LEVEL_HIGH_SCHOOL = 60
READING_LEVEL_COLLEGE = 50

# Formality thresholds (average word length in characters)
FORMALITY_FORMAL_THRESHOLD = 5.5
FORMALITY_MODERATE_THRESHOLD = 4.5

# Emotional marker normalization (expected markers per N words)
EMOTIONAL_MARKER_WORDS_PER_EXPECTED = 100

# Tone recommendation thresholds
TONE_LONG_SENTENCE_THRESHOLD = 25
TONE_LOW_ENTHUSIASM_THRESHOLD = 0.3
TONE_HIGH_AUTHORITY_THRESHOLD = 0.8

# SEO title length thresholds (characters)
SEO_TITLE_MIN_GOOD = 30
SEO_TITLE_MAX_GOOD = 60
SEO_TITLE_MIN_OK = 20
SEO_TITLE_MAX_OK = 70

# SEO meta description length thresholds (characters)
SEO_META_MIN_GOOD = 120
SEO_META_MAX_GOOD = 160
SEO_META_MIN_OK = 80
SEO_META_MAX_OK = 200

# SEO scoring weights (points)
SEO_TITLE_POINTS_GOOD = 25
SEO_TITLE_POINTS_OK = 15
SEO_TITLE_POINTS_POOR = 5
SEO_META_POINTS_GOOD = 20
SEO_META_POINTS_OK = 10
SEO_META_POINTS_POOR = 5
SEO_CONTENT_POINTS_EXCELLENT = 30
SEO_CONTENT_POINTS_GOOD = 20
SEO_CONTENT_POINTS_OK = 10
SEO_CONTENT_POINTS_POOR = 5
SEO_HEADING_WEIGHT = 0.25

# SEO heading structure penalties (subtracted from 100)
SEO_PENALTY_NO_H1 = 30
SEO_PENALTY_MULTIPLE_H1 = 20
SEO_PENALTY_NO_H2 = 20

# SEO content length thresholds (word count)
SEO_WORDS_EXCELLENT = 2000
SEO_WORDS_GOOD = 1000
SEO_WORDS_OK = 500
SEO_WORDS_MIN_RECOMMENDED = 1000

# Engagement readability thresholds (Flesch Reading Ease score)
ENGAGEMENT_READABILITY_GOOD = 60
ENGAGEMENT_READABILITY_OK = 40
ENGAGEMENT_DIFFICULTY_EASY = 70
ENGAGEMENT_DIFFICULTY_MODERATE = 50

# Engagement scoring weights (points)
ENGAGEMENT_READABILITY_POINTS_GOOD = 30
ENGAGEMENT_READABILITY_POINTS_OK = 20
ENGAGEMENT_READABILITY_POINTS_POOR = 10
ENGAGEMENT_IMAGES_MANY_POINTS = 15
ENGAGEMENT_IMAGES_SOME_POINTS = 10
ENGAGEMENT_VIDEO_POINTS = 10
ENGAGEMENT_LISTS_POINTS = 10
ENGAGEMENT_CTA_POINTS = 10
ENGAGEMENT_SOCIAL_POINTS = 15
ENGAGEMENT_WORDCOUNT_POINTS_GOOD = 10
ENGAGEMENT_WORDCOUNT_POINTS_OK = 5

# Engagement image thresholds
ENGAGEMENT_IMAGES_MANY = 3

# Engagement CTA threshold
ENGAGEMENT_CTA_MIN = 2

# Engagement ideal word count range
ENGAGEMENT_WORDS_MIN_IDEAL = 800
ENGAGEMENT_WORDS_MAX_IDEAL = 2500
ENGAGEMENT_WORDS_MIN_OK = 500
ENGAGEMENT_WORDS_MAX_OK = 3500

# Engagement readability recommendation threshold
ENGAGEMENT_SIMPLIFY_THRESHOLD = 50

# Tone sample excerpt settings
TONE_MIN_PARAGRAPH_LENGTH = 50
TONE_EXCERPT_MAX_LENGTH = 150
TONE_SAMPLE_PARAGRAPHS = 3

# Reading time (words per minute)
READING_SPEED_WPM = 200

# SEO score display thresholds
SEO_TITLE_SCORE_GOOD = 100
SEO_TITLE_SCORE_PRESENT = 70
SEO_META_SCORE_GOOD = 100
SEO_META_SCORE_PRESENT = 70


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
        FLESCH_INTERCEPT
        - FLESCH_SENTENCE_COEFF * avg_sentence_length
        - FLESCH_SYLLABLE_COEFF * avg_syllables_per_word
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
    if avg_word_length > FORMALITY_FORMAL_THRESHOLD:
        formality = "formal"
    elif avg_word_length > FORMALITY_MODERATE_THRESHOLD:
        formality = "moderate"
    else:
        formality = "casual"

    # Detect reading level based on Flesch score
    flesch = readability["flesch_reading_ease"]
    if flesch >= READING_LEVEL_ELEMENTARY:
        reading_level = "elementary"
    elif flesch >= READING_LEVEL_MIDDLE_SCHOOL:
        reading_level = "middle school"
    elif flesch >= READING_LEVEL_HIGH_SCHOOL:
        reading_level = "high school"
    elif flesch >= READING_LEVEL_COLLEGE:
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
    max_markers = max(1, word_count / EMOTIONAL_MARKER_WORDS_PER_EXPECTED)

    return {
        "formality_level": formality,
        "reading_level": reading_level,
        "avg_sentence_length": readability["avg_sentence_length"],
        "vocabulary_complexity": "advanced"
        if avg_word_length > FORMALITY_FORMAL_THRESHOLD
        else "intermediate"
        if avg_word_length > FORMALITY_MODERATE_THRESHOLD
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
        structure_score -= SEO_PENALTY_NO_H1
    elif h1_count > 1:
        structure_score -= SEO_PENALTY_MULTIPLE_H1
    if h2_count == 0:
        structure_score -= SEO_PENALTY_NO_H2

    # Word count
    word_count = len(text.split())

    # Calculate SEO score
    seo_score = 0

    # Title optimization (0-25 points)
    if title:
        if SEO_TITLE_MIN_GOOD <= len(title) <= SEO_TITLE_MAX_GOOD:
            seo_score += SEO_TITLE_POINTS_GOOD
        elif SEO_TITLE_MIN_OK <= len(title) <= SEO_TITLE_MAX_OK:
            seo_score += SEO_TITLE_POINTS_OK
        else:
            seo_score += SEO_TITLE_POINTS_POOR

    # Meta description (0-20 points)
    if meta_desc:
        if SEO_META_MIN_GOOD <= len(meta_desc) <= SEO_META_MAX_GOOD:
            seo_score += SEO_META_POINTS_GOOD
        elif SEO_META_MIN_OK <= len(meta_desc) <= SEO_META_MAX_OK:
            seo_score += SEO_META_POINTS_OK
        else:
            seo_score += SEO_META_POINTS_POOR

    # Headings (0-25 points)
    seo_score += int(structure_score * SEO_HEADING_WEIGHT)

    # Content length (0-30 points)
    if word_count >= SEO_WORDS_EXCELLENT:
        seo_score += SEO_CONTENT_POINTS_EXCELLENT
    elif word_count >= SEO_WORDS_GOOD:
        seo_score += SEO_CONTENT_POINTS_GOOD
    elif word_count >= SEO_WORDS_OK:
        seo_score += SEO_CONTENT_POINTS_OK
    else:
        seo_score += SEO_CONTENT_POINTS_POOR

    return {
        "seo_score": min(100, seo_score),
        "title_optimization": {
            "score": SEO_TITLE_SCORE_GOOD
            if (SEO_TITLE_MIN_GOOD <= len(title) <= SEO_TITLE_MAX_GOOD)
            else (SEO_TITLE_SCORE_PRESENT if title else 0),
            "length": len(title),
            "present": bool(title),
        },
        "meta_description": {
            "score": SEO_META_SCORE_GOOD
            if (SEO_META_MIN_GOOD <= len(meta_desc) <= SEO_META_MAX_GOOD)
            else (SEO_META_SCORE_PRESENT if meta_desc else 0),
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
    if flesch >= ENGAGEMENT_READABILITY_GOOD:
        engagement_score += ENGAGEMENT_READABILITY_POINTS_GOOD
    elif flesch >= ENGAGEMENT_READABILITY_OK:
        engagement_score += ENGAGEMENT_READABILITY_POINTS_OK
    else:
        engagement_score += ENGAGEMENT_READABILITY_POINTS_POOR

    # Visual elements (0-25 points)
    if image_count >= ENGAGEMENT_IMAGES_MANY:
        engagement_score += ENGAGEMENT_IMAGES_MANY_POINTS
    elif image_count >= 1:
        engagement_score += ENGAGEMENT_IMAGES_SOME_POINTS
    if video_count >= 1:
        engagement_score += ENGAGEMENT_VIDEO_POINTS

    # Interactive elements (0-20 points)
    if has_bullet_points or has_numbered_lists:
        engagement_score += ENGAGEMENT_LISTS_POINTS
    if cta_count >= ENGAGEMENT_CTA_MIN:
        engagement_score += ENGAGEMENT_CTA_POINTS

    # Social proof (0-15 points)
    if has_share_buttons:
        engagement_score += ENGAGEMENT_SOCIAL_POINTS

    # Word count appropriateness (0-10 points)
    word_count = len(text.split())
    if ENGAGEMENT_WORDS_MIN_IDEAL <= word_count <= ENGAGEMENT_WORDS_MAX_IDEAL:
        engagement_score += ENGAGEMENT_WORDCOUNT_POINTS_GOOD
    elif ENGAGEMENT_WORDS_MIN_OK <= word_count <= ENGAGEMENT_WORDS_MAX_OK:
        engagement_score += ENGAGEMENT_WORDCOUNT_POINTS_OK

    return {
        "engagement_score": min(100, engagement_score),
        "readability": {
            "flesch_reading_ease": readability["flesch_reading_ease"],
            "avg_time_to_read": f"{max(1, len(text.split()) // READING_SPEED_WPM)} minutes",
            "difficulty_level": "easy"
            if flesch >= ENGAGEMENT_DIFFICULTY_EASY
            else "moderate"
            if flesch >= ENGAGEMENT_DIFFICULTY_MODERATE
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
            timeout=HTTP_TIMEOUT_SECONDS, follow_redirects=False
        ) as client:
            response = await client.get(url)

            # Handle redirects manually with SSRF validation
            redirects_followed = 0
            while (
                response.status_code in (301, 302, 303, 307, 308)
                and redirects_followed < MAX_REDIRECTS
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

            if redirects_followed >= MAX_REDIRECTS:
                raise ValueError(f"Too many redirects (>{MAX_REDIRECTS})")

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
            for p in paragraphs[:TONE_SAMPLE_PARAGRAPHS]:
                p_text = p.get_text().strip()
                if len(p_text) > TONE_MIN_PARAGRAPH_LENGTH:
                    sample_excerpts.append(
                        {
                            "text": p_text[:TONE_EXCERPT_MAX_LENGTH] + "..."
                            if len(p_text) > TONE_EXCERPT_MAX_LENGTH
                            else p_text,
                            "tone_label": tone_analysis["formality_level"],
                        }
                    )

            # Generate recommendations
            recommendations = []
            if readability["avg_sentence_length"] > TONE_LONG_SENTENCE_THRESHOLD:
                recommendations.append("Consider shortening sentences for better readability")
            if tone_analysis["emotional_markers"]["enthusiasm"] < TONE_LOW_ENTHUSIASM_THRESHOLD:
                recommendations.append("Add more engaging language to capture reader interest")
            if tone_analysis["emotional_markers"]["authority"] > TONE_HIGH_AUTHORITY_THRESHOLD:
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
            if seo_analysis["title_optimization"]["length"] < SEO_TITLE_MIN_GOOD:
                recommendations.append(
                    f"Lengthen page title to {SEO_TITLE_MIN_GOOD}-{SEO_TITLE_MAX_GOOD} characters for better SEO"
                )
            elif seo_analysis["title_optimization"]["length"] > SEO_TITLE_MAX_GOOD:
                recommendations.append(
                    f"Shorten page title to under {SEO_TITLE_MAX_GOOD} characters"
                )

            if not seo_analysis["meta_description"]["present"]:
                recommendations.append(
                    f"Add a meta description ({SEO_META_MIN_GOOD}-{SEO_META_MAX_GOOD} characters)"
                )
            elif seo_analysis["meta_description"]["length"] < SEO_META_MIN_GOOD:
                recommendations.append(
                    f"Expand meta description to {SEO_META_MIN_GOOD}-{SEO_META_MAX_GOOD} characters"
                )

            if seo_analysis["headings"]["h1_count"] == 0:
                recommendations.append("Add an H1 heading to improve SEO structure")
            elif seo_analysis["headings"]["h1_count"] > 1:
                recommendations.append("Use only one H1 heading per page")

            if seo_analysis["content_quality"]["word_count"] < SEO_WORDS_MIN_RECOMMENDED:
                recommendations.append(
                    f"Increase content length to {SEO_WORDS_MIN_RECOMMENDED}+ words for better ranking"
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
            if engagement_analysis["engagement_elements"]["cta_count"] < ENGAGEMENT_CTA_MIN:
                recommendations.append("Add clear calls-to-action throughout the content")
            if readability["flesch_reading_ease"] < ENGAGEMENT_SIMPLIFY_THRESHOLD:
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
