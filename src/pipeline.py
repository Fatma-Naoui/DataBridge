import json
from collections import Counter, defaultdict
from pathlib import Path

from src.connectors.registry import create_connector
from src.models import Record
from src.output.report import generate_report
from src.processing.anonymize import Anonymizer
from src.processing.build import build_examples, pair_threads, split
from src.processing.clean import clean
from src.processing.dedup import dedupe
from src.processing.parse import ParseError, parse
from src.processing.tag import tag_domain, tag_language
from src.processing.validate import validate

FIELDS = ("text", "question", "answer")


def run(cfg: dict) -> dict:
    ingested = Counter()
    pii = Counter()
    dropped: dict[str, Counter] = defaultdict(Counter)
    failed_sources = []

    # 1. Connect, fetch and parse.
    records: list[Record] = []

    for src in cfg["sources"]:
        conn = create_connector(src)
        source_type = conn.source_type

        if not conn.test_connection():
            failed_sources.append(source_type)
            continue

        for ref in conn.list_items():
            try:
                raw = conn.fetch(ref)
                ingested[source_type] += 1
                records.extend(parse(raw, cfg))

            except ParseError as exc:
                dropped[source_type][str(exc)] += 1

            except Exception as exc:
                dropped[source_type][f"error:{type(exc).__name__}"] += 1

        for skipped in getattr(conn, "skipped", []):
            dropped[source_type][skipped["reason"]] += 1

    # 2. Build SQL gazetteer.
    known_names = {
        name.strip()
        for record in records
        if record.source_type == "sql" and record.kind == "row"
        for name in record.metadata.get("_names", [])
        if isinstance(name, str) and name.strip()
    }

    # SQL rows are reference data, not training records.
    dataset_records = [
        record
        for record in records
        if not (record.source_type == "sql" and record.kind == "row")
    ]

    # 3. Clean records.
    cleaned = []

    for record in dataset_records:
        record.text = clean(record.text)
        record.question = clean(record.question or "")
        record.answer = clean(record.answer or "")

        if not record.body.strip():
            dropped[record.source_type]["empty_after_cleaning"] += 1
            continue

        cleaned.append(record)

    # 4. Initialize anonymizer.
    anonymizer_cfg = cfg.get("anonymizer", {})

    anonymize_batch = anonymizer_cfg.get("record_batch_size", 500)

    if anonymize_batch < 1:
        raise ValueError("anonymizer.record_batch_size must be greater than 0")

    anonymizer = Anonymizer(
        threshold=anonymizer_cfg.get("threshold", 0.5),
        chunk_size=anonymizer_cfg.get("chunk_size", 1000),
        batch_size=anonymizer_cfg.get("batch_size", 16),
        cache_size=anonymizer_cfg.get("cache_size", 50_000),
        skipwords=set(anonymizer_cfg.get("skipwords", [])),
        model_name=anonymizer_cfg.get(
            "model_name",
            "urchade/gliner_multi_pii-v1",
        ),
        known_names=known_names,
    )

    # 5. Anonymize records in batches.
    for i in range(0, len(cleaned), anonymize_batch):
        batch = cleaned[i : i + anonymize_batch]

        jobs = [
            (record, field)
            for record in batch
            for field in FIELDS
            if getattr(record, field)
        ]

        results = anonymizer.anonymize_many(
            [getattr(record, field) for record, field in jobs]
        )

        for (record, field), (value, counts) in zip(
            jobs,
            results,
            strict=False,
        ):
            setattr(record, field, value)
            record.pii = dict(Counter(record.pii) + counts)

    # 6. Deduplicate after anonymization.
    cleaned.sort(
        key=lambda record: record.metadata.get("modified", ""),
        reverse=True,
    )

    kept, duplicates = dedupe(
        cleaned,
        cfg.get("dedup_threshold", 0.85),
    )

    for record, reason, _ in duplicates:
        dropped[record.source_type][reason] += 1

    for record in kept:
        pii.update(record.pii)

    # 7. Tag language and domain.
    for record in kept:
        record.language = tag_language(record.body)
        record.domain = tag_domain(
            record.question or record.text,
            record.metadata,
        )

    # 8. Pair email threads.
    kept, unpaired = pair_threads(kept)

    if unpaired:
        dropped["email"]["unpaired_thread"] += unpaired

    # 9. Build examples using the static system prompt.
    examples = build_examples(
        kept,
        cfg["system_prompt"],
    )

    train, ev = split(
        examples,
        cfg.get("eval_pct", 15),
    )

    # 10. Write datasets.
    output_dir = Path(cfg.get("output_dir", "output"))
    output_dir.mkdir(parents=True, exist_ok=True)

    for name, data in (
        ("train", train),
        ("eval", ev),
    ):
        lines = "\n".join(json.dumps(item, ensure_ascii=False) for item in data)

        (output_dir / f"{name}.jsonl").write_text(
            lines + "\n",
            encoding="utf-8",
        )

    # 11. Generate report.
    stats = {
        "ingested_per_source": dict(ingested),
        "failed_sources": failed_sources,
        "dropped": {source: dict(counts) for source, counts in dropped.items()},
        "duplicates_removed": {
            "exact": sum(
                1 for _, reason, _ in duplicates if reason == "exact_duplicate"
            ),
            "near": sum(1 for _, reason, _ in duplicates if reason == "near_duplicate"),
        },
        "sql_gazetteer": {
            "known_names": len(known_names),
        },
        "pii_replaced": dict(pii),
        "language_distribution": dict(
            Counter(example["meta"]["language"] for example in examples)
        ),
        "domain_distribution": dict(
            Counter(example["meta"]["domain"] for example in examples)
        ),
        "split": {
            "train": len(train),
            "eval": len(ev),
        },
        "validation": validate(output_dir),
    }

    return generate_report(stats, output_dir)
