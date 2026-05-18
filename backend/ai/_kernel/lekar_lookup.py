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
        "кој",
        "која",
        "кои",
        "koja",
        "што",
        "си",
        "ти",
        "те",
        "мене",
        "вие",
        "нас",
        "вас",
        "koj",
        "koi",
        "sto",
        "si",
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
        "слободен",
        "слободна",
        "слободни",
        "слободно",
        "термин",
        "термини",
        "sloboden",
        "slobodna",
        "termin",
        "преглед",
        "прегледи",
        "прегледите",
        "pregled",
        "pregledi",
        "термин",
        "термини",
        "termin",
        "termini",
        "site",
        "сите",
        "prikazi",
        "прикажи",
        "pokazi",
        "покажи",
        "januar",
        "februar",
        "mart",
        "april",
        "maj",
        "juni",
        "juli",
        "avgust",
        "septemvri",
        "oktomvri",
        "noemvri",
        "decemvri",
        "јануари",
        "февруари",
        "март",
        "април",
        "мај",
        "јуни",
        "јули",
        "август",
        "септември",
        "октомври",
        "ноември",
        "декември",
        "дијагноза",
        "dijagnoza",
        "терапија",
        "terapija",
        "мигрена",
        "migrena",
        "хипертензија",
        "hipertenzija",
        "аналгетик",
        "analgetik",
        "затвори",
        "zatvori",
        "ponedelnik",
        "vtornik",
        "sreda",
        "chetvrtok",
        "petok",
        "sabota",
        "nedela",
        "понеделник",
        "вторник",
        "среда",
        "четврток",
        "петок",
        "сабота",
        "недела",
        "работно",
        "работното",
        "време",
        "болница",
        "болницата",
        "кое",
        "ко",
        "каде",
        "наоѓа",
        "наоѓаат",
        "локација",
        "локацијата",
        "кардиологија",
        "кардиологијата",
        "гинекологија",
        "неврологија",
        "ортопедија",
        "лабораторија",
        "радиологија",
        "хирургија",
        "педиатрија",
        "онкологија",
        "одделот",
        "оддел",
        "оделот",
        "одел",
        "лекари",
        "лекарите",
        "доктори",
        "докторите",
        "каков",
        "каква",
        "телефон",
        "телефонот",
        "контакт",
        "контактот",
        "контакти",
        "дали",
        "може",
        "можете",
        "да",
        "провериш",
        "проверите",
        "провери",
        "проверете",
        "проверес",
        "проверка",
        "proveres",
        "proveri",
        "proverete",
        "mozete",
        "mozesh",
        "dali",
        "moze",
        "da",
        "slobodno",
        "slobodna",
        "slobodni",
        "утре",
        "utre",
        "денес",
        "denes",
        "вчера",
        "vchera",
        "задутре",
        "zautre",
        "задутра",
        "наредниот",
        "наредна",
        "нареден",
        "следниот",
        "следна",
        "следен",
        "идни",
        "утрешниот",
        "утрешна",
        "утрешно",
        "utreshniot",
        "utreshna",
        "избришеш",
        "избришам",
        "избриша",
        "бришеш",
        "бришам",
        "бриши",
        "истата",
        "иста",
        "сега",
    }
)

_RE_PREZIME_POCETOK = re.compile(
    r"^([a-zа-яёїієґ\-]{2,})\s+"
    r"(?:кога|дали|има|е\s+слобод|слободен|слободна|слободни|"
    r"koga|dali|ima|e\s+slobod|sloboden|slobodna|slobodni)",
    re.UNICODE | re.IGNORECASE,
)

# Unicode букви (кирилица + латиница) за имиња
_RE_ZBOR = re.compile(r"[\w\-]+", re.UNICODE)
_RE_POSLE_DR = re.compile(
    r"(?:д-р|др|dr|d-r)\.?\s+(.+)",
    re.IGNORECASE | re.UNICODE,
)
_RE_POSLE_KAJ = re.compile(
    r"\bкај\s+(.+)",
    re.IGNORECASE | re.UNICODE,
)


def _cist_ime_zbor(raw: str) -> str:
    """Тргни интерпункција („период?" → „период")."""
    return re.sub(r"[^\w\-]", "", raw, flags=re.UNICODE).lower()


def _delovi_od_fragment(fragment: str) -> list[str]:
    """Име/презиме од дел од прашањето (по „д-р“ или „кај“)."""
    delovi: list[str] = []
    frag = re.split(r"[?.!,;]", fragment, maxsplit=1)[0]
    for raw in _RE_ZBOR.findall(frag):
        w = _cist_ime_zbor(raw)
        if len(w) < 2:
            continue
        if w in _STOP_IME:
            break
        delovi.append(w)
        if len(delovi) >= 3:
            break
    return delovi[:3]


def prezime_na_pocetok_od_prasanje(prasanje: str) -> str | None:
    """
    „Здравев кога е слободен утре" → „здравев" (презиме на почеток, пред прашање).
    """
    p = transliterijaj(prasanje or "").strip().lower()
    m = _RE_PREZIME_POCETOK.match(p)
    if not m:
        return None
    token = _cist_ime_zbor(m.group(1))
    if len(token) < 3 or token in _STOP_IME:
        return None
    return token


def prasanje_ukazuva_kon_konkreten_lekar(prasanje: str) -> bool:
    """Дали прашањето наведува конкретен лекар (не „кој од нив" / цел оддел)."""
    if not (prasanje or "").strip():
        return False
    if prezime_na_pocetok_od_prasanje(prasanje):
        return True
    p = transliterijaj(prasanje).lower()
    if _RE_POSLE_DR.search(p) or _RE_POSLE_KAJ.search(p):
        return True
    delovi = izvlechi_delovi_ime(prasanje)
    if not delovi:
        return False
    if len(delovi) == 1:
        return len(najdi_lekari_po_prezime(delovi[0])) > 0
    return najdi_lekar_od_delovi(delovi) is not None


def izvlechi_delovi_ime(prasanje: str) -> list[str]:
    p = transliterijaj(prasanje).lower()

    poc = prezime_na_pocetok_od_prasanje(prasanje)
    if poc:
        return [poc]

    # Најсигурно: текст веднаш после д-р / др (не мешај со „слободен понеделник“)
    m = _RE_POSLE_DR.search(p)
    if m:
        delovi = _delovi_od_fragment(m.group(1))
        if delovi:
            return delovi

    # „кај Моника Иванова“, „сlobodno kaj Петров“
    m_kaj = _RE_POSLE_KAJ.search(p)
    if m_kaj:
        delovi = _delovi_od_fragment(m_kaj.group(1))
        if delovi:
            return delovi

    # Резервно: зборови од целото прашање (без шумни зборови)
    delovi = []
    p = re.sub(r"\b(д-р|др|dr|d-r)\b", " ", p, flags=re.IGNORECASE | re.UNICODE)
    for raw in _RE_ZBOR.findall(p):
        w = _cist_ime_zbor(raw)
        if len(w) >= 2 and w not in _STOP_IME:
            delovi.append(w)
        if len(delovi) >= 3:
            break

    return delovi[:3] if delovi else []


def _ocenka_prezime_sovpad(prezime: str, surname: str) -> int:
    """
    Поголема оценка = поблиску до она што корисникот најчесто мисли.
    „Петров“ → Петровски (90), не Петровска (55) — освен ако самото бара „…ска“.
    """
    p = (prezime or "").strip().lower()
    s = (surname or "").strip().lower()
    if not p or not s:
        return 0
    if s == p:
        return 100
    if not s.startswith(p):
        return 0

    suf = s[len(p) :]
    bara_ska = p.endswith("ска") or p.endswith("ska")
    bara_ski = p.endswith("ски") or p.endswith("ski")

    if s == p + "ски" or s == p + "ski":
        return 95
    if s == p + "ска" or s == p + "ska":
        return 95 if bara_ska else 58

    if suf in ("ски", "ski"):
        return 92 if not bara_ska else 75
    if suf in ("ска", "ska"):
        return 92 if bara_ska else 55
    if len(suf) <= 1:
        return 88
    return 72


def _izberi_eden_od_rangiran(prezime: str, rows: list[dict]) -> list[dict]:
    """Ако еден кандидат е јасно поблиску, врати само него."""
    if len(rows) <= 1:
        return rows

    scored: list[tuple[int, dict]] = []
    for r in rows:
        oc = _ocenka_prezime_sovpad(prezime, r.get("surname") or "")
        if oc > 0:
            scored.append((oc, r))

    if not scored:
        return rows

    scored.sort(key=lambda x: (-x[0], (x[1].get("surname") or ""), x[1].get("name") or ""))
    najdobar, drugi = scored[0][0], scored[1][0] if len(scored) > 1 else 0

    # Еден јасен победник (на пр. „петров“ → само Петровски)
    if najdobar >= 85 and (len(scored) == 1 or najdobar - drugi >= 28):
        return [scored[0][1]]

    # Сите со иста највисока оценка — вистинска нејасност (два Петровски)
    top = [r for o, r in scored if o == najdobar]
    if len(top) == 1:
        return top
    return top


def najdi_lekari_po_prezime(prezime: str) -> list[dict]:
    """Сите лекари чие презиме одговара (точно или по почеток)."""
    prezime = (prezime or "").strip().lower()
    if len(prezime) < 2:
        return []

    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """
            SELECT doctor_ID, name, surname, specialty, email
            FROM Doctors
            WHERE LOWER(surname) LIKE %s
            ORDER BY surname, name
            """,
            (f"{prezime}%",),
        )
        rows = cur.fetchall()
    finally:
        cur.close()
        conn.close()

    if not rows:
        return []

    exact = [r for r in rows if (r.get("surname") or "").lower() == prezime]
    if exact:
        return _lekari_od_rows(exact)

    if len(rows) == 1:
        one = _lekar_od_red(rows[0])
        return [one] if one else []

    rows = _izberi_eden_od_rangiran(prezime, rows)
    if len(rows) == 1:
        one = _lekar_od_red(rows[0])
        return [one] if one else []

    return _lekari_od_rows(rows)


def _lekari_od_rows(rows: list[dict]) -> list[dict]:
    out: list[dict] = []
    for r in rows:
        lekar = _lekar_od_red(r)
        if lekar:
            out.append(lekar)
    return out


def najdi_lekari_po_delovi(delovi: list[str]) -> list[dict]:
    """0, 1 или повеќе лекари — без AI."""
    delovi = [d for d in delovi if d and d not in _STOP_IME]
    if len(delovi) >= 2:
        lekar = najdi_lekar_od_delovi(delovi)
        return [lekar] if lekar else []
    if len(delovi) == 1:
        return najdi_lekari_po_prezime(delovi[0])
    return []


def poraka_za_vise_lekari(lekari: list[dict], delovi: list[str] | None = None) -> str:
    linii = [
        f"• Д-р {l['name']} {l['surname']} — {l.get('specialty') or 'Општа пракса'}"
        for l in lekari
    ]
    hint = ""
    if delovi and len(delovi) == 1:
        hint = (
            f"\n\nНаведете го и името (на пр. „д-р Стефан {delovi[0].title()}“) "
            "или целосно име и презиме."
        )
    return (
        "Има повеќе лекари со слично презиме во евиденцијата:\n"
        + "\n".join(linii)
        + hint
    )


def _lekar_od_red(row: dict | None) -> dict | None:
    if not row:
        return None
    return {
        "doctor_ID": row["doctor_ID"],
        "name": row["name"],
        "surname": row["surname"],
        "specialty": row.get("specialty"),
        "email": (row.get("email") or "").strip(),
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
            SELECT doctor_ID, name, surname, specialty, email
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
                SELECT doctor_ID, name, surname, specialty, email
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
            SELECT doctor_ID, name, surname, specialty, email
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
            SELECT doctor_ID, name, surname, specialty, email
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
    if len(delovi) == 1:
        token = delovi[0]
        sur = (lekar.get("surname") or "").lower()
        ime = (lekar.get("name") or "").lower()
        return (
            token == sur
            or token == ime
            or sur.startswith(token)
            or token in sur
            or token in blob
        )
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


def najdi_lekar_od_prasanje(
    prasanje: str,
    *,
    koristi_ai: bool = True,
) -> dict | None:
    delovi = izvlechi_delovi_ime(prasanje)
    kandidati = najdi_lekari_po_delovi(delovi)
    if len(kandidati) == 1:
        return kandidati[0]
    if len(kandidati) > 1:
        return None

    if not koristi_ai:
        return None

    from ai.pacient.slobodni_termini import najdi_lekar_so_ai

    lekar = najdi_lekar_so_ai(prasanje)
    if not lekar:
        return None
    if delovi and not delovite_odgovaraat_na_lekar(lekar, delovi):
        povtorno = najdi_lekari_po_delovi(delovi)
        if len(povtorno) == 1:
            return povtorno[0]
        return None
    return lekar
