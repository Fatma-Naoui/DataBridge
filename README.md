# DataBridge

DataBridge turns raw company data (databases, documents and support emails) into clean, **PII-anonymized** chat datasets ready for fine-tuning a customer-support assistant.

It ingests data from several sources, cleans and deduplicates it, replaces personal information with placeholders such as `[PERSON]` or `[IBAN]`, tags each example by language and domain, and writes `train.jsonl` / `eval.jsonl` files together with a quality report.

The bundled sample data is a multilingual (Dutch / French / English) insurance scenario, but the pipeline is configuration-driven and not tied to it.

## Features

- **Pluggable source connectors**: SQL databases, local documents (PDF, DOCX, TXT) and support history (CSV tickets + `.eml` emails).
- **Robust parsing**: page numbers and repeated headers/footers are stripped from PDFs; DOCX tables are flattened; broken encodings are repaired.
- **Text cleaning**: removes quoted replies, signatures, sign-offs, mobile footers and legal disclaimers (NL / FR / EN).
- **PII anonymization**: combines three layers:
  - regex detection with checksum validation (IBAN via MOD-97, credit cards via Luhn), plus emails, phone numbers and national IDs;
  - named entity recognition (NER) with the [GLiNER](https://github.com/urchade/GLiNER) multilingual PII model (`urchade/gliner_multi_pii-v1`) for names, addresses, organizations, etc. (see [Anonymization and NER](#anonymization-and-ner));
  - a **name gazetteer built from your SQL data**, so known customer names are always caught.
- **Deduplication**: exact (hash) and near-duplicate (MinHash LSH) removal, keeping the most recent version of a document.
- **Tagging**: language (`nl`, `fr`, `en`) and domain (`claims`, `policies`, `billing`, `general`).
- **Email thread pairing**: customer message + agent reply become one Q&A example.
- **Leak-safe splitting**: deterministic, domain-stratified, group-aware train/eval split, so examples from the same document or thread never end up in both files.
- **Validation and reporting**: schema checks, a second PII scan of the final output, train/eval overlap checks, and a Markdown + JSON quality report.
- **Streamlit frontend**: upload files, run the pipeline and inspect results in the browser.

## How it works

```
 Sources                Processing                                          Output
┌──────────┐   ┌────────────────────────────────────────────────────┐   ┌──────────────────┐
│ SQL      │   │ parse → clean → anonymize → dedupe → tag →         │   │ train.jsonl      │
│ Files    │──▶│ pair email threads → build examples → split        │──▶│ eval.jsonl       │
│ Email    │   │                                    → validate      │   │ quality_report.* │
└──────────┘   └────────────────────────────────────────────────────┘   └──────────────────┘
```

1. **Connect, fetch and parse.** Each configured source is tested, listed and fetched; failures are counted instead of crashing the run.
2. **Build the SQL gazetteer.** Names from SQL rows are collected. SQL rows are used as reference data only and are **not** turned into training examples.
3. **Clean** text fields.
4. **Anonymize** `text`, `question` and `answer` fields in batches.
5. **Deduplicate** (after anonymization, newest first).
6. **Tag** language and domain.
7. **Pair** customer and agent emails by thread subject.
8. **Build** chat examples with the configured system prompt.
9. **Split** into train and eval.
10. **Validate** and write the quality report.

## Anonymization and NER

Anonymization lives in `src/processing/anonymize.py` (`Anonymizer`). It uses **named entity recognition (NER)** for free-text PII such as names and addresses, and rules for structured identifiers that follow a fixed format.

### Three detection layers

| Layer | Detects | Notes |
|---|---|---|
| **NER model** ([GLiNER](https://github.com/urchade/GLiNER), `urchade/gliner_multi_pii-v1`) | names, addresses, organizations, dates of birth, national IDs, passport numbers, phone numbers, emails, card numbers | A zero-shot, multilingual model: it is given a list of label names and finds matching spans, with no training on your data. Works across Dutch, French and English. |
| **Regex + checksums** | emails, IBANs, phone numbers, credit cards, national IDs (`###-##-####`) | IBANs must pass the MOD-97 checksum and card numbers the Luhn check, which cuts false positives. Phone matching never overlaps a detected IBAN. |
| **SQL name list** | every name found in your SQL data | Names from columns like `customer_name`, `first_name` + `last_name` are matched case-insensitively as whole words, so known customers are masked even if the NER model misses them. |

### Entity labels and placeholders

The NER model is asked for these labels, and each one is replaced by a placeholder:

| NER label | Placeholder |
|---|---|
| `person` | `[PERSON]` |
| `email` | `[EMAIL]` |
| `phone number` | `[PHONE]` |
| `address` | `[ADDRESS]` |
| `organization` | `[ORGANIZATION]` |
| `date of birth` | `[NATIONAL_ID]` |
| `social security number` | `[NATIONAL_ID]` |
| `passport number` | `[NATIONAL_ID]` |
| `credit card number` | `[CREDIT_CARD]` |

The regex layer additionally produces `[IBAN]`. Note that dates of birth are grouped under `[NATIONAL_ID]`; change `LABEL_MAP` in `anonymize.py` if you want a separate placeholder.

### How detections are combined

1. Long texts are split into fixed-size chunks (`chunk_size` characters) and run through the model in batches (`batch_size`).
2. Regex and SQL-name matches are added to the model's detections, each with a confidence of `1.0`.
3. **Overlaps are resolved** by keeping the highest-confidence entity, and the longest one on a tie. Because rule-based and SQL matches score `1.0`, they take priority over model guesses on the same span.
4. Entities are replaced from the end of the text backwards, so character offsets stay valid, and the replacement counts feed the quality report.
5. Results are cached per text in an in-memory LRU cache (`cache_size`), so repeated texts such as shared signatures are only processed once.

### Tuning

Set these under `anonymizer:` in `config.yaml`:

| Option | Effect |
|---|---|
| `threshold` | Minimum model confidence. Lower it to catch more PII (more false positives); raise it to be stricter about what gets masked. |
| `skipwords` | Words that must never be masked, e.g. your company or product name, if the model keeps flagging them as organizations. Matching is case-insensitive. |
| `chunk_size` / `batch_size` | Memory and speed trade-offs for model inference. |
| `record_batch_size` | How many records are anonymized per batch in the pipeline. |
| `cache_size` | Maximum number of cached texts (`0` disables the cache). |
| `model_name` | Any GLiNER-compatible model from Hugging Face. |

To change which entity types are detected, edit `Anonymizer.LABELS` and `Anonymizer.LABEL_MAP`. Since GLiNER is zero-shot, you can add labels such as `"license plate"` without retraining, but check the results on a sample first.

### Limitations

- NER is probabilistic: some PII will be missed and some harmless words will be masked. The validation step catches leftover *structured* PII (emails, IBANs, cards, phone numbers, national IDs), but it **cannot detect missed names or addresses**, so spot-check `train.jsonl` and `eval.jsonl` manually.
- Chunks are cut at fixed character positions without overlap, so an entity that straddles a chunk boundary in a very long text can be missed or split.
- The model is downloaded from Hugging Face on first use and runs locally; no text is sent to an external API for anonymization.

## Project structure

```
DataBridge/
├── config.yaml              # Pipeline configuration
├── run.py                   # CLI entry point
├── frontend/
│   └── app.py               # Streamlit app
├── src/
│   ├── models.py            # ItemRef, RawDocument, Record (Pydantic)
│   ├── pipeline.py          # Orchestrates the whole run
│   ├── connectors/
│   │   ├── base.py          # SourceConnector interface
│   │   ├── registry.py      # type → connector lookup
│   │   ├── sql.py           # SQLConnector
│   │   ├── files.py         # FileConnector (.pdf, .docx, .txt)
│   │   └── email.py         # EmailConnector (tickets.csv + .eml)
│   ├── processing/
│   │   ├── parse.py         # MIME type → Record parsers
│   │   ├── clean.py         # Boilerplate and encoding cleanup
│   │   ├── anonymize.py     # Regex + GLiNER + gazetteer PII masking
│   │   ├── dedup.py         # Exact + MinHash LSH deduplication
│   │   ├── tag.py           # Language and domain tagging
│   │   ├── build.py         # Thread pairing, example building, split
│   │   └── validate.py      # Output validation
│   └── output/
│       └── report.py        # quality_report.json / .md
├── data/                    # Sample data (db, docs, support emails/tickets)
├── output/                  # Generated datasets and reports
└── tests/
```

## Getting started

### Requirements

- Python 3.12 or newer
- [uv](https://docs.astral.sh/uv/) (the repo ships a `uv.lock`)
- Internet access on the first run, to download the GLiNER model from Hugging Face

### Install

```bash
git clone https://github.com/Fatma-Naoui/DataBridge.git
cd DataBridge
uv sync
```

### Run the pipeline (CLI)

```bash
uv run python run.py                        # uses config.yaml
uv run python run.py --config my_config.yaml
```

The run prints the quality statistics as JSON and writes its results to `output/`.

### Run the web app

```bash
uv run streamlit run frontend/app.py
```

In the app you:

1. **Upload files**: databases (`.db`, `.sqlite`, `.sqlite3`), documents (`.pdf`, `.docx`, `.txt`) and emails (`.eml`). Detected files and their support status are listed.
2. **Run the pipeline** on your uploads (combined with the sources in `config.yaml`).
3. **Inspect the results**: counts, language and domain distributions, dropped items and validation status, with downloads available.

Uploaded files are stored under `data/streamlit_uploads/`.

### Validate existing output

```bash
uv run python -m src.processing.validate --dir output
```

Exits with code `0` if validation passes and `1` otherwise.

### Tests and linting

```bash
uv run pytest
uv run ruff check .
uv run ruff format .
```

## Configuration

All behavior is controlled by `config.yaml`:

| Key | Description |
|---|---|
| `system_prompt` | System message added to every training example. |
| `agent_domains` | Sender domains that identify **agent** emails (everything else is treated as a customer). |
| `sources` | List of data sources (see below). |
| `sql_anonymization` | Column names used to extract person names from SQL rows for the gazetteer (`full_name_columns`, `first_name_column`, `last_name_column`). |
| `anonymizer.model_name` | GLiNER model used for PII detection. |
| `anonymizer.threshold` | Minimum confidence for a detected entity (default `0.5`). |
| `anonymizer.chunk_size` / `batch_size` / `record_batch_size` | Text chunk size, model batch size and number of records anonymized per batch. |
| `anonymizer.cache_size` | Size of the detection cache. |
| `anonymizer.skipwords` | Words that should never be masked. |
| `dedup_threshold` | Similarity threshold for near-duplicate detection (default `0.85`). |
| `eval_pct` | Percentage of groups held out for evaluation (default `15`). |
| `output_dir` | Where results are written (default `output`). |

### Sources

```yaml
sources:
  - type: sql
    connection_string: "sqlite:///data/db/insurer.sqlite"
    # tables: [customers, claims]   # optional; omit to discover all tables

  - type: files
    directory: data/docs
    # recursive: true               # default

  - type: email
    tickets_file: data/support/tickets.csv
    emails_directory: data/support/emails
```

- **`sql`**: any SQLAlchemy connection string. Every table (or the ones listed under `tables`) is read row by row; each table needs a primary key (composite keys are supported).
- **`files`**: `.pdf`, `.docx` and `.txt` files. Word lock files (`~$…`), unsupported extensions and files outside the directory are skipped and reported.
- **`email`**: a CSV of tickets plus a folder of `.eml` files. Ticket columns such as `question` / `body` / `description` and `answer` / `resolution` / `agent_reply` are detected automatically.

## Output

| File | Contents |
|---|---|
| `output/train.jsonl` | Training examples. |
| `output/eval.jsonl` | Held-out evaluation examples. |
| `output/quality_report.json` | Machine-readable run statistics. |
| `output/quality_report.md` | Human-readable summary of the same statistics. |

Each line is a chat-format example with metadata:

```json
{
  "messages": [
    {"role": "system", "content": "You are a helpful customer support assistant. ..."},
    {"role": "user", "content": "Polis opzeggen\nBeste,\n\n[PERSON] wil mijn autoverzekering ... beëindigen."},
    {"role": "assistant", "content": "Beste [PERSON],\n\nBedankt voor uw bericht. ... [EMAIL] ..."}
  ],
  "meta": {
    "domain": "policies",
    "language": "nl",
    "source_ids": ["ticket:T-100001:row_1"]
  }
}
```

PII is replaced with bracketed labels like `[PERSON]`, `[EMAIL]`, `[PHONE]`, `[IBAN]`, `[ADDRESS]`, `[ORGANIZATION]` and `[NATIONAL_ID]`.

### Quality report

The report covers records ingested per source, items dropped and why (e.g. `pdf_unreadable`, `word_lock_file`, `exact_duplicate`, `near_duplicate`, `empty_after_cleaning`, `unpaired_thread`), duplicates removed, PII replaced by type, language and domain distributions, the train/eval split, and the validation result.

### Validation checks

- Every example has exactly `system`, `user`, `assistant` messages with non-empty content.
- `meta.source_ids` is present.
- No remaining emails, IBANs, credit cards, national IDs or phone numbers in user/assistant messages.
- No identical user messages or shared source IDs between train and eval.
- Warnings for very short answers and for unknown language or domain tags.

## Extending DataBridge

**Add a new source type**

1. Subclass `SourceConnector` in `src/connectors/` and implement `test_connection()`, `list_items()` and `fetch()`. Set a unique `source_type`.
2. Register the class in `src/connectors/registry.py`.
3. Reference it in `config.yaml` with `type: <your_source_type>`.

**Support a new file format**

Register a parser for its MIME type in `src/processing/parse.py`:

```python
@parser("text/html")
def _html(raw, cfg):
    ...
    return [Record(id=raw.id, source_type=raw.source_type, kind="doc", text=text, metadata=raw.metadata)]
```

If the file connector should pick it up, also add the extension to `SUPPORTED_EXTENSIONS` and `MIME_TYPES` in `src/connectors/files.py`.

**Add a domain or language**

Domains and their keywords live in `src/processing/tag.py` (`DOMAINS`, `TABLE_HINTS`); the language detector is configured at the top of the same file. Update the allowed values in `src/processing/validate.py` too.