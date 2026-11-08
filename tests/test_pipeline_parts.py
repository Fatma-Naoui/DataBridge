from src.models import RawDocument, Record
from src.processing.build import split
from src.processing.clean import clean
from src.processing.dedup import dedupe
from src.processing.parse import ParseError, parse


def test_clean_strips_signature_and_disclaimer():
    text = (
        "Bonjour, je voudrais déclarer un sinistre.\n\n"
        "Cordialement,\nJean\n\n"
        "Ce message est confidentiel et destiné au seul destinataire."
    )
    out = clean(text)
    assert "sinistre" in out
    assert "Cordialement" not in out and "confidentiel" not in out


def test_clean_fixes_broken_encoding():
    assert "é" in clean("dÃ©claration")


def test_dedupe_exact_and_near():
    base = (
        "Pour déclarer un sinistre auto vous devez remplir le constat amiable "
        "et nous le renvoyer sous cinq jours ouvrables"
    )
    recs = [
        Record(id="a", source_type="files", kind="doc", text=base),
        Record(id="b", source_type="files", kind="doc", text=base),  # exact
        Record(id="c", source_type="files", kind="doc", text=base + " merci"),  # near
        Record(
            id="d",
            source_type="files",
            kind="doc",
            text="Tout autre sujet sans rapport avec le reste du corpus ici présent",
        ),
    ]
    kept, dropped = dedupe(recs)
    assert [r.id for r in kept] == ["a", "d"]
    assert {reason for _, reason, _ in dropped} == {"exact_duplicate", "near_duplicate"}


def test_split_has_no_overlap_and_keeps_groups_together():
    examples = [
        {"messages": [], "meta": {"domain": d, "source_ids": [f"{g}"]}, "_group": g}
        for d in ("claims", "billing")
        for g in [f"{d}-{i}" for i in range(10)]
        for _ in range(2)  # two examples per group
    ]
    train, ev = split(examples, eval_pct=20)
    assert train and ev
    train_src = {s for e in train for s in e["meta"]["source_ids"]}
    eval_src = {s for e in ev for s in e["meta"]["source_ids"]}
    assert not train_src & eval_src
    assert {e["meta"]["domain"] for e in ev} == {"claims", "billing"}


def test_bad_pdf_is_reported_not_crashing():
    raw = RawDocument(
        id="x.pdf",
        source_type="files",
        source_uri="x",
        content=b"not a pdf",
        mime_type="application/pdf",
    )
    try:
        parse(raw, {})
        raise AssertionError("should have raised")
    except ParseError as e:
        assert str(e).startswith("pdf_unreadable")


def test_unknown_mime_is_dropped_with_reason():
    raw = RawDocument(
        id="x", source_type="files", source_uri="x", content=b"", mime_type="image/png"
    )
    try:
        parse(raw, {})
        raise AssertionError()
    except ParseError as e:
        assert "unsupported_mime" in str(e)
