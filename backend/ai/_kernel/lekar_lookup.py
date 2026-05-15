"""Пребарување лекар по име од текст на прашање (правила + опционално AI)."""

import re

from database import get_connection
from ai._kernel.transliteracija import transliterijaj

_STOP_IME = frozenset(
    {
        "кога",
        "дали",
        "има",
        "ли",
        "е",
        "се",
        "на",
        "во",
        "за",
        "од",
        "до",
        "кај",
        "со",
        "и",
        "или",
        "дежурна",
        "дежурен",
        "дежурство",
        "дежурства",
        "дежурни",
        "наредниот",
        "наредна",
        "нареден",
        "следниот",
        "следна",
        "идни",
        "перод",
        "период",
        "закажани",
        "системот",
        "кои",
        "колку",
        "доколку",
        "работи",
        "koga",
        "dali",
        "ima",
        "dezurna",
        "dezurstvo",
        "period",
        "naredniot",
    }
)

# Unicode букви (кирилица + латиница) за имиња
_RE_ZBOR = re.compile(r"[\w\-]+", re.UNICODE)
_RE_POSLE_DR = re.compile(
    r"(?:д-р|др|dr|d-r)\.?\s+(.+)",
    re.IGNORECASE | re.UNICODE,
)


def _cist_ime_zbor(raw: str) -> str:
    """Тргни интерпункција („период?" → „период")."""
    return re.sub(r"[^\w\-]", "", raw, flags=re.UNICODE).lower()


def izvlechi_delovi_ime(prashanje: str) -> list[str]:
    p = transliterijaj(prashanje).lower()

    # Најсигурно: текст веднаш после д-р / др
    delovi: list[str] = []
    m = _RE_POSLE_DR.search(p)
    if m:
        for raw in _RE_ZBOR.findall(m.group(1)):
            w = _cist_ime_zbor(raw)
            if len(w) < 2:
                continue
            if w in _STOP_IME:
                break
            delovi.append(w)
            if len(delovi) >= 3:
                break

    if len(delovi) >= 2:
        return delovi

    # Резервно: сите зборови без титула
    p = re.sub(r"\b(д-р|др|dr|d-r)\b", " ", p, flags=re.IGNORECASE | re.UNICODE)
    for raw in _RE_ZBOR.findall(p):
        w = _cist_ime_zbor(raw)
        if len(w) >= 2 and w not in _STOP_IME:
            delovi.append(w)
        if len(delovi) >= 3:
            break

    return delovi[:3] if delovi else []


def _lekar_od_red(row: dict | None) -> dict | None:
    if not row:
        return None
    return {
        "doctor_ID": row["doctor_ID"],
        "name": row["name"],
        "surname": row["surname"],
        "specialty": row.get("specialty"),
    }


def najdi_lekar_od_delovi(delovi: list[str]) -> dict | None:
    """SQL: Марија Хубрева, Гордана Камчева Михаилова, …"""
    if len(delovi) < 2:
        return None

    ime = delovi[0]
    prezime = delovi[-1]
    sredina = " ".join(delovi[1:-1]) if len(delovi) > 2 else ""

    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """
            SELECT doctor_ID, name, surname, specialty
            FROM Doctors
            WHERE LOWER(name) LIKE %s AND LOWER(surname) LIKE %s
            """,
            (f"%{ime}%", f"%{prezime}%"),
        )
        row = cur.fetchone()
        if row:
            return _lekar_od_red(row)

        if sredina:
            full_prezime = f"{sredina} {prezime}".strip()
            cur.execute(
                """
                SELECT doctor_ID, name, surname, specialty
                FROM Doctors
                WHERE LOWER(name) LIKE %s AND LOWER(surname) LIKE %s
                """,
                (f"%{ime}%", f"%{full_prezime}%"),
            )
            row = cur.fetchone()
            if row:
                return _lekar_od_red(row)

        pref = prezime[:4] if len(prezime) >= 4 else prezime
        cur.execute(
            """
            SELECT doctor_ID, name, surname, specialty
            FROM Doctors
            WHERE LOWER(name) LIKE %s AND LOWER(surname) LIKE %s
            """,
            (f"%{ime}%", f"{pref}%"),
        )
        rows = cur.fetchall()
        if len(rows) == 1:
            return _lekar_od_red(rows[0])

        # Само презиме + филтер по име
        cur.execute(
            """
            SELECT doctor_ID, name, surname, specialty
            FROM Doctors
            WHERE LOWER(surname) LIKE %s
            """,
            (f"%{prezime}%",),
        )
        rows = cur.fetchall()
        matches = [r for r in rows if ime in (r.get("name") or "").lower()]
        if len(matches) == 1:
            return _lekar_od_red(matches[0])
    finally:
        cur.close()
        conn.close()
    return None


def delovite_odgovaraat_na_lekar(lekar: dict | None, delovi: list[str]) -> bool:
    if not lekar or not delovi:
        return False
    blob = f"{lekar.get('name', '')} {lekar.get('surname', '')}".lower()
    if delovi[0] not in blob:
        return False
    if len(delovi) < 2:
        return True
    prezime = delovi[-1]
    if prezime in blob:
        return True
    if len(prezime) >= 4 and prezime[:4] in blob:
        return True
    return False


def najdi_lekar_od_prashanje(
    prashanje: str,
    *,
    koristi_ai: bool = True,
) -> dict | None:
    delovi = izvlechi_delovi_ime(prashanje)
    if len(delovi) >= 2:
        found = najdi_lekar_od_delovi(delovi)
        if found:
            return found

    if not koristi_ai:
        return None

    from ai.pacient.slobodni_termini import najdi_lekar_so_ai

    lekar = najdi_lekar_so_ai(prashanje)
    if not lekar:
        return None
    if len(delovi) >= 2 and not delovite_odgovaraat_na_lekar(lekar, delovi):
        return najdi_lekar_od_delovi(delovi)
    return lekar
