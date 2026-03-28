"""
Schema validation utilities for SEO agents.
"""

import json
import re
from typing import Any, Type


def validate_json(text: str) -> Any:
    """Parse JSON from text, handling potential markdown wrapper."""
    json_match = re.search(r"\{[\s\S]*\}", text)
    if not json_match:
        raise ValueError("No JSON object found in response")
    return json.loads(json_match.group())


def validate_against_schema(text: str, schema: Type) -> Any:
    """Parse JSON from text and validate against Pydantic schema."""
    data = validate_json(text)

    if hasattr(schema, "model_validate"):
        return schema.model_validate(data)
    elif hasattr(schema, "validate"):
        return schema.validate(data)
    else:
        raise ValueError(f"Schema {schema} is not a Pydantic model")