import mimetypes
import os
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from src.connectors.base import SourceConnector
from src.models import ItemRef, RawDocument


class FileConnector(SourceConnector):
    """Connector for locally stored documents (PDF, DOCX, TXT)."""

    source_type = "files"

    SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt"}

    MIME_TYPES = {
        ".pdf": "application/pdf",
        ".docx": (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        ".txt": "text/plain",
    }

    def __init__(self, config: dict):
        super().__init__(config)

        self.directory = Path(config.get("directory", "data/docs")).resolve()
        self.recursive = config.get("recursive", True)

        # Files seen but not listed (lock files, unsupported types), with the reason.
        # The pipeline reads this to report "dropped and why".
        self.skipped: list[dict] = []

    def test_connection(self) -> bool:
        """Check whether the documents directory is accessible."""
        return (
            self.directory.exists()
            and self.directory.is_dir()
            and os.access(self.directory, os.R_OK)
        )

    def list_items(self) -> Iterator[ItemRef]:
        """List all supported documents in the directory."""
        if not self.test_connection():
            raise ConnectionError(
                f"Cannot access documents directory: {self.directory}"
            )

        self.skipped = []
        files = (
            self.directory.rglob("*") if self.recursive else self.directory.glob("*")
        )

        for file_path in sorted(files):
            if not file_path.is_file():
                continue

            # Temporary Word lock files (~$name.docx).
            if file_path.name.startswith("~$"):
                self.skipped.append(
                    {"file": file_path.name, "reason": "word_lock_file"}
                )
                continue

            extension = file_path.suffix.lower()
            if extension not in self.SUPPORTED_EXTENSIONS:
                self.skipped.append(
                    {
                        "file": file_path.name,
                        "reason": f"unsupported_extension:{extension}",
                    }
                )
                continue

            resolved_path = file_path.resolve()

            # Never list files outside the configured directory (e.g. via symlinks).
            try:
                relative_path = resolved_path.relative_to(self.directory)
            except ValueError:
                self.skipped.append(
                    {"file": file_path.name, "reason": "outside_directory"}
                )
                continue

            stat = file_path.stat()
            yield ItemRef(
                id=relative_path.as_posix(),
                source_uri=str(resolved_path),
                metadata={
                    "filename": file_path.name,
                    "extension": extension,
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                },
            )

    def fetch(self, ref: ItemRef) -> RawDocument:
        """Retrieve a document and return its raw bytes. Parsing happens later."""
        file_path = Path(ref.source_uri).resolve()

        try:
            file_path.relative_to(self.directory)
        except ValueError as err:
            raise ValueError(
                "Requested file is outside the configured directory."
            ) from err

        if not file_path.is_file():
            raise FileNotFoundError(file_path)

        extension = file_path.suffix.lower()
        if extension not in self.SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported file extension: {extension}")

        content = file_path.read_bytes()

        mime_type = self.MIME_TYPES.get(extension) or (
            mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        )

        return RawDocument(
            id=ref.id,
            source_type=self.source_type,
            source_uri=ref.source_uri,
            content=content,
            mime_type=mime_type,
            metadata={**ref.metadata, "size": len(content)},
        )
