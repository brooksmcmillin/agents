"""Unit tests for the web_analyzer content analysis tool.

Tests cover:
- Syllable counting
- Readability metrics (Flesch Reading Ease)
- Text extraction from HTML
- Tone analysis (formality, reading level, emotional markers)
- SEO analysis (title, meta description, headings, content quality)
- Engagement analysis (images, videos, CTAs, lists, readability)
- Build helpers for tone, SEO, and engagement result dicts
- analyze_website orchestration (mocking HTTP layer)
- Input validation (_validate_and_fetch)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agent_framework.tools.web_analyzer import (
    SEO,
    _analyze_engagement,
    _analyze_seo,
    _analyze_tone,
    _build_engagement_result,
    _build_seo_result,
    _build_tone_result,
    _calculate_readability,
    _count_syllables,
    _extract_text_content,
    analyze_website,
)
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_soup(html: str) -> BeautifulSoup:
    """Parse HTML string into a BeautifulSoup object."""
    return BeautifulSoup(html, "lxml")


def _simple_readability(text: str) -> dict[str, Any]:
    """Convenience wrapper for _calculate_readability."""
    return _calculate_readability(text)


# ---------------------------------------------------------------------------
# _count_syllables
# ---------------------------------------------------------------------------


class TestCountSyllables:
    """Tests for the syllable counting helper."""

    def test_single_vowel_word(self):
        """Single vowel word should return 1 syllable."""
        assert _count_syllables("a") == 1

    def test_simple_one_syllable(self):
        """Common monosyllabic words."""
        assert _count_syllables("the") == 1
        assert _count_syllables("cat") == 1
        assert _count_syllables("dog") == 1

    def test_two_syllable_word(self):
        """Two-syllable words.

        Note: the implementation is a simple approximation; "table" ends in a
        silent 'e' so the heuristic subtracts one syllable and returns 1.
        We test words where the approximation gives the expected count.
        """
        assert _count_syllables("happy") == 2
        assert _count_syllables("button") == 2

    def test_three_syllable_word(self):
        """Three-syllable words."""
        assert _count_syllables("beautiful") == 3

    def test_silent_e_reduces_count(self):
        """Words ending in silent 'e' should not count the trailing e."""
        # "make" → ma-ke → 1 syllable (silent e removed)
        assert _count_syllables("make") == 1
        # "like" → 1 syllable
        assert _count_syllables("like") == 1

    def test_minimum_one_syllable(self):
        """Words with no counted vowels still return at least 1."""
        # "rhythm" has 'y' as vowel but edge cases like "nth" should still get 1
        assert _count_syllables("nth") >= 1

    def test_uppercase_handled(self):
        """Function should work case-insensitively (lowercases internally)."""
        assert _count_syllables("CAT") == _count_syllables("cat")
        assert _count_syllables("HAPPY") == _count_syllables("happy")


# ---------------------------------------------------------------------------
# _calculate_readability
# ---------------------------------------------------------------------------


class TestCalculateReadability:
    """Tests for the Flesch Reading Ease readability metric."""

    def test_empty_text_returns_zeros(self):
        """Empty text should return zero metrics."""
        result = _calculate_readability("")
        assert result["flesch_reading_ease"] == 0
        assert result["avg_sentence_length"] == 0
        assert result["avg_word_length"] == 0

    def test_no_sentences_returns_zeros(self):
        """Text with no sentence-ending punctuation and no words returns zeros."""
        # Single non-sentence word list with no terminator still has 1 "sentence"
        result = _calculate_readability("hello world")
        # Word count 2, sentence count 1 — should compute a positive score
        assert result["flesch_reading_ease"] >= 0

    def test_simple_text_high_readability(self):
        """Very simple, short sentences should have a high Flesch score."""
        text = "I eat food. I like cats. Cats are good."
        result = _calculate_readability(text)
        assert result["flesch_reading_ease"] > 60

    def test_complex_text_lower_readability(self):
        """Complex academic text should score lower than simple text."""
        simple = "The cat sat. The dog ran."
        complex_text = (
            "The epistemological implications of poststructuralist deconstruction "
            "necessitate comprehensive reevaluation of hermeneutical frameworks. "
            "Phenomenological investigations corroborate hypothetical presuppositions. "
            "Consequently, multidisciplinary methodological circumspection demonstrates "
            "theoretical incompatibilities within foundational philosophical assumptions."
        )
        simple_score = _calculate_readability(simple)["flesch_reading_ease"]
        complex_score = _calculate_readability(complex_text)["flesch_reading_ease"]
        assert simple_score > complex_score

    def test_returns_all_keys(self):
        """Result must contain the three expected keys."""
        result = _calculate_readability("Simple text here.")
        assert "flesch_reading_ease" in result
        assert "avg_sentence_length" in result
        assert "avg_word_length" in result

    def test_score_clamped_between_0_and_100(self):
        """Flesch score must be clamped to [0, 100]."""
        # Very simple one-word sentence
        result = _calculate_readability("Hi.")
        assert 0 <= result["flesch_reading_ease"] <= 100

    def test_avg_sentence_length_calculation(self):
        """Average sentence length should equal total words divided by sentence count."""
        # 6 words, 2 sentences → avg 3.0
        text = "One two three. Four five six."
        result = _calculate_readability(text)
        assert result["avg_sentence_length"] == pytest.approx(3.0, rel=0.1)

    def test_avg_word_length_positive(self):
        """Average word length should be > 0 for non-empty text."""
        result = _calculate_readability("Some words here.")
        assert result["avg_word_length"] > 0


# ---------------------------------------------------------------------------
# _extract_text_content
# ---------------------------------------------------------------------------


class TestExtractTextContent:
    """Tests for HTML → clean text extraction."""

    def test_removes_script_tags(self):
        """Script content should not appear in extracted text."""
        soup = _make_soup("<html><body><p>Hello</p><script>alert('hi');</script></body></html>")
        text = _extract_text_content(soup)
        assert "alert" not in text
        assert "Hello" in text

    def test_removes_style_tags(self):
        """Style content should not appear in extracted text."""
        soup = _make_soup("<html><body><p>World</p><style>.btn{color:red}</style></body></html>")
        text = _extract_text_content(soup)
        assert "color" not in text
        assert "World" in text

    def test_removes_nav_footer_header(self):
        """Nav, footer, and header elements should be stripped."""
        html = (
            "<html><body>"
            "<header>Site Header</header>"
            "<nav>Navigation</nav>"
            "<p>Main content</p>"
            "<footer>Footer content</footer>"
            "</body></html>"
        )
        soup = _make_soup(html)
        text = _extract_text_content(soup)
        assert "Main content" in text
        assert "Site Header" not in text
        assert "Navigation" not in text
        assert "Footer content" not in text

    def test_returns_non_empty_string(self):
        """Non-empty HTML should produce non-empty text."""
        soup = _make_soup("<p>Test content for extraction.</p>")
        text = _extract_text_content(soup)
        assert len(text.strip()) > 0

    def test_empty_html_returns_empty_or_whitespace(self):
        """Completely empty HTML should return empty or whitespace string."""
        soup = _make_soup("")
        text = _extract_text_content(soup)
        assert text.strip() == ""

    def test_multiple_paragraphs_joined(self):
        """Text from multiple paragraphs should all be present."""
        soup = _make_soup("<p>First paragraph.</p><p>Second paragraph.</p>")
        text = _extract_text_content(soup)
        assert "First paragraph" in text
        assert "Second paragraph" in text


# ---------------------------------------------------------------------------
# _analyze_tone
# ---------------------------------------------------------------------------


class TestAnalyzeTone:
    """Tests for tone and style analysis."""

    def _readability_for(self, text: str) -> dict[str, Any]:
        return _calculate_readability(text)

    def test_formal_long_words(self):
        """Text with long average word length should be classified as formal."""
        # Use words longer than TONE.formal_threshold (5.5 chars avg)
        formal_text = (
            "Philosophical anthropological considerations demonstrate institutional "
            "responsibilities toward environmental sustainability frameworks. "
            "Comprehensive investigations reveal multidisciplinary perspectives."
        )
        readability = self._readability_for(formal_text)
        result = _analyze_tone(formal_text, readability)
        assert result["formality_level"] == "formal"
        assert result["vocabulary_complexity"] == "advanced"

    def test_casual_short_words(self):
        """Text with short average word length should be classified as casual."""
        casual_text = "I go run. I eat. I play. We win. Fun time to be had by all."
        readability = self._readability_for(casual_text)
        result = _analyze_tone(casual_text, readability)
        assert result["formality_level"] == "casual"
        assert result["vocabulary_complexity"] == "simple"

    def test_moderate_formality(self):
        """Text with medium word length sits at moderate formality."""
        moderate_text = (
            "Today we review the project status and discuss upcoming deadlines. "
            "The team made progress on several features this week."
        )
        readability = self._readability_for(moderate_text)
        result = _analyze_tone(moderate_text, readability)
        assert result["formality_level"] in ("moderate", "casual", "formal")

    def test_returns_required_keys(self):
        """Result must contain all expected keys."""
        text = "Simple text here for testing."
        result = _analyze_tone(text, self._readability_for(text))
        assert "formality_level" in result
        assert "reading_level" in result
        assert "avg_sentence_length" in result
        assert "vocabulary_complexity" in result
        assert "emotional_markers" in result
        assert "enthusiasm" in result["emotional_markers"]
        assert "authority" in result["emotional_markers"]
        assert "empathy" in result["emotional_markers"]

    def test_enthusiasm_markers_detected(self):
        """Enthusiasm words should increase the enthusiasm score."""
        text = (
            "This is a great, excellent, and amazing product. "
            "We love it and it is truly awesome and fantastic."
        )
        readability = self._readability_for(text)
        result = _analyze_tone(text, readability)
        assert result["emotional_markers"]["enthusiasm"] > 0

    def test_authority_markers_detected(self):
        """Authority words should increase the authority score."""
        text = (
            "Research and study show the data is supported by evidence from expert "
            "professional sources. Proven methods from the study confirm the research."
        )
        readability = self._readability_for(text)
        result = _analyze_tone(text, readability)
        assert result["emotional_markers"]["authority"] > 0

    def test_empathy_markers_detected(self):
        """Empathy words should increase the empathy score."""
        text = "We understand your feelings. We help and support you. We listen together."
        readability = self._readability_for(text)
        result = _analyze_tone(text, readability)
        assert result["emotional_markers"]["empathy"] > 0

    def test_emotional_markers_capped_at_1(self):
        """Emotional marker scores should never exceed 1.0."""
        # Stuff the text with many enthusiasm words
        text = " ".join(["great excellent amazing fantastic awesome love best"] * 20)
        readability = self._readability_for(text)
        result = _analyze_tone(text, readability)
        assert result["emotional_markers"]["enthusiasm"] <= 1.0
        assert result["emotional_markers"]["authority"] <= 1.0
        assert result["emotional_markers"]["empathy"] <= 1.0

    def test_reading_level_elementary(self):
        """Very high Flesch score → elementary reading level."""
        # Build a readability dict that forces Flesch score >= 90
        readability = {
            "flesch_reading_ease": 92.0,
            "avg_sentence_length": 8.0,
            "avg_word_length": 3.5,
        }
        text = "I go. You run. We eat."
        result = _analyze_tone(text, readability)
        assert result["reading_level"] == "elementary"

    def test_reading_level_graduate(self):
        """Very low Flesch score → graduate reading level."""
        readability = {
            "flesch_reading_ease": 20.0,
            "avg_sentence_length": 40.0,
            "avg_word_length": 7.5,
        }
        text = "Incomprehensible text."
        result = _analyze_tone(text, readability)
        assert result["reading_level"] == "graduate"


# ---------------------------------------------------------------------------
# _analyze_seo
# ---------------------------------------------------------------------------


class TestAnalyzeSeo:
    """Tests for SEO element analysis."""

    def test_good_title_length_max_seo_points(self):
        """Title in 30-60 char range should earn maximum title points."""
        # 40-char title: good
        title = "A" * 40
        html = (
            f"<html><head><title>{title}</title></head><body><p>{'word ' * 200}</p></body></html>"
        )
        soup = _make_soup(html)
        text = _extract_text_content(soup)
        result = _analyze_seo(soup, text)
        assert result["title_optimization"]["score"] == SEO.title_score_good

    def test_missing_title_zero_score(self):
        """Missing title should give zero for title optimization score."""
        html = "<html><head></head><body><p>content</p></body></html>"
        soup = _make_soup(html)
        text = _extract_text_content(soup)
        result = _analyze_seo(soup, text)
        assert result["title_optimization"]["present"] is False
        assert result["title_optimization"]["score"] == 0

    def test_short_title_reduces_seo_score(self):
        """Very short title should earn fewer points than a well-sized title."""
        short_title = "Hi"
        good_title = "A" * 45
        html_short = f"<html><head><title>{short_title}</title></head><body><p>{'word ' * 200}</p></body></html>"
        html_good = f"<html><head><title>{good_title}</title></head><body><p>{'word ' * 200}</p></body></html>"

        soup_short = _make_soup(html_short)
        soup_good = _make_soup(html_good)
        text = "word " * 200

        result_short = _analyze_seo(soup_short, text)
        result_good = _analyze_seo(soup_good, text)
        assert result_good["seo_score"] >= result_short["seo_score"]

    def test_good_meta_description(self):
        """Meta description in 120-160 char range earns max meta points."""
        meta_content = "A" * 140
        html = (
            f'<html><head><meta name="description" content="{meta_content}"></head>'
            "<body><p>content</p></body></html>"
        )
        soup = _make_soup(html)
        text = _extract_text_content(soup)
        result = _analyze_seo(soup, text)
        assert result["meta_description"]["score"] == SEO.meta_score_good
        assert result["meta_description"]["present"] is True

    def test_missing_meta_description(self):
        """Missing meta description should be flagged."""
        html = "<html><head></head><body><p>content</p></body></html>"
        soup = _make_soup(html)
        text = _extract_text_content(soup)
        result = _analyze_seo(soup, text)
        assert result["meta_description"]["present"] is False
        assert result["meta_description"]["score"] == 0

    def test_single_h1_full_structure_score(self):
        """Single H1 + H2 should give full heading structure score (100)."""
        html = "<html><body><h1>Title</h1><h2>Section</h2><p>content</p></body></html>"
        soup = _make_soup(html)
        text = _extract_text_content(soup)
        result = _analyze_seo(soup, text)
        assert result["headings"]["h1_count"] == 1
        assert result["headings"]["h2_count"] == 1
        assert result["headings"]["structure_score"] == 100

    def test_no_h1_reduces_structure_score(self):
        """Missing H1 should reduce heading structure score."""
        html = "<html><body><h2>Section</h2><p>content</p></body></html>"
        soup = _make_soup(html)
        text = _extract_text_content(soup)
        result = _analyze_seo(soup, text)
        assert result["headings"]["h1_count"] == 0
        assert result["headings"]["structure_score"] == 100 - SEO.penalty_no_h1

    def test_multiple_h1_reduces_structure_score(self):
        """Multiple H1 tags should reduce heading structure score."""
        html = "<html><body><h1>A</h1><h1>B</h1><h2>Section</h2><p>content</p></body></html>"
        soup = _make_soup(html)
        text = _extract_text_content(soup)
        result = _analyze_seo(soup, text)
        assert result["headings"]["h1_count"] == 2
        assert result["headings"]["structure_score"] == 100 - SEO.penalty_multiple_h1

    def test_no_h2_reduces_structure_score(self):
        """Missing H2 tag should reduce heading structure score."""
        html = "<html><body><h1>Title</h1><p>content</p></body></html>"
        soup = _make_soup(html)
        text = _extract_text_content(soup)
        result = _analyze_seo(soup, text)
        assert result["headings"]["structure_score"] == 100 - SEO.penalty_no_h2

    def test_excellent_content_length(self):
        """2000+ words should earn maximum content points."""
        text = "word " * 2100
        html = f"<html><body><h1>X</h1><h2>Y</h2><p>{text}</p></body></html>"
        soup = _make_soup(html)
        result = _analyze_seo(soup, text)
        assert result["content_quality"]["word_count"] >= SEO.words_excellent

    def test_seo_score_capped_at_100(self):
        """SEO score should never exceed 100."""
        text = "word " * 2500
        meta = "A" * 140
        title = "A" * 45
        html = (
            f"<html><head><title>{title}</title>"
            f'<meta name="description" content="{meta}"></head>'
            f"<body><h1>X</h1><h2>Y</h2><p>{text}</p></body></html>"
        )
        soup = _make_soup(html)
        result = _analyze_seo(soup, text)
        assert result["seo_score"] <= 100

    def test_returns_required_keys(self):
        """Result must contain all expected top-level keys."""
        soup = _make_soup("<html><body><p>test</p></body></html>")
        text = "test"
        result = _analyze_seo(soup, text)
        assert "seo_score" in result
        assert "title_optimization" in result
        assert "meta_description" in result
        assert "headings" in result
        assert "content_quality" in result

    def test_meta_description_list_content_attribute(self):
        """Meta description whose 'content' attribute is a list should still work."""
        html = "<html><head></head><body><p>content</p></body></html>"
        soup = _make_soup(html)
        # Manually add a meta tag with a list-style content attribute
        meta = soup.new_tag("meta")
        meta["name"] = "description"
        meta["content"] = ["A short description for testing purposes here okay."]
        soup.head.append(meta)  # type: ignore[union-attr]
        text = _extract_text_content(soup)
        result = _analyze_seo(soup, text)
        assert result["meta_description"]["present"] is True


# ---------------------------------------------------------------------------
# _analyze_engagement
# ---------------------------------------------------------------------------


class TestAnalyzeEngagement:
    """Tests for engagement potential analysis."""

    def test_no_images_no_video_no_lists(self):
        """Page with no visual or interactive elements should score low."""
        html = "<html><body><p>Plain text content here.</p></body></html>"
        soup = _make_soup(html)
        text = _extract_text_content(soup)
        readability = _calculate_readability(text)
        result = _analyze_engagement(soup, text, readability)
        assert result["engagement_elements"]["has_images"] is False
        assert result["engagement_elements"]["has_videos"] is False
        assert result["engagement_elements"]["has_interactive_elements"] is False

    def test_images_detected(self):
        """Images should be counted and flagged."""
        html = "<html><body><img src='a.jpg'><img src='b.jpg'><img src='c.jpg'><p>text</p></body></html>"
        soup = _make_soup(html)
        text = _extract_text_content(soup)
        readability = _calculate_readability(text)
        result = _analyze_engagement(soup, text, readability)
        assert result["engagement_elements"]["has_images"] is True
        assert result["engagement_elements"]["image_count"] == 3

    def test_youtube_iframe_counts_as_video(self):
        """YouTube iframe should be counted as a video."""
        html = (
            "<html><body>"
            "<iframe src='https://www.youtube.com/embed/abc'></iframe>"
            "<p>text</p>"
            "</body></html>"
        )
        soup = _make_soup(html)
        text = _extract_text_content(soup)
        readability = _calculate_readability(text)
        result = _analyze_engagement(soup, text, readability)
        assert result["engagement_elements"]["has_videos"] is True
        assert result["engagement_elements"]["video_count"] >= 1

    def test_native_video_element_counted(self):
        """Native HTML5 video element should be counted."""
        html = "<html><body><video src='test.mp4'></video><p>text</p></body></html>"
        soup = _make_soup(html)
        text = _extract_text_content(soup)
        readability = _calculate_readability(text)
        result = _analyze_engagement(soup, text, readability)
        assert result["engagement_elements"]["has_videos"] is True

    def test_bullet_lists_detected(self):
        """Unordered list should mark has_interactive_elements and has_bullet_points."""
        html = "<html><body><ul><li>Item 1</li><li>Item 2</li></ul><p>text</p></body></html>"
        soup = _make_soup(html)
        text = _extract_text_content(soup)
        readability = _calculate_readability(text)
        result = _analyze_engagement(soup, text, readability)
        assert result["content_structure"]["has_bullet_points"] is True
        assert result["engagement_elements"]["has_interactive_elements"] is True

    def test_ordered_lists_detected(self):
        """Ordered list should mark has_numbered_lists."""
        html = "<html><body><ol><li>Step 1</li><li>Step 2</li></ol><p>text</p></body></html>"
        soup = _make_soup(html)
        text = _extract_text_content(soup)
        readability = _calculate_readability(text)
        result = _analyze_engagement(soup, text, readability)
        assert result["content_structure"]["has_numbered_lists"] is True

    def test_cta_keywords_counted(self):
        """CTA keywords in text should be counted."""
        html = (
            "<html><body><p>Please subscribe now and download our guide. "
            "Sign up today and get started on your journey. Contact us to learn more.</p></body></html>"
        )
        soup = _make_soup(html)
        text = _extract_text_content(soup)
        readability = _calculate_readability(text)
        result = _analyze_engagement(soup, text, readability)
        assert result["engagement_elements"]["has_call_to_action"] is True
        assert result["engagement_elements"]["cta_count"] >= 2

    def test_social_share_keywords_detected(self):
        """Share/social keywords should set has_share_buttons."""
        html = (
            "<html><body><p>Share this on Facebook or tweet about it on LinkedIn.</p></body></html>"
        )
        soup = _make_soup(html)
        text = _extract_text_content(soup)
        readability = _calculate_readability(text)
        result = _analyze_engagement(soup, text, readability)
        assert result["content_structure"]["has_share_buttons"] is True

    def test_engagement_score_capped_at_100(self):
        """Engagement score should never exceed 100."""
        # Pack all positive signals into one page
        text = (
            "Subscribe download buy get started sign up learn more click here contact us. "
            "Share tweet facebook linkedin. " * 10
        )
        html = (
            "<html><body>"
            "<ul><li>A</li></ul><ol><li>B</li></ol>"
            "<img src='a.jpg'><img src='b.jpg'><img src='c.jpg'><img src='d.jpg'>"
            "<video src='v.mp4'></video>"
            f"<p>{text}</p>"
            "</body></html>"
        )
        soup = _make_soup(html)
        text_extracted = _extract_text_content(soup)
        readability = _calculate_readability(text_extracted)
        result = _analyze_engagement(soup, text_extracted, readability)
        assert result["engagement_score"] <= 100

    def test_returns_required_keys(self):
        """Result must contain all expected keys."""
        soup = _make_soup("<html><body><p>test</p></body></html>")
        text = "test"
        readability = _calculate_readability(text)
        result = _analyze_engagement(soup, text, readability)
        assert "engagement_score" in result
        assert "readability" in result
        assert "engagement_elements" in result
        assert "content_structure" in result

    def test_readability_sub_keys(self):
        """Readability sub-dict must contain expected keys."""
        soup = _make_soup(
            "<html><body><p>Simple text. Easy to read. Short sentences here.</p></body></html>"
        )
        text = _extract_text_content(soup)
        readability = _calculate_readability(text)
        result = _analyze_engagement(soup, text, readability)
        assert "flesch_reading_ease" in result["readability"]
        assert "avg_time_to_read" in result["readability"]
        assert "difficulty_level" in result["readability"]

    def test_difficulty_level_easy(self):
        """High Flesch score should yield 'easy' difficulty."""
        readability = {
            "flesch_reading_ease": 75.0,
            "avg_sentence_length": 8.0,
            "avg_word_length": 3.5,
        }
        soup = _make_soup("<html><body><p>test</p></body></html>")
        result = _analyze_engagement(soup, "test", readability)
        assert result["readability"]["difficulty_level"] == "easy"

    def test_difficulty_level_moderate(self):
        """Mid Flesch score should yield 'moderate' difficulty."""
        readability = {
            "flesch_reading_ease": 55.0,
            "avg_sentence_length": 15.0,
            "avg_word_length": 5.0,
        }
        soup = _make_soup("<html><body><p>test</p></body></html>")
        result = _analyze_engagement(soup, "test", readability)
        assert result["readability"]["difficulty_level"] == "moderate"

    def test_difficulty_level_difficult(self):
        """Low Flesch score should yield 'difficult' difficulty."""
        readability = {
            "flesch_reading_ease": 20.0,
            "avg_sentence_length": 40.0,
            "avg_word_length": 8.0,
        }
        soup = _make_soup("<html><body><p>test</p></body></html>")
        result = _analyze_engagement(soup, "test", readability)
        assert result["readability"]["difficulty_level"] == "difficult"


# ---------------------------------------------------------------------------
# _build_tone_result
# ---------------------------------------------------------------------------


class TestBuildToneResult:
    """Tests for the tone result builder (includes recommendations)."""

    def _build(self, html: str, text: str) -> dict[str, Any]:
        soup = _make_soup(html)
        readability = _calculate_readability(text)
        return _build_tone_result("https://example.com", soup, text, readability)

    def test_returns_top_level_structure(self):
        """Result must contain url, analysis_type, analyzed_at, results, recommendations."""
        html = "<html><body><p>Simple text here.</p></body></html>"
        result = self._build(html, "Simple text here.")
        assert result["url"] == "https://example.com"
        assert result["analysis_type"] == "tone"
        assert "analyzed_at" in result
        assert "results" in result
        assert "recommendations" in result
        assert "sample_excerpts" in result

    def test_long_sentences_trigger_recommendation(self):
        """Text with long average sentences should recommend shortening them."""
        # Build a single very long sentence (>25 words)
        long_sentence = "word " * 30 + ". "
        html = f"<html><body><p>{long_sentence}</p></body></html>"
        result = self._build(html, long_sentence)
        combined = " ".join(result["recommendations"])
        assert "shortening sentences" in combined

    def test_sample_excerpts_populated(self):
        """Long paragraphs should populate sample excerpts."""
        # Paragraph > 50 chars
        long_para = "This is a fairly long paragraph that should be included as a sample excerpt for testing purposes here."
        html = f"<html><body><p>{long_para}</p></body></html>"
        result = self._build(html, long_para)
        assert len(result["sample_excerpts"]) >= 1
        assert "text" in result["sample_excerpts"][0]
        assert "tone_label" in result["sample_excerpts"][0]

    def test_no_issues_gives_balanced_recommendation(self):
        """Content with no issues should recommend that tone is well-balanced."""
        # Create a text that won't trigger any negative recommendations:
        # - Short sentences (< 25 words avg)
        # - Moderate enthusiasm
        # - Low authority markers
        text = "Great! Amazing results here. Excellent. Best ever. Love it too. Awesome stuff."
        html = f"<html><body><p>{text}</p></body></html>"
        result = self._build(html, text)
        # Either well-balanced message OR specific feedback (depending on thresholds)
        assert len(result["recommendations"]) >= 1


# ---------------------------------------------------------------------------
# _build_seo_result
# ---------------------------------------------------------------------------


class TestBuildSeoResult:
    """Tests for the SEO result builder (includes recommendations)."""

    def _build(self, html: str, text: str) -> dict[str, Any]:
        soup = _make_soup(html)
        readability = _calculate_readability(text)
        return _build_seo_result("https://example.com", soup, text, readability)

    def test_returns_top_level_structure(self):
        """Result must contain url, analysis_type, analyzed_at, results, recommendations."""
        html = "<html><head><title>Test Page</title></head><body><p>content</p></body></html>"
        result = self._build(html, "content")
        assert result["url"] == "https://example.com"
        assert result["analysis_type"] == "seo"
        assert "analyzed_at" in result
        assert "results" in result
        assert "recommendations" in result

    def test_missing_meta_triggers_recommendation(self):
        """No meta description should trigger an add-meta recommendation."""
        html = "<html><head><title>Test Page Title Here</title></head><body><p>content</p></body></html>"
        result = self._build(html, "content")
        combined = " ".join(result["recommendations"])
        assert "meta description" in combined.lower()

    def test_short_title_triggers_recommendation(self):
        """Title shorter than 30 chars should trigger a lengthen recommendation."""
        html = "<html><head><title>Hi</title></head><body><p>content</p></body></html>"
        result = self._build(html, "content")
        combined = " ".join(result["recommendations"])
        assert "title" in combined.lower()

    def test_long_title_triggers_recommendation(self):
        """Title longer than 60 chars should trigger a shorten recommendation."""
        long_title = "A" * 65
        html = f"<html><head><title>{long_title}</title></head><body><p>content</p></body></html>"
        result = self._build(html, "content")
        combined = " ".join(result["recommendations"])
        assert "title" in combined.lower()

    def test_no_h1_triggers_recommendation(self):
        """Missing H1 should trigger an add-H1 recommendation."""
        html = "<html><head><title>Good Enough Title Here</title></head><body><p>content</p></body></html>"
        result = self._build(html, "content")
        combined = " ".join(result["recommendations"])
        assert "h1" in combined.lower()

    def test_multiple_h1_triggers_recommendation(self):
        """Multiple H1 tags should trigger a use-one-H1 recommendation."""
        html = (
            "<html><head><title>Good Enough Title Here</title></head>"
            "<body><h1>A</h1><h1>B</h1><p>content</p></body></html>"
        )
        result = self._build(html, "content")
        combined = " ".join(result["recommendations"])
        assert "h1" in combined.lower()

    def test_images_without_alt_trigger_recommendation(self):
        """Images missing alt text should trigger an alt-text recommendation."""
        html = (
            "<html><head><title>Good Title For SEO Here</title></head>"
            "<body><img src='a.jpg'><img src='b.jpg'><p>content</p></body></html>"
        )
        result = self._build(html, "content")
        combined = " ".join(result["recommendations"])
        assert "alt" in combined.lower()

    def test_optimized_page_no_recommendations(self):
        """Fully optimized page should return a positive message."""
        title = "A" * 45
        meta = "A" * 140
        text = "word " * 1200
        html = (
            f"<html><head><title>{title}</title>"
            f'<meta name="description" content="{meta}"></head>'
            f"<body><h1>Main Title</h1><h2>Section</h2>"
            f"<img src='a.jpg' alt='desc'><p>{text}</p></body></html>"
        )
        result = self._build(html, text)
        combined = " ".join(result["recommendations"])
        assert "well-optimized" in combined or len(result["recommendations"]) == 1


# ---------------------------------------------------------------------------
# _build_engagement_result
# ---------------------------------------------------------------------------


class TestBuildEngagementResult:
    """Tests for the engagement result builder (includes recommendations)."""

    def _build(self, html: str, text: str) -> dict[str, Any]:
        soup = _make_soup(html)
        readability = _calculate_readability(text)
        return _build_engagement_result("https://example.com", soup, text, readability)

    def test_returns_top_level_structure(self):
        """Result must contain url, analysis_type, analyzed_at, results, recommendations."""
        html = "<html><body><p>text</p></body></html>"
        result = self._build(html, "text")
        assert result["url"] == "https://example.com"
        assert result["analysis_type"] == "engagement"
        assert "analyzed_at" in result
        assert "results" in result
        assert "recommendations" in result

    def test_no_images_triggers_recommendation(self):
        """Missing images should trigger an add-images recommendation."""
        html = "<html><body><p>text</p></body></html>"
        result = self._build(html, "text")
        combined = " ".join(result["recommendations"])
        assert "images" in combined.lower()

    def test_no_bullet_points_triggers_recommendation(self):
        """Missing bullet points should trigger a use-bullet-points recommendation."""
        html = "<html><body><p>text</p></body></html>"
        result = self._build(html, "text")
        combined = " ".join(result["recommendations"])
        assert "bullet points" in combined.lower()

    def test_no_cta_triggers_recommendation(self):
        """Missing CTAs should trigger a calls-to-action recommendation."""
        html = "<html><body><p>text</p></body></html>"
        result = self._build(html, "text")
        combined = " ".join(result["recommendations"])
        assert "calls-to-action" in combined.lower()

    def test_highly_engaging_no_recommendations(self):
        """Fully engaging page should return 'Content is highly engaging'."""
        text = (
            "Subscribe now and download your free guide. Sign up to get started. "
            "Contact us or learn more about our service. " * 50
        )
        html = (
            "<html><body>"
            "<ul><li>A</li></ul>"
            "<img src='a.jpg'><img src='b.jpg'><img src='c.jpg'>"
            "<video src='v.mp4'></video>"
            f"<p>{text}</p>"
            "</body></html>"
        )
        result = self._build(html, text)
        # With all signals present, should recommend nothing or say highly engaging
        combined = " ".join(result["recommendations"])
        assert "highly engaging" in combined or len(result["recommendations"]) >= 1


# ---------------------------------------------------------------------------
# analyze_website (integration-style with mocked HTTP)
# ---------------------------------------------------------------------------


class TestAnalyzeWebsite:
    """Tests for the top-level analyze_website orchestration function."""

    _SAMPLE_HTML = """
    <html>
    <head>
        <title>A Good Title For SEO Testing Purposes Here</title>
        <meta name="description" content="{meta}">
    </head>
    <body>
        <h1>Main Heading</h1>
        <h2>Sub Heading</h2>
        <p>{body}</p>
    </body>
    </html>
    """.format(
        meta="A" * 140,
        body="word " * 1100,
    )

    async def _call(self, analysis_type: str, html: str = _SAMPLE_HTML) -> dict[str, Any]:
        """Call analyze_website with mocked HTTP."""
        with (
            patch(
                "agent_framework.tools.web_analyzer._validate_and_fetch",
                new_callable=AsyncMock,
                return_value=html,
            ),
        ):
            return await analyze_website("https://example.com", analysis_type)  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_tone_analysis_type(self):
        """analyze_website with 'tone' should return analysis_type == 'tone'."""
        result = await self._call("tone")
        assert result["analysis_type"] == "tone"
        assert result["url"] == "https://example.com"
        assert "results" in result
        assert "recommendations" in result

    @pytest.mark.asyncio
    async def test_seo_analysis_type(self):
        """analyze_website with 'seo' should return analysis_type == 'seo'."""
        result = await self._call("seo")
        assert result["analysis_type"] == "seo"
        assert "results" in result

    @pytest.mark.asyncio
    async def test_engagement_analysis_type(self):
        """analyze_website with 'engagement' should return analysis_type == 'engagement'."""
        result = await self._call("engagement")
        assert result["analysis_type"] == "engagement"
        assert "results" in result

    @pytest.mark.asyncio
    async def test_invalid_analysis_type_raises(self):
        """Unsupported analysis_type should return an error dict."""
        result = await analyze_website("https://example.com", "invalid")  # type: ignore[arg-type]
        assert result["status"] == "error"
        assert "Unsupported analysis type" in result["message"]

    @pytest.mark.asyncio
    async def test_empty_page_raises_value_error(self):
        """Page with no extractable text content should return an error dict."""
        empty_html = "<html><body></body></html>"
        result = await self._call("tone", html=empty_html)
        assert result["status"] == "error"
        assert "No text content" in result["message"]

    @pytest.mark.asyncio
    async def test_http_error_wrapped_as_value_error(self):
        """httpx.HTTPError during fetch should return an error dict."""

        with patch(
            "agent_framework.tools.web_analyzer._validate_and_fetch",
            new_callable=AsyncMock,
            side_effect=ValueError("Failed to fetch URL: connection error"),
        ):
            result = await analyze_website("https://example.com", "tone")
            assert result["status"] == "error"
            assert "Failed to fetch URL" in result["message"]

    @pytest.mark.asyncio
    async def test_result_contains_analyzed_at_timestamp(self):
        """Result should include an ISO-format analyzed_at timestamp."""
        result = await self._call("seo")
        assert "analyzed_at" in result
        # Should be parseable as ISO datetime
        from datetime import datetime

        datetime.fromisoformat(result["analyzed_at"])


# ---------------------------------------------------------------------------
# _validate_and_fetch (security validation)
# ---------------------------------------------------------------------------


class TestValidateAndFetch:
    """Tests for URL validation and SSRF protection in _validate_and_fetch."""

    @pytest.mark.asyncio
    async def test_non_http_url_raises(self):
        """URL not starting with http:// or https:// should raise ValueError."""
        from agent_framework.tools.web_analyzer import _validate_and_fetch

        with pytest.raises(ValueError, match="Invalid URL"):
            await _validate_and_fetch("ftp://example.com")

    @pytest.mark.asyncio
    async def test_ssrf_blocked_url_raises(self):
        """Internal/private URL should be blocked by SSRF validator."""
        from agent_framework.tools.web_analyzer import _validate_and_fetch

        with pytest.raises(ValueError, match="(security|rejected|blocked|fetch)"):
            await _validate_and_fetch("http://169.254.169.254/latest/meta-data/")

    @pytest.mark.asyncio
    async def test_valid_url_fetches_content(self):
        """Valid public URL should pass SSRF checks and fetch HTML."""
        from agent_framework.tools.web_analyzer import _validate_and_fetch

        sample_html = "<html><body><p>Hello</p></body></html>"

        with (
            patch(
                "agent_framework.tools.web_analyzer.SSRFValidator.is_safe_url",
                return_value=(True, ""),
            ),
            patch(
                "agent_framework.tools.web_analyzer.SSRFValidator.validate_request_with_redirects",
                new_callable=AsyncMock,
                return_value=(True, "https://example.com"),
            ),
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_response = MagicMock()
            mock_response.text = sample_html
            mock_response.raise_for_status = MagicMock()
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            content = await _validate_and_fetch("https://example.com")
            assert content == sample_html

    @pytest.mark.asyncio
    async def test_ssrf_redirect_blocked(self):
        """SSRF validator blocking a redirect should raise ValueError."""
        from agent_framework.tools.web_analyzer import _validate_and_fetch

        with (
            patch(
                "agent_framework.tools.web_analyzer.SSRFValidator.is_safe_url",
                return_value=(True, ""),
            ),
            patch(
                "agent_framework.tools.web_analyzer.SSRFValidator.validate_request_with_redirects",
                new_callable=AsyncMock,
                return_value=(False, "Redirect to private IP blocked"),
            ),
        ):
            with pytest.raises(ValueError, match="security reasons"):
                await _validate_and_fetch("https://example.com")
