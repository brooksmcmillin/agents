"""JSON parsing utilities for extracting structured data from LLM responses.

LLMs frequently return JSON wrapped in markdown code fences or with
leading/trailing prose. These utilities handle the extraction robustly.
"""

import json


def strip_and_parse_json(text: str) -> dict | list | None:
    """Extract and parse JSON from LLM response text.

    Handles markdown fences, leading/trailing text, and extracts
    the first complete JSON object or array found.

    Strategy:
    1. Try direct parse (already clean JSON)
    2. Strip markdown code fences and retry
    3. Find first balanced { ... } or [ ... ] and parse

    Args:
        text: Raw LLM response text that may contain JSON

    Returns:
        Parsed JSON as dict or list, or None if no valid JSON found
    """
    text = text.strip()

    # 1. Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. Strip markdown fences
    if "```" in text:
        parts = text.split("```")
        if len(parts) >= 3:
            inner = parts[1]
            if inner.startswith(("json", "JSON")):
                inner = inner[4:]
            inner = inner.strip()
            try:
                return json.loads(inner)
            except json.JSONDecodeError:
                pass

    # 3. Find first { ... } or [ ... ] by scanning for balanced braces
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start = text.find(start_char)
        if start == -1:
            continue
        depth = 0
        for i in range(start, len(text)):
            if text[i] == start_char:
                depth += 1
            elif text[i] == end_char:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break

    return None


def strip_markdown_fences(text: str) -> str:
    """Strip markdown code fences from text.

    Removes opening ``` (with optional language tag) and closing ```.

    Args:
        text: Text potentially wrapped in markdown code fences

    Returns:
        Text with fences removed
    """
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()
