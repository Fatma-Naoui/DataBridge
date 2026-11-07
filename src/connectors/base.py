from abc import ABC, abstractmethod
from collections.abc import Iterator

from src.models import ItemRef, RawDocument


class SourceConnector(ABC):
    """Base interface for all data source connectors."""

    source_type: str

    def __init__(self, config: dict):
        self.config = config

    @abstractmethod
    def test_connection(self) -> bool:
        """Check whether the connector can access its data source."""

    @abstractmethod
    def list_items(self) -> Iterator[ItemRef]:
        """List the available items in the data source."""

    @abstractmethod
    def fetch(self, ref: ItemRef) -> RawDocument:
        """Retrieve an item and return it as a RawDocument."""
