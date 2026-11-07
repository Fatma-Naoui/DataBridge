from src.connectors.base import SourceConnector
from src.connectors.email import EmailConnector
from src.connectors.files import FileConnector
from src.connectors.sql import SQLConnector

CONNECTORS = {
    cls.source_type: cls for cls in (SQLConnector, FileConnector, EmailConnector)
}


def create_connector(config: dict) -> SourceConnector:
    """Build a connector from a source config containing a 'type' key."""
    source_type = config.get("type")
    if source_type not in CONNECTORS:
        raise ValueError(
            f"Unknown source type: {source_type!r}. Available: {sorted(CONNECTORS)}"
        )
    return CONNECTORS[source_type](config)
