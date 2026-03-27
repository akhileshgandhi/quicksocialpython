"""
Schema validation utilities for SEO agents.
"""

import json
from typing import Any, Type


def validate_against_schema(text: str, schema: Type) -> Any:
    """Parse JSON from text and validate against Pydantic schema."""
    import re

    json_match = re.search(r"\{[\s\S]*\}", text)
    if not json_match:
        raise ValueError("No JSON object found in response")

    data = json.loads(json_match.group())

    if hasattr(schema, "model_validate"):
        return schema.model_validate(data)
    elif hasattr(schema, "validate"):
        return schema.validate(data)
    else:
        raise ValueError(f"Schema {schema} is not a Pydantic model")