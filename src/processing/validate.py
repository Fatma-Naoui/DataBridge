import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

from src.processing.anonymize import find_remaining_pii

LANGS = {"nl", "fr", "en"}
DOMAINS = {"claims", "policies", "billing", "general"}
ROLES = ["system", "user", "assistant"]
MIN_ANSWER_CHARS = 20


def _norm(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()


def _load(path: Path, errors: list) -> list[tuple[int, dict]]:

    if not path.is_file():
        errors.append(f"{path.name}: file missing")
        return []

    rows = []

    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue

        try:
            rows.append((n, json.loads(line)))
        except ValueError:
            errors.append(f"{path.name}:{n}: invalid JSON")

    return rows


def _check_example(
    name: str,
    n: int,
    ex: dict,
    errors: list,
    warnings: list,
    leaks: Counter,
):

    where = f"{name}:{n}"
    msgs = ex.get("messages")

    if (
        not isinstance(msgs, list)
        or [m.get("role") if isinstance(m, dict) else None for m in msgs] != ROLES
    ):
        errors.append(f"{where}: messages must be system, user, assistant")
        return

    if any(
        not isinstance(m.get("content"), str) or not m["content"].strip() for m in msgs
    ):
        errors.append(f"{where}: empty message content")
        return

    if len(msgs[2]["content"].strip()) < MIN_ANSWER_CHARS:
        warnings.append(f"{where}: very short answer")

    meta = ex.get("meta") or {}

    if meta.get("language") not in LANGS:
        warnings.append(f"{where}: language is {meta.get('language')!r}")

    if meta.get("domain") not in DOMAINS:
        warnings.append(f"{where}: domain is {meta.get('domain')!r}")

    ids = meta.get("source_ids")

    if not isinstance(ids, list) or not ids:
        errors.append(f"{where}: meta.source_ids missing or empty")

    # Skip system prompt. Check user and assistant messages.
    for message in msgs[1:]:
        content = message["content"]

        for label in find_remaining_pii(content):
            leaks[label] += 1

            errors.append(
                f"{where}: possible {label} left in {message['role']} message"
            )


def validate(out_dir: str | Path = "output") -> dict:

    out = Path(out_dir)

    errors: list[str] = []
    warnings: list[str] = []
    leaks: Counter = Counter()

    splits = {name: _load(out / f"{name}.jsonl", errors) for name in ("train", "eval")}

    users: dict[str, set] = {}
    sources: dict[str, set] = {}

    for name, rows in splits.items():
        seen = set()

        users[name], sources[name] = set(), set()

        for n, ex in rows:
            _check_example(
                f"{name}.jsonl",
                n,
                ex,
                errors,
                warnings,
                leaks,
            )

            try:
                q = _norm(ex["messages"][1]["content"])
                users[name].add(q)

                if q in seen:
                    warnings.append(
                        f"{name}.jsonl:{n}: repeated user message within {name}"
                    )

                seen.add(q)

                sources[name].update(ex["meta"]["source_ids"])

            except (KeyError, IndexError, TypeError):
                pass

    # No overlap between train and eval:
    # by question text and by source.
    if shared := users["train"] & users["eval"]:
        errors.append(f"{len(shared)} user message(s) appear in both train and eval")

    if shared := sources["train"] & sources["eval"]:
        errors.append(f"{len(shared)} source id(s) appear in both train and eval")

    if not splits["train"] or not splits["eval"]:
        errors.append("train or eval is empty")

    return {
        "ok": not errors,
        "counts": {name: len(rows) for name, rows in splits.items()},
        "pii_leaks": dict(leaks),
        "errors": errors,
        "warnings": warnings,
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="output")

    args = ap.parse_args()

    result = validate(args.dir)

    print(f"train: {result['counts']['train']}  eval: {result['counts']['eval']}")

    for label, items in (
        ("ERRORS", result["errors"]),
        ("WARNINGS", result["warnings"]),
    ):
        if items:
            print(f"\n{label} ({len(items)})")

            for line in items[:20]:
                print(f"  {line}")

            if len(items) > 20:
                print(f"  ... and {len(items) - 20} more")

    print("\nOK" if result["ok"] else "\nFAILED")

    sys.exit(0 if result["ok"] else 1)
