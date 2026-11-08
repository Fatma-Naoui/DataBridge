import re

from lingua import Language, LanguageDetectorBuilder

_detector = LanguageDetectorBuilder.from_languages(
    Language.DUTCH, Language.FRENCH, Language.ENGLISH
).build()

DOMAINS = {
    "claims": [
        "claim",
        "sinistre",
        "schade",
        "ongeval",
        "accident",
        "expert",
        "franchise",
        "vol ",
        "diefstal",
        "dégât",
    ],
    "policies": [
        "policy",
        "police",
        "polis",
        "coverage",
        "couverture",
        "dekking",
        "waarborg",
        "conditions",
        "voorwaarden",
        "contrat",
        "contract",
        "garantie",
    ],
    "billing": [
        "invoice",
        "facture",
        "factuur",
        "payment",
        "paiement",
        "betaling",
        "premium",
        "prime",
        "premie",
        "refund",
        "remboursement",
    ],
}
TABLE_HINTS = {
    "claims": "claims",
    "policies": "policies",
    "payments": "billing",
    "invoices": "billing",
}
PLACEHOLDER = re.compile(r"\[[A-Z_]+\]")


def tag_language(text: str) -> str:
    if len(text.strip()) < 20:
        return "unknown"
    lang = _detector.detect_language_of(text)
    return lang.iso_code_639_1.name.lower() if lang else "unknown"


def tag_domain(text: str, metadata: dict) -> str:
    if hint := TABLE_HINTS.get(metadata.get("table_name", "")):
        return hint
    low = PLACEHOLDER.sub(" ", text).lower()
    scores = {d: sum(low.count(k) for k in kws) for d, kws in DOMAINS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] else "general"
