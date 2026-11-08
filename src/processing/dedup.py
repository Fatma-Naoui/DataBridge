import hashlib
import re

from datasketch import MinHash, MinHashLSH

from src.models import Record


def _norm(t: str) -> str:
    return re.sub(r"\W+", " ", t.lower()).strip()


def _minhash(t: str, k: int = 5) -> MinHash:
    w = _norm(t).split()
    m = MinHash(num_perm=128)
    for i in range(max(1, len(w) - k + 1)):
        m.update(" ".join(w[i : i + k]).encode())
    return m


def dedupe(records: list[Record], threshold: float = 0.85):
    """Exact (hash) then near-duplicate (MinHash LSH). Input should be sorted
    newest first so the most recent version of a document is the one kept."""
    kept, dropped, seen = [], [], {}
    lsh = MinHashLSH(threshold=threshold, num_perm=128)
    for r in records:
        key = hashlib.sha1(_norm(r.body).encode()).hexdigest()
        if key in seen:
            dropped.append((r, "exact_duplicate", seen[key]))
            continue
        m = _minhash(r.body)
        if hits := lsh.query(m):
            dropped.append((r, "near_duplicate", hits[0]))
            continue
        seen[key] = r.id
        lsh.insert(r.id, m)
        kept.append(r)
    return kept, dropped
