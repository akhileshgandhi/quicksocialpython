"""
Schema Validators Package — Pydantic validation utilities.
"""

import json
import re
from typing import Any, Dict, Type

from pydantic import BaseModel, ValidationError


def _strip_thinking_tags(text: str) -> str:
    """Strip <think>...</thinking> tags used by some models (e.g., Qwen)."""
    # Remove <think>...</think> blocks
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    # Remove single <think> tags if any
    text = text.replace('</think>', '').replace('<think>', '')
    return text.strip()


def _extract_json_from_text(text: str) -> str:
    """
    Extract JSON from various response formats.
    Handles:
    - Plain JSON
    - Markdown code blocks
    - <think> tags (Qwen models)
    - Mixed content with JSON at the end
    """
    text = text.strip()
    
    # First, strip thinking tags
    text = _strip_thinking_tags(text)
    
    # Handle markdown code blocks
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 2:
            text = "```".join(parts[1:-1]) if parts[-1].strip() == "```" else parts[1]
            lines = text.split("\n")
            if lines and re.match(r'^[a-zA-Z]+$', lines[0].strip()):
                lines = lines[1:]
            text = "\n".join(lines)
    
    text = text.strip().strip("`").strip()
    
    # If no valid JSON start, try to find JSON in the text
    if not text.startswith('{') and not text.startswith('['):
        # Look for { as start of JSON
        json_start = text.find('{')
        if json_start >= 0:
            text = text[json_start:]
            # Find matching closing brace
            brace_count = 0
            for i, char in enumerate(text):
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        text = text[:i+1]
                        break
    
    return text.strip()


def validate_against_schema(text: str, schema: Type[BaseModel]) -> Dict[str, Any]:
    """
    Parse JSON from text and validate against Pydantic schema.
    """
    text = _extract_json_from_text(text)
    
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse JSON: {e}\nResponse text: {text[:500]}")
    
    try:
        validated = schema(**data)
        return validated.model_dump()
    except ValidationError as e:
        raise ValueError(f"Schema validation failed: {e}\nData: {data}")


def validate_json(text: str) -> Dict[str, Any]:
    """
    Parse JSON from text without schema validation.
    """
    text = _extract_json_from_text(text)
    
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse JSON: {e}\nResponse text: {text[:500]}")