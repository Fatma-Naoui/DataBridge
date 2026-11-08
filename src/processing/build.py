import hashlib
from collections import defaultdict

from src.models import Record


def pair_threads(records: list[Record]):
    """Pair customer + agent messages of the same email thread into qa records."""
    out, threads = [], defaultdict(list)
    for r in records:
        (threads[r.metadata["thread"]] if r.kind == "message" else out).append(r)
    unpaired = 0
    for key, msgs in threads.items():
        c = next((m for m in msgs if m.metadata["role"] == "customer"), None)
        a = next((m for m in msgs if m.metadata["role"] == "agent"), None)
        if not (c and a):
            unpaired += 1
            continue
        out.append(
            Record(
                id=f"{c.id}+{a.id}",
                source_type=c.source_type,
                kind="qa",
                question=c.text,
                answer=a.text,
                language=c.language,
                domain=c.domain,
                metadata={"group": key, "source_ids": [c.id, a.id]},
            )
        )
    return out, unpaired


def build_examples(records: list[Record], system_prompt: str) -> list[dict]:
    examples = []
    for r in records:
        if r.kind != "qa" or not (r.question.strip() and r.answer.strip()):
            continue
        examples.append(
            {
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": r.question.strip()},
                    {"role": "assistant", "content": r.answer.strip()},
                ],
                "meta": {
                    "domain": r.domain,
                    "language": r.language,
                    "source_ids": r.metadata.get("source_ids", [r.id]),
                },
                "_group": r.metadata.get("group", r.id),
            }
        )
    return examples


def split(examples: list[dict], eval_pct: int = 15, seed: int = 42):
    """Group-aware, domain-stratified, deterministic split.
    Examples from the same document or thread always land in the same file."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for ex in examples:
        groups[ex.pop("_group")].append(ex)

    by_domain: dict[str, list[str]] = defaultdict(list)
    for g, exs in groups.items():
        by_domain[exs[0]["meta"]["domain"]].append(g)

    eval_groups: set[str] = set()
    for gs in by_domain.values():
        gs.sort(key=lambda g: hashlib.sha1(f"{seed}:{g}".encode()).hexdigest())
        n = round(len(gs) * eval_pct / 100)
        if len(gs) >= 2:
            n = max(n, 1)
        eval_groups.update(gs[:n])

    train, ev = [], []
    for g, exs in groups.items():
        (ev if g in eval_groups else train).extend(exs)
    return train, ev
