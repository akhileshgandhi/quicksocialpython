"""
Schema Validators Package — Pydantic validation utilities.
"""

import json
import re
from typing import Any, Dict, Type

from pydantic import BaseModel, ValidationError


def validate_against_schema(text: str, schema: Type[BaseModel]) -> Dict[str, Any]:
    """
    Parse JSON from text and validate against Pydantic schema.
    
    Handles common Gemini response formats:
    - Plain JSON
    - Markdown code blocks with ```json
    - Markdown code blocks without language
    """
    # Strip markdown code blocks if present
    text = text.strip()
    
    # Handle markdown code blocks
    if text.startswith("```"):
        # Split by ``` and take the content between
        parts = text.split("```")
        if len(parts) >= 2:
            # Get content between first ``` and last ```
            text = "```".join(parts[1:-1]) if parts[-1].strip() == "```" else parts[1]
            # Remove language identifier like "json" or "python"
            lines = text.split("\n")
            if lines and re.match(r'^[a-zA-Z]+$', lines[0].strip()):
                lines = lines[1:]
            text = "\n".join(lines)
    
    text = text.strip()
    
    # Handle any remaining backticks
    text = text.strip("`").strip()
    
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
    Handles common Gemini response formats.
    """
    text = text.strip()
    
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
    
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse JSON: {e}\nResponse text: {text[:500]}")