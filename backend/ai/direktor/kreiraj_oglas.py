"""
Креирање оглас за работа преку AI - само за директорот.

Tek: Корисник пишува „Креирај оглас за кардиолог со рок 1 јуни"
→ AI извлекува pozicija, oddel, рок → INSERT во Vrabotuvanje.
"""

import re
from datetime import date, datetime, timedelta

from database import get_connection
from ai._kernel.ai_json import parse_ai_json
from ai._kernel.auth import require_direktor
from ai._kernel.groq_client import ask_ai
from ai._kernel.prompt_helpers import today_prompt_line
from ai._kernel.transliteracija import transliterijaj
from ai.pacient.slobodni_termini import _DEN_WD, _DEN_ALT, _den_od_match, _sleden_takov_kalendarski_den


PROMPT = """
Ти си систем што извлекува податоци за оглас за работа.

Корисникот пишува на македонски. Врати САМО JSON:
{"pozicija": "Кардиолог", "oddel": "Кардиологија", "rok": "YYYY-MM-DD"}

Правила:
- pozicija: наслов (пр. „Кардиолог", „Медицинска сестра"). Ако нема → null.
- oddel: мора од листата подолу. „кардиолог"→„Кардиологија", „гинеколог"→„Акушерство и геникологија".
- rok: краен датум за пријавување во формат YYYY-MM-DD. Ако нема → null.

ВАЖНО за rok (релативни датуми — пресметај точно од денешниот датум што ти го давам во пораката):
- „наредната среда" / „наредна среда" / „следната среда" = наредната календарска среда (не оваа ако е уште истата недела).
- „наредната недела до среда" / „до наредната среда" / „следната недела до петок" = соодветниот ден во НАРЕДНАТА календарска недела (понеделник–недела после оваа недела), не месец подоцна.
- „1 јуни", „15.05.2026" → точен датум.

БЕЗ markdown, БЕЗ објаснувања. Само JSON.
""".strip()


# „наредната недела до среда", „до наредната недела до среда"
_RE_NAR_NEDELA_DO = re.compile(
    rf"(?:до\s+)?(?:наредн\w*|следн\w*)\s+недел\w*.{{0,48}}?до\s+({_DEN_ALT})\b",
    re.IGNORECASE | re.DOTALL,
)
# „наредната среда", „до наредната среда" (еден ден, наредно појавување)
_RE_NAR_DEN = re.compile(
    rf"(?:до\s+)?(?:наредната|наредниот|нареден|наредна|следната|следниот|следен|следна)\s+({_DEN_ALT})\b",
    re.IGNORECASE,
)


def _den_naredna_nedela(denes: date, ime_den: str) -> date:
    """Дадениот ден (0=пон … 6=нед) од календарската недела веднаш по оваа."""
    twd = _DEN_WD[ime_den]
    dwd = denes.weekday()
    pocetok_nedela = denes - timedelta(days=dwd)
    pocetok_naredna = pocetok_nedela + timedelta(days=7)
    return pocetok_naredna + timedelta(days=twd)


def _rok_lokalno_od_prashanje(prashanje: str, denes: date) -> date | None:
    """
    Рок за пријава од релативни фрази на македонски (прецизнија од само-AI).
    Враќа None ако нема препознатлив шаблон.
    """
    p = transliterijaj(prashanje).lower()

    m = _RE_NAR_NEDELA_DO.search(p)
    if m:
        ime = _den_od_match(m)
        if ime:
            return _den_naredna_nedela(denes, ime)

    m2 = _RE_NAR_DEN.search(p)
    if m2:
        ime = _den_od_match(m2)
        if ime:
            return _sleden_takov_kalendarski_den(denes, ime)

    return None


def _zimi_oddeli() -> list[str]:
    """Сите имиња на оддели од базата."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT ime_na_oddel FROM Oddeli ORDER BY ime_na_oddel")
    oddeli = [str(r[0]) for r in cur.fetchall() if r[0] is not None]
    cur.close()
    conn.close()
    return oddeli


def _najdi_oddel(oddel: str, site_oddeli: list[str]) -> str | None:
    """Match (case-insensitive, или содржан)."""
    if not oddel:
        return None
    o = oddel.lower().strip()
    for x in site_oddeli:
        if x.lower() == o or o in x.lower() or x.lower() in o:
            return x
    return None


def _izvlechi(prashanje: str, denes: date) -> dict:
    """AI враќа dict со pozicija/oddel/rok."""
    oddeli = _zimi_oddeli()
    prompt = (
        f"{today_prompt_line()} ({denes.strftime('%d.%m.%Y')}).\n\n"
        f"Оддели: {', '.join(oddeli)}\n\nПрашање: „{prashanje}\"\nВрати JSON."
    )
    odgovor = ask_ai(prompt, system_prompt=PROMPT)
    print(f"[kreiraj_oglas] AI: {odgovor!r}")
    return parse_ai_json(odgovor, log_tag="kreiraj_oglas")


def odgovori_za_kreiranje_oglas(prashanje: str, lekar: dict | None) -> str:
    """Главна точка - повикана од router-от."""
    if err := require_direktor(lekar):
        return err

    denes = date.today()
    podatoci = _izvlechi(prashanje, denes)
    if podatoci.get("_error"):
        return podatoci["_error"]

    pozicija = (podatoci.get("pozicija") or "").strip()
    oddel = _najdi_oddel(podatoci.get("oddel") or "", _zimi_oddeli())
    rok_str = podatoci.get("rok")

    if not pozicija or not oddel:
        return (
            'За оглас ми треба позиција + оддел.\n'
            'Пример: „Креирај оглас за кардиолог" или „Оглас за гинеколог со рок 1 јуни"'
        )

    rok_lokal = _rok_lokalno_od_prashanje(prashanje, denes)
    rok_ai: date | None = None
    if rok_str:
        try:
            rs = str(rok_str).strip()[:10]
            rok_ai = datetime.strptime(rs, "%Y-%m-%d").date()
        except Exception:
            rok_ai = None

    if rok_lokal is not None:
        rok = rok_lokal
    elif rok_ai is not None:
        rok = rok_ai
    else:
        rok = denes + timedelta(days=30)

    if rok < denes:
        rok = denes + timedelta(days=30)

    # INSERT
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO Vrabotuvanje (pozicija, oddel, datum_na_objava, datum_na_prijavuvanje, status_oglas)"
        " VALUES (%s, %s, %s, %s, 'активен')",
        (pozicija, oddel, denes, rok),
    )
    conn.commit()
    cur.close()
    conn.close()

    return (
        f"Огласот е креиран!\n\n"
        f"Позиција: {pozicija}\n"
        f"Оддел: {oddel}\n"
        f"Рок: {rok.strftime('%d.%m.%Y')}"
    )
