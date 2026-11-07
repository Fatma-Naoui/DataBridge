from pydantic import BaseModel, Field


class ItemRef(BaseModel):
    """Reference to an item available in a data source."""

    id: str
    source_uri: str
    metadata: dict = Field(default_factory=dict)


class RawDocument(BaseModel):
    """Standardized representation of raw data."""

    id: str
    source_type: str
    source_uri: str
    content: str | bytes
    mime_type: str
    metadata: dict = Field(default_factory=dict)
