"""Pydantic schema for schema markup map."""
from typing import Any, Dict, List
from pydantic import BaseModel


class SchemaEntry(BaseModel):
    page_url: str
    schema_type: str  # "Organization", "Article", "Product", "FAQPage"
    json_ld: Dict[str, Any]  # JSON-LD object
    notes: str


class SchemaMapSchema(BaseModel):
    total_schemas: int
    schemas: List[SchemaEntry]
