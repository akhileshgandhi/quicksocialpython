"""
SEO Agents Utilities - Shared helper functions.

This module provides reusable utilities for:
- Field normalization (None → [], string → list, etc.)
- Data type conversions
- Common validation patterns
"""

from typing import Any, Dict, List, Optional, Type, TypeVar, Union
from pydantic import BaseModel

T = TypeVar("T")


def normalize_to_list(value: Any, default: List[Any] | None = None) -> List[Any]:
    """Normalize a value to a list.
    
    Handles common LLM response variations:
    - None → []
    - single item "string" → ["string"]
    - list → list (unchanged)
    - invalid type → []
    
    Args:
        value: The value to normalize
        default: Default if value is None (default: empty list)
        
    Returns:
        List representation of the value
    """
    if value is None:
        return default if default is not None else []
    
    if isinstance(value, list):
        return value
    
    if isinstance(value, str):
        return [value] if value else (default if default is not None else [])
    
    # Invalid type - return default
    return default if default is not None else []


def normalize_list_field(value: Any, field_name: str = "") -> List[Any]:
    """Normalize a list field that may be None, string, or list.
    
    Convenience wrapper around normalize_to_list with empty list default.
    
    Args:
        value: The value to normalize
        field_name: Optional field name for error messages
        
    Returns:
        Normalized list
    """
    return normalize_to_list(value, default=[])


def normalize_dict_value(
    value: Any,
    pydantic_type: Type[T] | None = None
) -> T | Dict[str, Any] | None:
    """Normalize a dict value by validating against Pydantic type.
    
    If pydantic_type is provided, validates and returns the Pydantic model.
    Otherwise returns the dict as-is if it's a dict.
    
    Args:
        value: Dict value to normalize
        pydantic_type: Optional Pydantic model to validate against
        
    Returns:
        Validated Pydantic model or original dict
    """
    if value is None:
        return None
    
    if not isinstance(value, dict):
        return value
    
    if pydantic_type is not None:
        return pydantic_type(**value)
    
    return value


def normalize_optional_int(value: Any, default: int = 0) -> int:
    """Normalize an optional integer field.
    
    Handles:
    - None → default
    - int → int (unchanged)
    - string digits → int
    - invalid → default
    
    Args:
        value: Value to normalize
        default: Default if value is None/invalid
        
    Returns:
        Integer value
    """
    if value is None:
        return default
    
    if isinstance(value, int):
        return value
    
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    
    return default


def normalize_optional_string(value: Any, default: str = "") -> str:
    """Normalize an optional string field.
    
    Handles:
    - None → default
    - str → str (unchanged)
    - non-string → str(default)
    
    Args:
        value: Value to normalize
        default: Default if value is None/invalid
        
    Returns:
        String value
    """
    if value is None:
        return default
    
    if isinstance(value, str):
        return value
    
    return default


def get_nested_field(obj: Any, path: str, default: Any = None) -> Any:
    """Get a nested field using dot notation.
    
    Example:
        get_nested_field(page, "og_tags.og_title", None)
        
    Args:
        obj: Object to access
        path: Dot-separated path (e.g., "field.subfield")
        default: Default if path not found
        
    Returns:
        Value at path or default
    """
    parts = path.split(".")
    current = obj
    
    for part in parts:
        if current is None:
            return default
        
        if hasattr(current, part):
            current = getattr(current, part)
        elif isinstance(current, dict):
            current = current.get(part)
            if current is None:
                return default
        else:
            return default
    
    return current


def set_nested_field(obj: Dict[str, Any], path: str, value: Any) -> None:
    """Set a nested field using dot notation.
    
    Creates intermediate dicts as needed.
    
    Example:
        set_nested_field(data, "og_tags.og_title", "New Title")
        
    Args:
        obj: Dict to modify
        path: Dot-separated path
        value: Value to set
    """
    parts = path.split(".")
    current = obj
    
    for i, part in enumerate(parts[:-1]):
        if part not in current:
            current[part] = {}
        current = current[part]
    
    current[parts[-1]] = value


def normalize_pydantic_list(
    items: Union[List[Dict], List[BaseModel]],
    model_class: Type[BaseModel],
) -> List[BaseModel]:
    """Normalize a list of dicts to Pydantic models.
    
    Handles mixed lists containing both dicts and Pydantic models.
    
    Args:
        items: List of items to normalize
        model_class: Pydantic model class to validate against
        
    Returns:
        List of validated Pydantic models
        
    Example:
        >>> from myapp.schemas import PageRecord
        >>> pages = normalize_pydantic_list(raw_pages, PageRecord)
    """
    result = []
    for item in items:
        if isinstance(item, model_class):
            result.append(item)
        elif isinstance(item, dict):
            try:
                result.append(model_class(**item))
            except Exception:
                # If validation fails, keep the original dict
                result.append(item)
        else:
            result.append(item)
    return result


def normalize_pydantic_optional(
    value: Any,
    model_class: Type[BaseModel],
) -> Optional[BaseModel]:
    """Normalize a value to a Pydantic model if possible.
    
    Args:
        value: Value to normalize (dict, Pydantic model, or None)
        model_class: Pydantic model class to validate against
        
    Returns:
        Validated Pydantic model, original value, or None
    """
    if value is None:
        return None
    
    if isinstance(value, model_class):
        return value
    
    if isinstance(value, dict):
        try:
            return model_class(**value)
        except Exception:
            return value
    
    return value


def normalize_optional_float(value: Any, default: float = 0.0) -> float:
    """Normalize an optional float field.
    
    Handles:
        - None → default
        - float → float (unchanged)
        - int → float
        - string digits → float
        - invalid → default
        
    Args:
        value: Value to normalize
        default: Default if value is None/invalid
        
    Returns:
        Float value
    """
    if value is None:
        return default
    
    if isinstance(value, float):
        return value
    
    if isinstance(value, (int, str)):
        try:
            return float(value)
        except (ValueError, TypeError):
            return default
    
    return default