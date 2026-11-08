import html
import io
import json
import re
from collections import Counter
from email import policy
from email.parser import BytesParser

from src.models import RawDocument, Record


class ParseError(Exception):
    """Raised with a short reason code, used in the dropped report."""


PARSERS = {}


def parser(*mimes):
    def register(fn):
        for mime in mimes:
            PARSERS[mime] = fn
        return fn

    return register


def parse(raw: RawDocument, cfg: dict) -> list[Record]:
    fn = PARSERS.get(raw.mime_type)

    if fn is None:
        raise ParseError(f"unsupported_mime:{raw.mime_type}")

    return fn(raw, cfg)


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _doc(raw: RawDocument, text: str) -> Record:
    return Record(
        id=raw.id,
        source_type=raw.source_type,
        kind="doc",
        text=text,
        metadata=raw.metadata,
    )


def _strip_running_lines(pages: list[str]) -> list[str]:
    """Drop page numbers and headers/footers repeated on most pages."""

    page_no = re.compile(
        r"^\s*(page|pagina|p\.?)?\s*\d+"
        r"(\s*(/|of|sur|van)\s*\d+)?\s*$",
        re.I,
    )

    if len(pages) >= 3:
        counts = Counter(
            line.strip()
            for page in pages
            for line in set(page.splitlines())
            if line.strip()
        )

        repeated = {line for line, count in counts.items() if count >= 0.6 * len(pages)}
    else:
        repeated = set()

    return [
        "\n".join(
            line
            for line in page.splitlines()
            if line.strip() not in repeated and not page_no.match(line)
        )
        for page in pages
    ]


@parser("application/pdf")
def _pdf(raw, cfg):
    from pypdf import PdfReader

    try:
        pages = [
            page.extract_text() or ""
            for page in PdfReader(io.BytesIO(raw.content)).pages
        ]
    except Exception as exc:
        raise ParseError(f"pdf_unreadable:{type(exc).__name__}") from exc

    text = "\n\n".join(_strip_running_lines(pages)).strip()

    if not text:
        raise ParseError("pdf_no_text")

    return [_doc(raw, text)]


@parser("application/vnd.openxmlformats-officedocument.wordprocessingml.document")
def _docx(raw, cfg):
    from docx import Document

    try:
        document = Document(io.BytesIO(raw.content))
    except Exception as exc:
        raise ParseError(f"docx_unreadable:{type(exc).__name__}") from exc

    parts = [paragraph.text for paragraph in document.paragraphs]

    for table in document.tables:
        parts.extend(
            " | ".join(cell.text.strip() for cell in row.cells) for row in table.rows
        )

    text = "\n".join(parts).strip()

    if not text:
        raise ParseError("docx_empty")

    return [_doc(raw, text)]


@parser("text/plain")
def _txt(raw, cfg):
    data = raw.content if isinstance(raw.content, bytes) else raw.content.encode()

    return [_doc(raw, _decode(data))]


def _thread_key(subject: str) -> str:
    return (
        re.sub(
            r"^\s*((re|fw|fwd|tr|aw|antw)\s*:\s*)+",
            "",
            subject,
            flags=re.I,
        )
        .strip()
        .lower()
    )


@parser("message/rfc822")
def _eml(raw, cfg):
    try:
        msg = BytesParser(policy=policy.default).parsebytes(raw.content)

        body = msg.get_body(preferencelist=("plain", "html"))
        text = body.get_content() if body else ""

        if body and body.get_content_type() == "text/html":
            text = html.unescape(re.sub(r"<[^>]+>", " ", text))

    except Exception as exc:
        raise ParseError(f"eml_unreadable:{type(exc).__name__}") from exc

    sender = raw.metadata.get("sender", "").lower()

    agent = any(domain in sender for domain in cfg.get("agent_domains", []))

    metadata = {
        **raw.metadata,
        "role": "agent" if agent else "customer",
        "thread": (_thread_key(raw.metadata.get("subject", "")) or raw.id),
    }

    return [
        Record(
            id=raw.id,
            source_type=raw.source_type,
            kind="message",
            text=text,
            metadata=metadata,
        )
    ]


# Column names differ between client exports.
Q_COLS = (
    "question",
    "body",
    "description",
    "message",
    "customer_message",
)

A_COLS = (
    "answer",
    "resolution",
    "response",
    "reply",
    "agent_reply",
)


def _extract_names(row: dict, cfg: dict) -> list[str]:
    """
    Extract full names from configured SQL columns.

    Supports:
    - customer_name
    - contact_name
    - policyholder_name
    - full_name
    - name
    - first_name + last_name
    """

    sql_cfg = cfg.get("sql_anonymization", {})

    full_name_columns = sql_cfg.get(
        "full_name_columns",
        [
            "customer_name",
            "contact_name",
            "policyholder_name",
            "full_name",
            "name",
        ],
    )

    first_name_column = sql_cfg.get(
        "first_name_column",
        "first_name",
    )

    last_name_column = sql_cfg.get(
        "last_name_column",
        "last_name",
    )

    names = []

    first_name = row.get(first_name_column)
    last_name = row.get(last_name_column)

    if first_name and last_name:
        full_name = f"{first_name} {last_name}".strip()
        names.append(full_name)

    for column in full_name_columns:
        value = row.get(column)

        if value is None:
            continue

        value = str(value).strip()

        if value:
            names.append(value)

    # Remove duplicates while preserving order.
    return list(dict.fromkeys(names))


@parser("application/json")
def _json(raw, cfg):
    try:
        row = json.loads(raw.content)
    except (ValueError, TypeError) as exc:
        raise ParseError("json_invalid") from exc

    if not isinstance(row, dict):
        raise ParseError("json_not_object")

    # SQL rows are used to build the name gazetteer.
    if "table_name" in raw.metadata:
        names = _extract_names(row, cfg)

        text = "\n".join(
            f"{key}: {value}" for key, value in row.items() if value not in (None, "")
        )

        metadata = {
            **raw.metadata,
            "_names": names,
        }

        return [
            Record(
                id=raw.id,
                source_type=raw.source_type,
                kind="row",
                text=text,
                metadata=metadata,
            )
        ]

    # Ordinary JSON documents / tickets.
    def pick(columns):
        for column in columns:
            value = row.get(column)

            if value is not None and value != "":
                return str(value)

        return ""

    question = pick(cfg.get("question_cols", Q_COLS))
    answer = pick(cfg.get("answer_cols", A_COLS))
    subject = row.get("subject", "")

    return [
        Record(
            id=raw.id,
            source_type=raw.source_type,
            kind="qa",
            question=f"{subject}\n{question}".strip(),
            answer=answer,
            metadata=raw.metadata,
        )
    ]
