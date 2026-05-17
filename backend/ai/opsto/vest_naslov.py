"""
Препознавање наслов на вест од базата (Novosti) — не мешај со пребарување лекар.

Примери:
- „Избриши ја веста со наслов Нова опрема во Клиничка Болница Штип"
- само насловот (копиран од сајт) → упатство за бришење, не „лекар не најдов"
"""

from __future__ import annotations

import re

from ai._kernel.db_helpers import db_cursor, fetch_all
from ai._kernel.transliteracija import transliterijaj

_RE_BRISI_PREFIX = re.compile(
    r"^(?:избриши|избришете|избришај|тргни|отстрани|izbrisi|izbrisete|delete)\s+"
    r"(?:ја|го|ги|ме|ja|go|gi)?\s*"
    r"(?:веста?|новоста?|вест|новост|vest|novost)?\s*"
    r"(?:со\s+)?(?:наслов(?:от)?)?\s*[:\-]?\s*",
    re.IGNORECASE | re.UNICODE,
)

_STOP_NASLOV = frozenset(
    {
        "во",
        "на",
        "за",
        "и",
        "со",
        "од",
        "до",
        "кај",
        "the",
        "a",
        "an",
    }
)

_BRISI_MARKERS = (
    "избриши",
    "избришете",
    "избришај",
    "тргни",
    "отстрани",
    "izbrisi",
    "izbrisete",
    "delete",
)


def _normaliziraj_naslov(txt: str) -> str:
    t = transliterijaj(txt or "").strip().lower()
    t = re.sub(r"[^\w\s\-]", " ", t, flags=re.UNICODE)
    return re.sub(r"\s+", " ", t).strip()


def izvleci_naslov_kandidat(prasanje: str) -> str:
    """Текст што веројатно е наслов (по тргање „избриши ја веста со наслов …")."""
    raw = (prasanje or "").strip()
    if not raw:
        return ""
    p = transliterijaj(raw)
    m = _RE_BRISI_PREFIX.match(p)
    if m:
        rest = p[m.end() :].strip()
        if rest:
            return rest.strip(" \"'„“")
    return raw.strip(" \"'„“")


def _score_naslov(kandidat: str, naslov_db: str) -> int:
    k = _normaliziraj_naslov(kandidat)
    n = _normaliziraj_naslov(naslov_db)
    if not k or not n:
        return 0
    if k == n:
        return 100
    if k in n or n in k:
        return 92
    k_words = {w for w in k.split() if w not in _STOP_NASLOV and len(w) >= 2}
    n_words = {w for w in n.split() if w not in _STOP_NASLOV and len(w) >= 2}
    if not k_words:
        return 0
    overlap = len(k_words & n_words) / len(k_words)
    if overlap >= 0.7:
        return int(75 + overlap * 25)
    return 0


def pronajdi_vest_po_naslov(prasanje: str, min_score: int = 75) -> dict | None:
    """Најблиска вест од Novosti по наслов (правила, без AI)."""
    kandidat = izvleci_naslov_kandidat(prasanje)
    if len(_normaliziraj_naslov(kandidat)) < 6:
        return None

    with db_cursor() as (_conn, cur):
        cur.execute(
            "SELECT id, naslov FROM Novosti ORDER BY created_at DESC, id DESC LIMIT 80"
        )
        rows = fetch_all(cur) or []

    best: dict | None = None
    best_score = 0
    for row in rows:
        s = _score_naslov(kandidat, str(row.get("naslov") or ""))
        if s > best_score:
            best_score = s
            best = row

    if best_score >= min_score:
        return best
    return None


def prasanje_ima_brisenje_marker(prasanje: str) -> bool:
    p = transliterijaj(prasanje).lower()
    return any(m in p for m in _BRISI_MARKERS)


def prasanje_e_izbrisi_vest_oglas(prasanje: str) -> bool:
    """Дали пораката е за бришење вест/оглас (вкл. по наслов од базата)."""
    if not prasanje_ima_brisenje_marker(prasanje):
        return False
    p = transliterijaj(prasanje).lower()
    if any(w in p for w in ("вест", "новост", "оглас", "vest", "novost", "oglas", "наслов")):
        return True
    if pronajdi_vest_po_naslov(prasanje):
        return True
    return False


def prasanje_e_samo_naslov_vest(prasanje: str) -> bool:
    """Само наслов на вест — не третирај како име на лекар."""
    p = transliterijaj(prasanje).lower()
    if prasanje_ima_brisenje_marker(prasanje):
        return False
    if re.search(r"\b(д-р|др|dr|лекар|лекари|доктор)\b", p, re.UNICODE):
        return False
    return pronajdi_vest_po_naslov(prasanje) is not None
