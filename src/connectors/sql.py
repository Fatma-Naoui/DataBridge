import json
from collections.abc import Iterator

from sqlalchemy import MetaData, Table, create_engine, inspect, select

from src.connectors.base import SourceConnector
from src.models import ItemRef, RawDocument


class SQLConnector(SourceConnector):
    """
    Generic SQL connector.

    Discovers database tables and retrieves records dynamically.
    Produces one RawDocument per database row.
    Supports single and composite primary keys.
    """

    source_type = "sql"

    def __init__(self, config: dict):
        super().__init__(config)

        self.connection_string = config.get("connection_string")

        if not self.connection_string:
            raise ValueError("A database connection_string is required.")

        # None means discover all available tables.
        self.tables = config.get("tables")

        if isinstance(self.tables, str):
            self.tables = [self.tables]

        self._engine = None
        self._table_cache = {}

    @property
    def engine(self):
        """Create the database engine lazily."""
        if self._engine is None:
            self._engine = create_engine(self.connection_string)

        return self._engine

    def test_connection(self) -> bool:
        """Check whether the database is reachable."""
        try:
            with self.engine.connect() as conn:
                conn.exec_driver_sql("SELECT 1")

            return True

        except Exception:
            return False

    def _table(self, name: str) -> Table:
        """
        Reflect a database table dynamically.

        SQLAlchemy discovers its columns, data types
        and primary key.
        """
        if name not in self._table_cache:
            self._table_cache[name] = Table(name, MetaData(), autoload_with=self.engine)

        return self._table_cache[name]

    def list_items(self) -> Iterator[ItemRef]:
        """
        Discover tables and list their records.

        Each database row becomes an ItemRef.
        Supports single and composite primary keys.
        """
        if not self.test_connection():
            raise ConnectionError("Cannot connect to the database.")

        inspector = inspect(self.engine)
        available_tables = inspector.get_table_names()

        # Use configured tables or discover all tables.
        tables_to_process = self.tables if self.tables is not None else available_tables

        # Validate configured tables.
        missing_tables = set(tables_to_process) - set(available_tables)

        if missing_tables:
            raise ValueError(f"Tables not found: {sorted(missing_tables)}")

        for name in tables_to_process:
            table = self._table(name)

            # Discover all primary key columns.
            pk_columns = list(table.primary_key.columns)

            if not pk_columns:
                raise ValueError(f"Table '{name}' has no primary key.")

            [column.name for column in pk_columns]

            with self.engine.connect() as conn:
                query = select(*pk_columns)

                for row in conn.execute(query):
                    # Store primary key names and values together.
                    pk_values = {
                        column.name: value
                        for column, value in zip(pk_columns, row, strict=False)
                    }

                    item_id = f"{name}:{json.dumps(pk_values, default=str)}"

                    yield ItemRef(
                        id=item_id,
                        source_uri=f"sql://{item_id}",
                        metadata={"table_name": name, "pk_values": pk_values},
                    )

    def fetch(self, ref: ItemRef) -> RawDocument:
        """
        Fetch one database record using its primary key.

        Works with both single and composite primary keys.
        """

        name = ref.metadata["table_name"]
        pk_values = ref.metadata["pk_values"]

        table = self._table(name)

        # Build WHERE conditions dynamically.
        conditions = [table.c[column] == value for column, value in pk_values.items()]

        with self.engine.connect() as conn:
            query = select(table).where(*conditions)

            row = conn.execute(query).mappings().first()

        if row is None:
            raise FileNotFoundError(
                f"Row not found in '{name}' with primary key {pk_values}"
            )

        row = dict(row)

        # Serialize the database row into JSON.
        content = json.dumps(row, default=str, ensure_ascii=False)

        return RawDocument(
            id=ref.id,
            source_type=self.source_type,
            source_uri=ref.source_uri,
            content=content,
            mime_type="application/json",
            metadata={**ref.metadata, "columns": list(row.keys())},
        )
