"""Web content analysis tool.

This tool fetches and analyzes web content for tone, style, SEO, and engagement.
Uses real web scraping with BeautifulSoup and text analysis.
"""

import logging
import re
from datetime import datetime
from typing import Any, Dict, Literal

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


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

    # Flesch Reading Ease = 206.835 - 1.015 * (words/sentences) - 84.6 * (syllables/words)
    avg_sentence_length = word_count / sentence_count
    avg_syllables_per_word = syllable_count / word_count
    flesch_score = 206.835 - 1.015 * avg_sentence_length - 84.6 * avg_syllables_per_word
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
    if avg_word_length > 5.5:
        formality = "formal"
    elif avg_word_length > 4.5:
        formality = "moderate"
    else:
        formality = "casual"

    # Detect reading level based on Flesch score
    flesch = readability["flesch_reading_ease"]
    if flesch >= 90:
        reading_level = "elementary"
    elif flesch >= 70:
        reading_level = "middle school"
    elif flesch >= 60:
        reading_level = "high school"
    elif flesch >= 50:
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
    max_markers = max(1, word_count / 100)  # Expect ~1 marker per 100 words

    return {
        "formality_level": formality,
        "reading_level": reading_level,
        "avg_sentence_length": readability["avg_sentence_length"],
        "vocabulary_complexity": "advanced"
        if avg_word_length > 5.5
        else "intermediate"
        if avg_word_length > 4.5
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
        structure_score -= 30
    elif h1_count > 1:
        structure_score -= 20
    if h2_count == 0:
        structure_score -= 20

    # Word count
    word_count = len(text.split())

    # Calculate SEO score
    seo_score = 0

    # Title optimization (0-25 points)
    if title:
        if 30 <= len(title) <= 60:
            seo_score += 25
        elif 20 <= len(title) <= 70:
            seo_score += 15
        else:
            seo_score += 5

    # Meta description (0-20 points)
    if meta_desc:
        if 120 <= len(meta_desc) <= 160:
            seo_score += 20
        elif 80 <= len(meta_desc) <= 200:
            seo_score += 10
        else:
            seo_score += 5

    # Headings (0-25 points)
    seo_score += int(structure_score * 0.25)

    # Content length (0-30 points)
    if word_count >= 2000:
        seo_score += 30
    elif word_count >= 1000:
        seo_score += 20
    elif word_count >= 500:
        seo_score += 10
    else:
        seo_score += 5

    return {
        "seo_score": min(100, seo_score),
        "title_optimization": {
            "score": 100 if (30 <= len(title) <= 60) else (70 if title else 0),
            "length": len(title),
            "present": bool(title),
        },
        "meta_description": {
            "score": 100
            if (120 <= len(meta_desc) <= 160)
            else (70 if meta_desc else 0),
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
        [
            v
            for v in videos
            if "youtube" in str(v) or "vimeo" in str(v) or v.name == "video"
        ]
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
    if flesch >= 60:
        engagement_score += 30
    elif flesch >= 40:
        engagement_score += 20
    else:
        engagement_score += 10

    # Visual elements (0-25 points)
    if image_count >= 3:
        engagement_score += 15
    elif image_count >= 1:
        engagement_score += 10
    if video_count >= 1:
        engagement_score += 10

    # Interactive elements (0-20 points)
    if has_bullet_points or has_numbered_lists:
        engagement_score += 10
    if cta_count >= 2:
        engagement_score += 10

    # Social proof (0-15 points)
    if has_share_buttons:
        engagement_score += 15

    # Word count appropriateness (0-10 points)
    word_count = len(text.split())
    if 800 <= word_count <= 2500:
        engagement_score += 10
    elif 500 <= word_count <= 3500:
        engagement_score += 5

    return {
        "engagement_score": min(100, engagement_score),
        "readability": {
            "flesch_reading_ease": readability["flesch_reading_ease"],
            "avg_time_to_read": f"{max(1, len(text.split()) // 200)} minutes",
            "difficulty_level": "easy"
            if flesch >= 70
            else "moderate"
            if flesch >= 50
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
) -> Dict[str, Any]:
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

    # Validate URL
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"Invalid URL: {url}")

    try:
        # Fetch the webpage
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            response = await client.get(url)
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
            for p in paragraphs[:3]:
                p_text = p.get_text().strip()
                if len(p_text) > 50:
                    sample_excerpts.append(
                        {
                            "text": p_text[:150] + "..."
                            if len(p_text) > 150
                            else p_text,
                            "tone_label": tone_analysis["formality_level"],
                        }
                    )

            # Generate recommendations
            recommendations = []
            if readability["avg_sentence_length"] > 25:
                recommendations.append(
                    "Consider shortening sentences for better readability"
                )
            if tone_analysis["emotional_markers"]["enthusiasm"] < 0.3:
                recommendations.append(
                    "Add more engaging language to capture reader interest"
                )
            if tone_analysis["emotional_markers"]["authority"] > 0.8:
                recommendations.append(
                    "Balance authoritative tone with more accessible language"
                )

            result = {
                "url": url,
                "analysis_type": "tone",
                "analyzed_at": datetime.utcnow().isoformat(),
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
            if seo_analysis["title_optimization"]["length"] < 30:
                recommendations.append(
                    "Lengthen page title to 30-60 characters for better SEO"
                )
            elif seo_analysis["title_optimization"]["length"] > 60:
                recommendations.append("Shorten page title to under 60 characters")

            if not seo_analysis["meta_description"]["present"]:
                recommendations.append("Add a meta description (120-160 characters)")
            elif seo_analysis["meta_description"]["length"] < 120:
                recommendations.append("Expand meta description to 120-160 characters")

            if seo_analysis["headings"]["h1_count"] == 0:
                recommendations.append("Add an H1 heading to improve SEO structure")
            elif seo_analysis["headings"]["h1_count"] > 1:
                recommendations.append("Use only one H1 heading per page")

            if seo_analysis["content_quality"]["word_count"] < 1000:
                recommendations.append(
                    "Increase content length to 1000+ words for better ranking"
                )

            # Check for images with alt text
            images_without_alt = len(
                [img for img in soup.find_all("img") if not img.get("alt")]
            )
            if images_without_alt > 0:
                recommendations.append(
                    f"Add alt text to {images_without_alt} images for better SEO"
                )

            result = {
                "url": url,
                "analysis_type": "seo",
                "analyzed_at": datetime.utcnow().isoformat(),
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
                recommendations.append(
                    "Add images to make content more visually appealing"
                )
            if engagement_analysis["engagement_elements"]["video_count"] == 0:
                recommendations.append(
                    "Consider adding video content to increase engagement"
                )
            if not engagement_analysis["content_structure"]["has_bullet_points"]:
                recommendations.append(
                    "Use bullet points to break up text and improve scannability"
                )
            if engagement_analysis["engagement_elements"]["cta_count"] < 2:
                recommendations.append(
                    "Add clear calls-to-action throughout the content"
                )
            if readability["flesch_reading_ease"] < 50:
                recommendations.append("Simplify language to improve readability")

            result = {
                "url": url,
                "analysis_type": "engagement",
                "analyzed_at": datetime.utcnow().isoformat(),
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
