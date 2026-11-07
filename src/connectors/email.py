import csv
import json
import os
from collections.abc import Iterator
from email import policy
from email.parser import BytesParser
from pathlib import Path

from src.connectors.base import SourceConnector
from src.models import ItemRef, RawDocument


class EmailConnector(SourceConnector):
    """Connector for support history: CSV tickets and .eml emails."""

    source_type = "email"

    def __init__(self, config: dict):
        super().__init__(config)

        self.tickets_file = Path(
            config.get("tickets_file", "data/support/tickets.csv")
        ).resolve()
        self.emails_directory = Path(
            config.get("emails_directory", "data/support/emails")
        ).resolve()
        self.encoding = config.get("encoding", "utf-8-sig")

        self._tickets_cache: dict[int, dict] | None = None

    def test_connection(self) -> bool:
        """True if at least one configured source (CSV or .eml folder) is readable."""
        tickets_available = self.tickets_file.is_file() and os.access(
            self.tickets_file, os.R_OK
        )
        emails_available = self.emails_directory.is_dir() and os.access(
            self.emails_directory, os.R_OK
        )
        return tickets_available or emails_available

    def _tickets(self) -> dict[int, dict]:
        """Read the CSV once and cache it: {row_number: row}."""
        if self._tickets_cache is None:
            self._tickets_cache = {}
            if self.tickets_file.is_file():
                with self.tickets_file.open(
                    "r", encoding=self.encoding, errors="replace", newline=""
                ) as csv_file:
                    for row_number, row in enumerate(csv.DictReader(csv_file), start=1):
                        self._tickets_cache[row_number] = row
        return self._tickets_cache

    def list_items(self) -> Iterator[ItemRef]:
        """List individual tickets (one per CSV row) and individual .eml files."""
        if not self.test_connection():
            raise ConnectionError("Cannot access support history sources.")

        # 1. CSV tickets. The row number keeps ids unique even when the
        #    same ticket_id appears twice (exported twice).
        for row_number, row in self._tickets().items():
            ticket_id = (
                row.get("ticket_id")
                or row.get("ticketId")
                or row.get("id")
                or f"row_{row_number}"
            )

            yield ItemRef(
                id=f"ticket:{ticket_id}:row_{row_number}",
                source_uri=str(self.tickets_file),
                metadata={
                    "record_type": "ticket",
                    "ticket_id": str(ticket_id),
                    "row_number": row_number,
                    "filename": self.tickets_file.name,
                    "extension": ".csv",
                },
            )

        # 2. .eml emails.
        if self.emails_directory.is_dir():
            for file_path in sorted(self.emails_directory.rglob("*.eml")):
                if not file_path.is_file():
                    continue

                resolved_path = file_path.resolve()
                try:
                    relative_path = resolved_path.relative_to(self.emails_directory)
                except ValueError:
                    continue

                yield ItemRef(
                    id=f"email:{relative_path.as_posix()}",
                    source_uri=str(resolved_path),
                    metadata={
                        "record_type": "email",
                        "filename": file_path.name,
                        "extension": ".eml",
                    },
                )

    def fetch(self, ref: ItemRef) -> RawDocument:
        """Retrieve a ticket (as JSON text) or an email (as raw bytes)."""
        record_type = ref.metadata.get("record_type")

        # 1. CSV ticket
        if record_type == "ticket":
            if Path(ref.source_uri).resolve() != self.tickets_file:
                raise ValueError("Invalid ticket source.")

            row_number = ref.metadata.get("row_number")
            if not isinstance(row_number, int) or row_number < 1:
                raise ValueError("Invalid ticket row number.")

            ticket = self._tickets().get(row_number)
            if ticket is None:
                raise FileNotFoundError(f"Ticket row {row_number} not found.")

            return RawDocument(
                id=ref.id,
                source_type=self.source_type,
                source_uri=ref.source_uri,
                content=json.dumps(ticket, ensure_ascii=False),
                mime_type="application/json",
                metadata={**ref.metadata},
            )

        # 2. .eml email
        if record_type == "email":
            file_path = Path(ref.source_uri).resolve()

            try:
                file_path.relative_to(self.emails_directory)
            except ValueError as err:
                raise ValueError("Invalid email source.") from err

            if not file_path.is_file():
                raise FileNotFoundError(file_path)

            content = file_path.read_bytes()

            # Headers go into metadata only; the content stays untouched.
            # A badly encoded email must not crash the fetch.
            try:
                message = BytesParser(policy=policy.default).parsebytes(content)
                headers = {
                    "subject": str(message.get("subject", "")),
                    "sender": str(message.get("from", "")),
                    "date": str(message.get("date", "")),
                }
            except Exception:
                headers = {"header_parse_error": True}

            return RawDocument(
                id=ref.id,
                source_type=self.source_type,
                source_uri=ref.source_uri,
                content=content,
                mime_type="message/rfc822",
                metadata={**ref.metadata, **headers},
            )

        raise ValueError(f"Unknown support record type: {record_type}")
