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


class Record(BaseModel):
    """Parsed content moving through the pipeline."""

    id: str
    source_type: str
    kind: str  # "doc" | "row" | "qa" | "message"
    text: str = ""
    question: str | None = None
    answer: str | None = None
    metadata: dict = Field(default_factory=dict)
    language: str | None = None
    domain: str | None = None
    pii: dict[str, int] = Field(default_factory=dict)

    @property
    def body(self) -> str:
        return self.text or f"{self.question or ''}\n{self.answer or ''}"
