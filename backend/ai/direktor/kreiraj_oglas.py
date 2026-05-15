"""
Креирање оглас за работа преку AI - само за директорот.

Корисникот може да пишува неструктурирано (залепен оглас, разговорен стил).
Системот извлекува позиција, оддел и рок (правила + AI) → INSERT во Vrabotuvanje.
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
Ти си систем што извлекува податоци за оглас за работа од СЛОБОДЕН текст.

Корисникот (директор) може да пишува неструктурирано: залепен оглас, Facebook пост,
разговор („треба сестра на гино до јуни"), со грешки во пишувањето (Гиникологија).

Врати САМО JSON:
{"pozicija": "...", "oddel": "...", "rok": "YYYY-MM-DD"}

Правила:
- pozicija: наслов на работното место (Медицинска сестра, Кардиолог, Уролог…). Не целата реченица.
- oddel: избери НАЈБЛИСК од листата „Оддели" подолу (точно име или многу блиску).
  Гинекологија/гиникологија/акаушерство → оддел што содржи гинеколог или акушерство.
- rok: краен датум за пријавување YYYY-MM-DD. „до 10 јуни 2026", „10.06.2026", „аплицирање до …".
  Игнорирај час (23:59). Ако нема датум → null.

Ако текстот е само „оглас за работа" без детали → сите null.
БЕЗ markdown. Само JSON.
""".strip()


_RE_NAR_NEDELA_DO = re.compile(
    rf"(?:до\s+)?(?:наредн\w*|следн\w*)\s+недел\w*.{{0,48}}?до\s+({_DEN_ALT})\b",
    re.IGNORECASE | re.DOTALL,
)
_RE_NAR_DEN = re.compile(
    rf"(?:до\s+)?(?:наредната|наредниот|нареден|наредна|следната|следниот|следен|следна)\s+({_DEN_ALT})\b",
    re.IGNORECASE,
)

_MESECI = {
    "јануари": 1, "февруари": 2, "март": 3, "април": 4, "мај": 5, "јуни": 6,
    "јули": 7, "август": 8, "септември": 9, "октомври": 10, "ноември": 11, "декември": 12,
    "januari": 1, "fevruari": 2, "mart": 3, "april": 4, "maj": 5, "juni": 6,
    "juli": 7, "avgust": 8, "septemvri": 9, "oktomvri": 10, "noemvri": 11, "dekemvri": 12,
}

_RE_ROK_MK = re.compile(
    r"(?:до|do|до\s+)?(\d{1,2})\s+(" + "|".join(_MESECI.keys()) + r")(?:\s+(\d{4}))?",
    re.IGNORECASE,
)
_RE_ROK_DMY = re.compile(r"(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})")


def _den_naredna_nedela(denes: date, ime_den: str) -> date:
    twd = _DEN_WD[ime_den]
    dwd = denes.weekday()
    pocetok_nedela = denes - timedelta(days=dwd)
    pocetok_naredna = pocetok_nedela + timedelta(days=7)
    return pocetok_naredna + timedelta(days=twd)


def _rok_lokalno_od_prashanje(prashanje: str, denes: date) -> date | None:
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

    m3 = _RE_ROK_MK.search(p)
    if m3:
        day = int(m3.group(1))
        mes_key = m3.group(2).lower()
        mes = _MESECI.get(mes_key)
        god = int(m3.group(3)) if m3.group(3) else denes.year
        if mes:
            try:
                return date(god, mes, day)
            except ValueError:
                pass

    m3b = re.search(
        r"(\d{1,2})\s+(" + "|".join(_MESECI.keys()) + r")\s+(\d{4})",
        p,
        re.IGNORECASE,
    )
    if m3b:
        day = int(m3b.group(1))
        mes = _MESECI.get(m3b.group(2).lower())
        if mes:
            try:
                return date(int(m3b.group(3)), mes, day)
            except ValueError:
                pass

    m4 = _RE_ROK_DMY.search(prashanje)
    if m4:
        d, mo, y = int(m4.group(1)), int(m4.group(2)), int(m4.group(3))
        try:
            return date(y, mo, d)
        except ValueError:
            pass

    return None


def _zimi_oddeli() -> list[str]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT ime_na_oddel FROM Oddeli ORDER BY ime_na_oddel")
    oddeli = [str(r[0]) for r in cur.fetchall() if r[0] is not None]
    cur.close()
    conn.close()
    return oddeli


def _najdi_oddel(oddel: str, site_oddeli: list[str]) -> str | None:
    if not oddel:
        return None
    o = oddel.lower().strip()
    for x in site_oddeli:
        if x.lower() == o or o in x.lower() or x.lower() in o:
            return x
    return None


def _oddel_od_tekst(p: str, site_oddeli: list[str]) -> str | None:
    """Најди оддел според имиња од базата или клучни зборови во текстот."""
    for ime in site_oddeli:
        il = ime.lower()
        if il in p:
            return ime
        for deo in re.split(r"[\s/\-]+", il):
            if len(deo) > 4 and deo in p:
                return ime

    if any(x in p for x in ("гинекол", "гиникол", "акауш", "геникол")):
        for ime in site_oddeli:
            il = ime.lower()
            if any(x in il for x in ("гинекол", "акауш", "геникол")):
                return ime
    if "кардиол" in p:
        for ime in site_oddeli:
            if "кардиол" in ime.lower():
                return ime
    if "хирург" in p:
        for ime in site_oddeli:
            if "хирург" in ime.lower():
                return ime
    if "урол" in p:
        for ime in site_oddeli:
            if "урол" in ime.lower():
                return ime
    if "интерн" in p:
        for ime in site_oddeli:
            if "интерн" in ime.lower():
                return ime
    return None


def _pozicija_od_tekst(p: str) -> str | None:
    if "медицинск" in p and "сестр" in p:
        return "Медицинска сестра"
    if "лаборант" in p:
        return "Лаборант"
    if "физиотерапевт" in p:
        return "Физиотерапевт"
    for spec, label in (
        ("кардиол", "Кардиолог"),
        ("хирург", "Хирург"),
        ("урол", "Уролог"),
        ("анестез", "Анестезиолог"),
        ("гинекол", "Гинеколог"),
        ("гиникол", "Гинеколог"),
        ("педијат", "Педијатар"),
        ("неврол", "Невролог"),
        ("ортопед", "Ортопед"),
        ("радиол", "Радиолог"),
        ("интерн", "Интернист"),
    ):
        if spec in p:
            return label
    m = re.search(r"\(([^)]+)\)", p)
    if m:
        inner = m.group(1).strip()
        if 3 < len(inner) < 80 and any(
            x in inner for x in ("сестр", "лекар", "медицин", "технич", "асистент")
        ):
            return inner[0].upper() + inner[1:]
    return None


def _izvlechi_pravila(prashanje: str, site_oddeli: list[str], denes: date) -> dict:
    p = transliterijaj(prashanje).lower()
    poz = _pozicija_od_tekst(p)
    odd = _oddel_od_tekst(p, site_oddeli)
    rok_dt = _rok_lokalno_od_prashanje(prashanje, denes)
    return {
        "pozicija": poz,
        "oddel": odd,
        "rok": rok_dt.strftime("%Y-%m-%d") if rok_dt else None,
    }


def _izvlechi_ai(prashanje: str, denes: date, site_oddeli: list[str]) -> dict:
    prompt = (
        f"{today_prompt_line()} ({denes.strftime('%d.%m.%Y')}).\n\n"
        f"Оддели во базата: {', '.join(site_oddeli)}\n\n"
        f"Текст од корисникот:\n{prashanje}\n\nВрати JSON."
    )
    odgovor = ask_ai(prompt, system_prompt=PROMPT)
    print(f"[kreiraj_oglas] AI: {odgovor!r}")
    return parse_ai_json(odgovor, log_tag="kreiraj_oglas")


def _spoj_izvlecheno(pravila: dict, ai: dict) -> tuple[str | None, str | None, date | None]:
    poz = (pravila.get("pozicija") or ai.get("pozicija") or "").strip() or None
    odd_raw = (pravila.get("oddel") or ai.get("oddel") or "").strip() or None
    rok: date | None = None
    if pravila.get("rok"):
        try:
            rok = datetime.strptime(str(pravila["rok"])[:10], "%Y-%m-%d").date()
        except Exception:
            rok = None
    if rok is None and ai.get("rok"):
        try:
            rok = datetime.strptime(str(ai["rok"]).strip()[:10], "%Y-%m-%d").date()
        except Exception:
            rok = None
    return poz, odd_raw, rok


def _samo_naslov_bez_detali(prashanje: str) -> bool:
    p = re.sub(r"\s+", " ", transliterijaj(prashanje).lower().strip())
    return p in (
        "оглас за работа",
        "oglas za rabota",
        "креирај оглас",
        "kreiraj oglas",
        "објави оглас",
        "нов оглас",
    )


def odgovori_za_kreiranje_oglas(prashanje: str, lekar: dict | None) -> str:
    if err := require_direktor(lekar):
        return err

    if _samo_naslov_bez_detali(prashanje):
        return (
            "Сакате да објавите оглас — во ред.\n\n"
            "Пишете слободно, како што ви е згодно, на пример:\n"
            "«Треба медицинска сестра на гинекологија, пријави се до 10 јуни»\n"
            "или залепете го целиот текст од Facebook/Word. Ќе го разберам и ќе го внесам."
        )

    denes = date.today()
    site_oddeli = _zimi_oddeli()

    pravila = _izvlechi_pravila(prashanje, site_oddeli, denes)
    ai = _izvlechi_ai(prashanje, denes, site_oddeli)
    if ai.get("_error"):
        ai = {}

    pozicija, oddel_raw, rok = _spoj_izvlecheno(pravila, ai)
    oddel = _najdi_oddel(oddel_raw or "", site_oddeli) if oddel_raw else _oddel_od_tekst(
        transliterijaj(prashanje).lower(), site_oddeli
    )

    if not pozicija or not oddel:
        delumno = []
        if pozicija:
            delumno.append(f"позиција: {pozicija}")
        if oddel:
            delumno.append(f"оддел: {oddel}")
        if rok:
            delumno.append(f"рок: {rok.strftime('%d.%m.%Y')}")
        uvod = (
            f"Го разбирам делумно ({'; '.join(delumno)})."
            if delumno
            else "Не успеав целосно да го разберам огласот."
        )
        return (
            f"{uvod}\n\n"
            "Дополнете во следната порака што недостасува (може неструктурирано), "
            "на пример: «сестра, гинекологија, до 15 јуни» или испратете го целиот текст повторно."
        )

    if rok is None:
        rok = denes + timedelta(days=30)
    if rok < denes:
        rok = denes + timedelta(days=30)

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
        f"Рок за пријава: {rok.strftime('%d.%m.%Y')}\n\n"
        "Проверете го на делот Кариера на сајтот."
    )
