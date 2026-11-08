import json
from pathlib import Path


def _table(headers: list[str], rows: list[list]) -> str:
    if not rows:
        return "_none_\n"
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines) + "\n"


def _distribution(counts: dict, headers: list[str]) -> str:
    total = sum(counts.values()) or 1
    rows = [
        [k, v, f"{100 * v / total:.0f}%"]
        for k, v in sorted(counts.items(), key=lambda x: -x[1])
    ]
    return _table(headers, rows)


def to_markdown(s: dict) -> str:
    md = ["# Quality report\n"]

    md.append("## Records ingested per source\n")
    md.append(_table(["source", "records"], list(s["ingested_per_source"].items())))
    if s["failed_sources"]:
        md.append(f"Sources that could not connect: {', '.join(s['failed_sources'])}\n")

    md.append("\n## Dropped and why\n")
    rows = [
        [src, reason, n]
        for src, reasons in s["dropped"].items()
        for reason, n in sorted(reasons.items(), key=lambda x: -x[1])
    ]
    md.append(_table(["source", "reason", "count"], rows))

    md.append("\n## Duplicates removed\n")
    d = s["duplicates_removed"]
    md.append(_table(["type", "count"], [["exact", d["exact"]], ["near", d["near"]]]))

    md.append("\n## PII replaced\n")
    md.append(_table(["type", "count"], sorted(s["pii_replaced"].items())))

    md.append("\n## Language distribution\n")
    md.append(
        _distribution(s["language_distribution"], ["language", "examples", "share"])
    )

    md.append("\n## Domain distribution\n")
    md.append(_distribution(s["domain_distribution"], ["domain", "examples", "share"]))
    md.append("\n## Train / eval split\n")
    sp = s["split"]
    total = (sp["train"] + sp["eval"]) or 1
    md.append(
        _table(
            ["file", "examples", "share"],
            [[k, v, f"{100 * v / total:.0f}%"] for k, v in sp.items()],
        )
    )

    v = s.get("validation")
    if v:
        md.append(f"\n## Validation: {'passed' if v['ok'] else 'FAILED'}\n")
        md.append(f"{len(v['errors'])} error(s), {len(v['warnings'])} warning(s).\n")
        for e in v["errors"][:10]:
            md.append(f"- {e}")

    return "\n".join(md) + "\n"


def generate_report(stats: dict, out_dir: str | Path) -> dict:
    out = Path(out_dir)
    (out / "quality_report.json").write_text(
        json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (out / "quality_report.md").write_text(to_markdown(stats), encoding="utf-8")
    return stats
