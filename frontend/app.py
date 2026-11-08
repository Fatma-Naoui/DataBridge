import hashlib
import mimetypes
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

import streamlit as st
import yaml

# --------------------------------------------------
# Project imports
# --------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from run import run  # noqa: E402

# --------------------------------------------------
# Configuration
# --------------------------------------------------

CONFIG_PATH = ROOT / "config.yaml"
UPLOAD_ROOT = ROOT / "data" / "streamlit_uploads"

DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".txt"}
EMAIL_EXTENSIONS = {".eml"}
DATABASE_EXTENSIONS = {".db", ".sqlite", ".sqlite3"}

SUPPORTED_EXTENSIONS = DOCUMENT_EXTENSIONS | EMAIL_EXTENSIONS | DATABASE_EXTENSIONS


def load_config():
    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file)


def save_uploads(uploaded_files, upload_dir):
    """Save uploaded files and return their detected metadata."""
    upload_dir.mkdir(parents=True, exist_ok=True)

    detected = []

    for uploaded_file in uploaded_files:
        filename = Path(uploaded_file.name).name
        extension = Path(filename).suffix.lower()

        destination = upload_dir / filename
        destination.write_bytes(uploaded_file.getvalue())

        detected.append(
            {
                "filename": filename,
                "extension": extension or "No extension",
                "size": destination.stat().st_size,
                "mime_type": (
                    mimetypes.guess_type(filename)[0] or "application/octet-stream"
                ),
                "supported": extension in SUPPORTED_EXTENSIONS,
            }
        )

    return detected


# --------------------------------------------------
# Document source preparation
# --------------------------------------------------


def prepare_file_source(config, upload_dir, temp_dir):
    """Combine existing documents with uploaded documents."""

    file_sources = [
        source for source in config["sources"] if source.get("type") == "files"
    ]

    combined_dir = temp_dir / "documents"
    combined_dir.mkdir(parents=True, exist_ok=True)

    if file_sources:
        source = file_sources[0]

        original_dir = Path(source.get("directory", "data/docs"))

        if not original_dir.is_absolute():
            original_dir = ROOT / original_dir

        if original_dir.exists():
            shutil.copytree(
                original_dir,
                combined_dir / "existing",
                dirs_exist_ok=True,
            )

        source["directory"] = str(combined_dir)
        source["recursive"] = True

    else:
        source = {
            "type": "files",
            "directory": str(combined_dir),
            "recursive": True,
        }

        config["sources"].append(source)

    # Copy uploaded documents.
    for item in upload_dir.iterdir():
        if item.is_file() and item.suffix.lower() in DOCUMENT_EXTENSIONS:
            destination = combined_dir / "uploaded" / item.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, destination)


# --------------------------------------------------
# Email source preparation
# --------------------------------------------------


def prepare_email_source(config, upload_dir, temp_dir):
    """Combine existing emails with uploaded EML files."""

    email_sources = [
        source for source in config["sources"] if source.get("type") == "email"
    ]

    combined_dir = temp_dir / "emails"
    combined_dir.mkdir(parents=True, exist_ok=True)

    if email_sources:
        source = email_sources[0]

        original_dir = Path(source.get("emails_directory", "data/support/emails"))

        if not original_dir.is_absolute():
            original_dir = ROOT / original_dir

        if original_dir.exists():
            shutil.copytree(
                original_dir,
                combined_dir / "existing",
                dirs_exist_ok=True,
            )

        source["emails_directory"] = str(combined_dir)

    else:
        source = {
            "type": "email",
            "emails_directory": str(combined_dir),
        }

        config["sources"].append(source)

    # Copy uploaded EML files.
    for item in upload_dir.iterdir():
        if item.is_file() and item.suffix.lower() in EMAIL_EXTENSIONS:
            destination = combined_dir / "uploaded" / item.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, destination)


# --------------------------------------------------
# SQL source preparation
# --------------------------------------------------


def prepare_sql_source(config, upload_dir):
    """Keep configured SQL sources and add uploaded SQLite databases."""

    sql_sources = [
        source for source in config["sources"] if source.get("type") == "sql"
    ]

    for item in upload_dir.iterdir():
        if not item.is_file():
            continue

        if item.suffix.lower() not in DATABASE_EXTENSIONS:
            continue

        database_path = item.resolve()

        sql_sources.append(
            {
                "type": "sql",
                "connection_string": (f"sqlite:///{database_path.as_posix()}"),
            }
        )

    config["sources"] = [
        source for source in config["sources"] if source.get("type") != "sql"
    ] + sql_sources


# --------------------------------------------------
# Utility functions
# --------------------------------------------------


def display_distribution(title, values):
    st.subheader(title)

    if values:
        st.bar_chart(values)
    else:
        st.caption("No data available.")


def get_fingerprint(files, upload_dir):
    """Create a fingerprint from uploaded file names and contents."""

    fingerprint_data = []

    for item in files:
        path = upload_dir / item["filename"]

        fingerprint_data.append(
            (
                item["filename"],
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        )

    return hashlib.sha256(repr(sorted(fingerprint_data)).encode("utf-8")).hexdigest()


# --------------------------------------------------
# Page setup
# --------------------------------------------------

st.set_page_config(
    page_title="DataBridge",
    page_icon="🔗",
    layout="wide",
)

st.title("🔗 DataBridge")

st.caption("Document, email and database ingestion, processing and PII anonymization")

st.divider()


# --------------------------------------------------
# Upload section
# --------------------------------------------------

st.header("1. Upload your files")

st.write(
    "Upload multiple documents, emails and SQLite databases. "
    "DataBridge will automatically detect their formats. "
    "Click Run pipeline when you are ready to process them."
)

uploaded_files = st.file_uploader(
    "Choose files",
    type=[
        "pdf",
        "docx",
        "txt",
        "eml",
        "db",
        "sqlite",
        "sqlite3",
    ],
    accept_multiple_files=True,
    help=("Supported formats: PDF, DOCX, TXT, EML, DB, SQLITE and SQLITE3."),
)


# --------------------------------------------------
# Upload session
# --------------------------------------------------

session_id = st.session_state.setdefault(
    "upload_session_id",
    uuid.uuid4().hex,
)

session_upload_dir = UPLOAD_ROOT / session_id

detected_files = save_uploads(
    uploaded_files or [],
    session_upload_dir,
)


# --------------------------------------------------
# File detection results
# --------------------------------------------------

supported_files = [item for item in detected_files if item["supported"]]

if detected_files:
    st.subheader("Detected files")

    st.dataframe(
        [
            {
                "Filename": item["filename"],
                "Extension": item["extension"],
                "Size (KB)": round(item["size"] / 1024, 2),
                "MIME type": item["mime_type"],
                "Status": ("Supported" if item["supported"] else "Unsupported"),
                "Type": (
                    "SQLite database"
                    if item["extension"] in DATABASE_EXTENSIONS
                    else "Email"
                    if item["extension"] in EMAIL_EXTENSIONS
                    else "Document"
                ),
            }
            for item in detected_files
        ],
        use_container_width=True,
        hide_index=True,
    )

    col1, col2, col3 = st.columns(3)

    col1.metric(
        "Uploaded files",
        len(detected_files),
    )

    col2.metric(
        "Supported files",
        len(supported_files),
    )

    col3.metric(
        "Unsupported files",
        len(detected_files) - len(supported_files),
    )

    if len(detected_files) != len(supported_files):
        st.warning("Some files have unsupported extensions and will not be processed.")

else:
    st.info("No files uploaded yet.")


# --------------------------------------------------
# Pipeline execution
# --------------------------------------------------

st.divider()

st.header("2. Run pipeline")

st.write(
    "The pipeline will ingest your configured sources "
    "and uploaded files, clean and anonymize records, "
    "remove duplicates, tag records and generate datasets."
)

current_fingerprint = (
    get_fingerprint(supported_files, session_upload_dir) if supported_files else None
)

if current_fingerprint != st.session_state.get("last_processed_fingerprint"):
    st.session_state.pop("pipeline_stats", None)


if not supported_files:
    st.info("Upload at least one supported file to run the pipeline.")


run_pipeline = st.button(
    "▶ Run pipeline",
    type="primary",
    disabled=not supported_files,
    use_container_width=True,
)


if run_pipeline:
    try:
        config = load_config()

        with st.status(
            "DataBridge is processing your files...",
            expanded=True,
        ) as status:
            data_directory = ROOT / "data"
            data_directory.mkdir(parents=True, exist_ok=True)

            with tempfile.TemporaryDirectory(dir=data_directory) as temporary_directory:
                temp_dir = Path(temporary_directory)

                # Documents
                st.write("Preparing document sources...")

                prepare_file_source(
                    config,
                    session_upload_dir,
                    temp_dir,
                )

                # Emails
                st.write("Preparing email sources...")

                prepare_email_source(
                    config,
                    session_upload_dir,
                    temp_dir,
                )

                # Databases
                st.write("Preparing SQL database sources...")

                prepare_sql_source(
                    config,
                    session_upload_dir,
                )

                # Output directory
                output_dir = Path(config.get("output_dir", "output"))

                if not output_dir.is_absolute():
                    config["output_dir"] = str(ROOT / output_dir)

                # Run original pipeline
                st.write(
                    "Running ingestion, cleaning, anonymization, "
                    "deduplication and dataset generation..."
                )

                stats = run(config)

            st.session_state["pipeline_stats"] = stats

            st.session_state["last_processed_fingerprint"] = current_fingerprint

            st.session_state["pipeline_success"] = True

            status.update(
                label="Processing completed successfully!",
                state="complete",
                expanded=False,
            )

        st.success("Pipeline completed successfully!")

    except Exception as error:
        st.session_state["pipeline_success"] = False

        st.session_state.pop(
            "pipeline_stats",
            None,
        )

        st.session_state["last_processed_fingerprint"] = None

        st.error(f"Pipeline failed: {error}")
        st.exception(error)


# --------------------------------------------------
# Pipeline results
# --------------------------------------------------

stats = st.session_state.get("pipeline_stats")

if stats:
    st.divider()

    st.header("3. Pipeline results")

    ingested = stats.get("ingested_per_source", {})
    pii = stats.get("pii_replaced", {})
    split = stats.get("split", {})
    duplicates = stats.get("duplicates_removed", {})

    col1, col2, col3, col4 = st.columns(4)

    col1.metric(
        "Records ingested",
        sum(ingested.values()),
    )

    col2.metric(
        "PII replacements",
        sum(pii.values()),
    )

    col3.metric(
        "Duplicates removed",
        sum(duplicates.values()),
    )

    col4.metric(
        "Generated examples",
        split.get("train", 0) + split.get("eval", 0),
    )

    # Ingestion
    st.subheader("Ingestion per source")

    st.bar_chart(ingested)

    # Distributions
    col1, col2 = st.columns(2)

    with col1:
        display_distribution(
            "PII replacements",
            pii,
        )

    with col2:
        display_distribution(
            "Train / evaluation split",
            split,
        )

    col1, col2 = st.columns(2)

    with col1:
        display_distribution(
            "Language distribution",
            stats.get("language_distribution", {}),
        )

    with col2:
        display_distribution(
            "Domain distribution",
            stats.get("domain_distribution", {}),
        )

    st.divider()

    # --------------------------------------------------
    # Validation
    # --------------------------------------------------

    st.header("4. Validation")

    validation = stats.get("validation", {})
    validation_ok = validation.get("ok", False)

    if validation_ok:
        st.success("Validation passed.")
    else:
        st.error("Validation failed.")

    col1, col2 = st.columns(2)

    col1.metric(
        "Errors",
        len(validation.get("errors", [])),
    )

    col2.metric(
        "Warnings",
        len(validation.get("warnings", [])),
    )

    if validation.get("errors"):
        with st.expander("View validation errors"):
            for error in validation["errors"]:
                st.error(error)

    if validation.get("warnings"):
        with st.expander("View validation warnings"):
            for warning in validation["warnings"]:
                st.warning(warning)

    st.divider()

    # --------------------------------------------------
    # Quality report
    # --------------------------------------------------

    st.header("5. Quality report")

    with st.expander("View complete pipeline statistics"):
        st.json(stats)

    # --------------------------------------------------
    # Download outputs
    # --------------------------------------------------

    st.header("6. Download outputs")

    output_dir = Path(load_config().get("output_dir", "output"))

    if not output_dir.is_absolute():
        output_dir = ROOT / output_dir

    output_files = [
        (
            "Training dataset",
            output_dir / "train.jsonl",
            "application/x-ndjson",
        ),
        (
            "Evaluation dataset",
            output_dir / "eval.jsonl",
            "application/x-ndjson",
        ),
        (
            "Quality report (JSON)",
            output_dir / "quality_report.json",
            "application/json",
        ),
        (
            "Quality report (Markdown)",
            output_dir / "quality_report.md",
            "text/markdown",
        ),
    ]

    for label, path, mime_type in output_files:
        if path.exists():
            st.download_button(
                label=f"Download {label}",
                data=path.read_bytes(),
                file_name=path.name,
                mime=mime_type,
                use_container_width=True,
            )

        else:
            st.caption(f"{label}: not generated.")

else:
    st.info("Pipeline results will appear here after you run processing.")
