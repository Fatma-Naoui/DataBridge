import re
from collections import Counter, OrderedDict
from collections.abc import Iterable

from gliner import GLiNER

# ---------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

# IBAN candidate: country code + checksum digits + account characters.
# The checksum is verified separately.
IBAN_RE = re.compile(
    r"(?<![A-Z0-9])"
    r"[A-Z]{2}\s?\d{2}(?:[\s-]?[A-Z0-9]){11,30}"
    r"(?![A-Z0-9])",
    re.IGNORECASE,
)

# Conservative phone detection:
# requires a leading + or separators between digits.
PHONE_RE = re.compile(
    r"(?<!\w)"
    r"(?:\+\d{7,15}|\+\d{1,3}[\s()./-]?(?:\d[\s()./-]?){6,14}\d"
    r"|(?:\d[\s()./-]){6,}\d)"
    r"(?!\w)"
)

CREDIT_CARD_RE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")

SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")


# ---------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------


def is_valid_iban(value: str) -> bool:
    """Validate an IBAN using the MOD-97 checksum."""

    iban = re.sub(r"\s+", "", value).upper()

    if not 15 <= len(iban) <= 34:
        return False

    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]+", iban):
        return False

    rearranged = iban[4:] + iban[:4]

    remainder = 0

    for char in rearranged:
        if char.isdigit():
            remainder = (remainder * 10 + int(char)) % 97
        else:
            number = str(ord(char) - ord("A") + 10)

            for digit in number:
                remainder = (remainder * 10 + int(digit)) % 97

    return remainder == 1


def is_valid_credit_card(value: str) -> bool:
    """Check a card-number candidate using the Luhn algorithm."""

    digits = re.sub(r"\D", "", value)

    if not 13 <= len(digits) <= 19:
        return False

    total = 0

    for index, char in enumerate(reversed(digits)):
        digit = int(char)

        if index % 2 == 1:
            digit *= 2

            if digit > 9:
                digit -= 9

        total += digit

    return total % 10 == 0


def find_remaining_pii(text: str) -> list[str]:
    """
    Return PII labels detected in text.

    IBANs and credit cards are checked separately before phone
    detection to reduce false positives.
    """

    found = []

    if EMAIL_RE.search(text):
        found.append("EMAIL")

    iban_spans = []

    for match in IBAN_RE.finditer(text):
        if is_valid_iban(match.group()):
            found.append("IBAN")
            iban_spans.append(match.span())

    card_spans = []

    for match in CREDIT_CARD_RE.finditer(text):
        if is_valid_credit_card(match.group()):
            found.append("CREDIT_CARD")
            card_spans.append(match.span())

    if SSN_RE.search(text):
        found.append("NATIONAL_ID")

    for match in PHONE_RE.finditer(text):
        start, end = match.span()

        overlaps_iban = any(
            start < iban_end and end > iban_start for iban_start, iban_end in iban_spans
        )

        overlaps_card = any(
            start < card_end and end > card_start for card_start, card_end in card_spans
        )

        if not overlaps_iban and not overlaps_card:
            found.append("PHONE")
            break

    return list(dict.fromkeys(found))


# ---------------------------------------------------------------------
# Anonymizer
# ---------------------------------------------------------------------


class Anonymizer:
    LABELS = [
        "person",
        "email",
        "phone number",
        "address",
        "organization",
        "date of birth",
        "social security number",
        "credit card number",
        "passport number",
    ]

    LABEL_MAP = {
        "person": "PERSON",
        "email": "EMAIL",
        "phone number": "PHONE",
        "address": "ADDRESS",
        "organization": "ORGANIZATION",
        "date of birth": "NATIONAL_ID",
        "social security number": "NATIONAL_ID",
        "credit card number": "CREDIT_CARD",
        "passport number": "NATIONAL_ID",
    }

    def __init__(
        self,
        threshold: float = 0.5,
        chunk_size: int = 1000,
        batch_size: int = 16,
        cache_size: int = 50_000,
        skipwords: set[str] | None = None,
        model_name: str = "urchade/gliner_multi_pii-v1",
        known_names: Iterable[str] | None = None,
    ):
        if chunk_size < 1:
            raise ValueError("chunk_size must be greater than 0")

        if batch_size < 1:
            raise ValueError("batch_size must be greater than 0")

        self.threshold = threshold
        self.chunk_size = chunk_size
        self.batch_size = batch_size
        self.cache_size = cache_size

        self.skipwords = {word.casefold() for word in (skipwords or set())}

        self.model = GLiNER.from_pretrained(model_name)

        self.cache: OrderedDict[str, list[dict]] = OrderedDict()

        self.known_names: set[str] = set()
        self.name_pattern: re.Pattern | None = None

        self.set_known_names(known_names or [])

    # -----------------------------------------------------------------
    # SQL reference names
    # -----------------------------------------------------------------

    @staticmethod
    def _normalize_name(name: str) -> str:
        return " ".join(name.split()).strip()

    def set_known_names(self, names: Iterable[str]) -> None:
        self.known_names = {
            self._normalize_name(name)
            for name in names
            if isinstance(name, str) and name.strip()
        }

        self._compile_name_pattern()

    def _compile_name_pattern(self) -> None:
        if not self.known_names:
            self.name_pattern = None
            return

        escaped_names = sorted(
            (re.escape(name) for name in self.known_names),
            key=len,
            reverse=True,
        )

        self.name_pattern = re.compile(
            r"(?<!\w)(" + "|".join(escaped_names) + r")(?!\w)",
            flags=re.IGNORECASE,
        )

    def _match_known_names(self, text: str) -> list[dict]:
        if self.name_pattern is None:
            return []

        matches = []

        for match in self.name_pattern.finditer(text):
            value = match.group(0)

            if value.casefold() in self.skipwords:
                continue

            matches.append(
                {
                    "text": value,
                    "label": "person",
                    "start": match.start(),
                    "end": match.end(),
                    "score": 1.0,
                }
            )

        return matches

    # -----------------------------------------------------------------
    # Regex detection
    # -----------------------------------------------------------------

    def _detect_regex(self, text: str) -> list[dict]:
        entities = []

        def add_matches(pattern, label, validator=None):
            for match in pattern.finditer(text):
                value = match.group()

                if validator is not None and not validator(value):
                    continue

                entities.append(
                    {
                        "text": value,
                        "label": label,
                        "start": match.start(),
                        "end": match.end(),
                        "score": 1.0,
                    }
                )

        add_matches(EMAIL_RE, "email")
        add_matches(IBAN_RE, "iban", is_valid_iban)

        # Do not let phone matching replace part of an IBAN.
        iban_spans = [
            (entity["start"], entity["end"])
            for entity in entities
            if entity["label"] == "iban"
        ]

        for match in PHONE_RE.finditer(text):
            start, end = match.span()

            if any(
                start < iban_end and end > iban_start
                for iban_start, iban_end in iban_spans
            ):
                continue

            entities.append(
                {
                    "text": match.group(),
                    "label": "phone number",
                    "start": start,
                    "end": end,
                    "score": 1.0,
                }
            )

        add_matches(
            CREDIT_CARD_RE,
            "credit card number",
            is_valid_credit_card,
        )

        add_matches(SSN_RE, "social security number")

        return entities

    # -----------------------------------------------------------------
    # Text chunking
    # -----------------------------------------------------------------

    def _split_text(self, text: str) -> list[tuple[int, str]]:
        return [
            (start, text[start : start + self.chunk_size])
            for start in range(0, len(text), self.chunk_size)
        ]

    # -----------------------------------------------------------------
    # GLiNER inference
    # -----------------------------------------------------------------

    def _detect_chunks(
        self,
        chunks: list[tuple[int, str]],
    ) -> list[dict]:

        results = []

        for i in range(0, len(chunks), self.batch_size):
            batch = chunks[i : i + self.batch_size]
            texts = [chunk for _, chunk in batch]

            predictions = self.model.inference(
                texts,
                self.LABELS,
                batch_size=self.batch_size,
                threshold=self.threshold,
            )

            for (offset, _), entities in zip(batch, predictions, strict=False):
                for entity in entities:
                    value = entity["text"]

                    if value.casefold() in self.skipwords:
                        continue

                    results.append(
                        {
                            "text": value,
                            "label": entity["label"],
                            "start": entity["start"] + offset,
                            "end": entity["end"] + offset,
                            "score": entity["score"],
                        }
                    )

        return results

    # -----------------------------------------------------------------
    # Overlap resolution
    # -----------------------------------------------------------------

    @staticmethod
    def _resolve_overlaps(entities: list[dict]) -> list[dict]:

        entities = sorted(
            entities,
            key=lambda entity: (
                entity["score"],
                entity["end"] - entity["start"],
            ),
            reverse=True,
        )

        selected = []

        for entity in entities:
            overlaps = any(
                entity["start"] < existing["end"] and entity["end"] > existing["start"]
                for existing in selected
            )

            if not overlaps:
                selected.append(entity)

        return sorted(selected, key=lambda entity: entity["start"])

    # -----------------------------------------------------------------
    # LRU cache
    # -----------------------------------------------------------------

    def _cache_get(self, text: str) -> list[dict] | None:

        if text not in self.cache:
            return None

        self.cache.move_to_end(text)

        return [entity.copy() for entity in self.cache[text]]

    def _cache_set(self, text: str, entities: list[dict]) -> None:

        if self.cache_size <= 0:
            return

        self.cache[text] = [entity.copy() for entity in entities]

        self.cache.move_to_end(text)

        while len(self.cache) > self.cache_size:
            self.cache.popitem(last=False)

    # -----------------------------------------------------------------
    # Entity detection
    # -----------------------------------------------------------------

    def _detect(self, text: str) -> list[dict]:

        cached = self._cache_get(text)

        if cached is not None:
            return cached

        entities = self._detect_chunks(self._split_text(text))

        entities.extend(self._match_known_names(text))
        entities.extend(self._detect_regex(text))

        entities = self._resolve_overlaps(entities)

        self._cache_set(text, entities)

        return entities

    # -----------------------------------------------------------------
    # Anonymization
    # -----------------------------------------------------------------

    def anonymize(self, text: str) -> tuple[str, Counter]:

        if not text:
            return text, Counter()

        entities = self._detect(text)

        counts = Counter()
        anonymized = text

        for entity in reversed(entities):
            start = entity["start"]
            end = entity["end"]

            original_label = entity["label"].casefold()

            replacement_label = self.LABEL_MAP.get(
                original_label,
                original_label.upper().replace(" ", "_"),
            )

            anonymized = (
                anonymized[:start] + f"[{replacement_label}]" + anonymized[end:]
            )

            counts[replacement_label] += 1

        return anonymized, counts

    def anonymize_many(
        self,
        texts: list[str],
    ) -> list[tuple[str, Counter]]:

        return [self.anonymize(text) for text in texts]
