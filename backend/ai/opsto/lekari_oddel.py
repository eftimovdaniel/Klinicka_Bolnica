"""
Лекари по оддел / специјалност, или цел лекарски тим во болницата.

Примери:
- „Кои лекари се на одделот за Урологија?"
- „Кои се лекарите од Кардиологија?"
- „Кои лекари работат во болницата?" → сите лекари од база + навигација #lekari

Логика:
1. Ако прашањето е за цела установа/болница (без оддел) → листа од Doctors + скрол кон #lekari.
2. Инаку: AI извлекува оддел; fuzzy-match со Oddeli/Doctors.specialty; листа по оддел.
"""

import json
import re
from typing import Any

from database import get_connection
from ai._kernel.groq_client import ask_ai
from ai._kernel.transliteracija import transliterijaj


PROMPT = """
Ти си систем што од прашање извлекува име на медицински оддел / специјалност.

Корисникот пишува на македонски (понекогаш на латиница). Тој прашува кои лекари
се на одреден оддел (напр. „кои лекари се на Урологија", „кои се од Кардиологија").

Врати САМО JSON:
{"oddel": "<име на одделот без префикс>" | null}

Правила:
- Извлечи само самото име, БЕЗ зборови како „оддел", „специјалност", „за".
  „Кои лекари се на одделот за Урологија" → {"oddel": "Урологија"}
- Ако корисникот пишува на латиница, врати го името во кирилица:
  „kardiologija" → „Кардиологија", „hirurgija" → „Хирургија".
- Прифатени специјалности (само како насока, нема комплетна листа):
  Кардиологија, Урологија, Хирургија, Гинекологија, Педијатрија,
  Неврологија, Ортопедија, Психијатрија, Радиологија, Анестезиологија,
  Интерна медицина, Општа медицина, ОРЛ, Дерматологија, Офталмологија.
- ВАЖНО: „хирургија", „општа хирургија", „генерална хирургија" → „Хирургија", НЕ „Неврохирургија".
  Само ако експлицитно пишува „неврохирургија" / „neurohirurgija" → „Неврохирургија".
- Ако прашањето е за СИТЕ лекари во болницата/установата/кај вас (без конкретен оддел) → {"oddel": null}
  (на пр. „кои лекари работат во болницата?", „кој доктори имате?").
- ако одделот не е јасен → null

БЕЗ markdown, БЕЗ објаснувања. Само JSON.
""".strip()


def _izvlechi(prashanje: str) -> str | None:
    odgovor = ask_ai(f"Прашање: „{prashanje}\"", system_prompt=PROMPT)
    print(f"[lekari_oddel] AI: {odgovor!r}")

    if "Привремено сум" in odgovor or "Привремена грешка" in odgovor:
        return "_error"

    cist = re.sub(r"^```(?:json)?|```$", "", odgovor.strip()).strip()
    try:
        data = json.loads(cist)
    except Exception:
        return None
    val = data.get("oddel")
    if not val:
        return None
    return str(val).strip()


def _site_lekari_vo_ustanova(prashanje: str) -> bool:
    """
    Прашање за целиот лекарски тим (без конкретен оддел), на пр. „кои лекари работат во болницата?".
    """
    p = transliterijaj(prashanje).lower()
    if not any(w in p for w in ("лекар", "доктор", "специјалист")):
        return False
    if re.search(r"на\s+оддел", p) or re.search(r"од\s+оддел", p) or re.search(r"оддел(?:от|о)?\s+за", p):
        return False
    if re.search(r"во\s+болниц", p):
        return True
    if re.search(r"во\s+установ", p) or "установа" in p or "установата" in p:
        return True
    if re.search(r"во\s+клиник", p) or "клиниката" in p:
        return True
    if "кај вас" in p:
        return True
    if any(
        s in p
        for s in (
            "сите лекари",
            "сите доктори",
            "листа на лекари",
            "листа на доктори",
            "медицински тим",
            "тимот на лекари",
        )
    ):
        return True
    return False


def _odgovor_site_lekari_so_navigacija() -> dict[str, Any]:
    """Листа на сите лекари + навигација кон секцијата „Лекари" на сајтот."""
    from ai.pacient.slobodni_termini import zimi_site_lekari

    lekari = zimi_site_lekari()
    if not lekari:
        return {
            "odgovor": "Моментално нема регистрирани лекари во системот.",
            "navigacija": {"target": "index.html#lekari", "label": "Лекари"},
        }

    redovi = [
        "Лекари во Клиничка Болница Штип:",
        "",
    ]
    for l in lekari:
        spec = (l.get("specialty") or "—").strip() or "—"
        polno = f"Д-р {l['name']} {l['surname']}"
        em = (l.get("email") or "").strip()
        if em:
            redovi.append(f"- {polno} — {spec} ({em})")
        else:
            redovi.append(f"- {polno} — {spec}")
    redovi.append("")
    redovi.append(
        "Секцијата „Лекари" на почетната страница се отвора автоматски за целосен преглед и филтрирање."
    )
    return {
        "odgovor": "\n".join(redovi),
        "navigacija": {"target": "index.html#lekari", "label": "Лекари"},
    }


def _normaliziraj(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"\s+", " ", s)
    return s


def _najdi_oddel(baran_oddel: str) -> tuple[str, list[str]] | None:
    """
    Прави fuzzy-match. Враќа (име од база за query, [сите варијанти]) или None.

    Стратегија:
    - Точна (case-insensitive) еднаквост во Doctors.specialty или Oddeli.ime_na_oddel
    - Ако бараното е потниза на повеќе имиња (пр. „хирургија" во „Неврохирургија" и „Хирургија"),
      се бира најкраткото име — така „Хирургија" победува над „Неврохирургија".
    - Инаку: DB име како потниза во побараното → најдолго совпаѓање (поспецифично).
    """
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT DISTINCT TRIM(specialty) AS oddel FROM Doctors
            WHERE specialty IS NOT NULL AND TRIM(specialty) <> ''
        """)
        speci = [r["oddel"] for r in cur.fetchall() if r["oddel"]]
        cur.execute("SELECT ime_na_oddel AS oddel FROM Oddeli WHERE ime_na_oddel IS NOT NULL")
        oddeli = [r["oddel"] for r in cur.fetchall() if r["oddel"]]
        cur.close()
    except Exception as e:
        print(f"[lekari_oddel] fetch oddeli greshka: {e}")
        return None
    finally:
        if conn:
            conn.close()

    site = sorted({*speci, *oddeli}, key=lambda x: (len(x), x))
    if not site:
        return None

    barano_n = _normaliziraj(baran_oddel)

    for kandidat in site:
        if _normaliziraj(kandidat) == barano_n:
            return kandidat, site

    # бараното е потниза во името од база (пр. „хирургија" во „Неврохирургија"):
    # најкратко совпаѓање за да не се меша општа хирургија со неврохирургија.
    vnatre = [
        k
        for k in site
        if barano_n and barano_n in _normaliziraj(k) and _normaliziraj(k) != barano_n
    ]
    if vnatre:
        best = min(vnatre, key=len)
        return best, site

    # името од база е потниза во побараното (подолго извлечување од AI)
    nadvor = [
        k
        for k in site
        if _normaliziraj(k) and _normaliziraj(k) in barano_n and _normaliziraj(k) != barano_n
    ]
    if nadvor:
        best = max(nadvor, key=len)
        return best, site

    return None


def _zimi_lekari_od_oddel(oddel: str) -> list[dict]:
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT doctor_ID, name, surname, specialty, email
            FROM Doctors
            WHERE LOWER(TRIM(specialty)) = LOWER(TRIM(%s))
            ORDER BY surname, name
        """, (oddel,))
        rez = cur.fetchall()
        cur.close()
        return rez
    except Exception as e:
        print(f"[lekari_oddel] lekari greshka: {e}")
        return []
    finally:
        if conn:
            conn.close()


def odgovori_za_lekari_oddel(prashanje: str) -> str | dict[str, Any]:
    if _site_lekari_vo_ustanova(prashanje):
        return _odgovor_site_lekari_so_navigacija()

    baran = _izvlechi(prashanje)
    if baran == "_error":
        return (
            "Привремено сум зафатен. Те молам обиди се повторно за неколку секунди."
        )
    if not baran:
        return (
            'Ако прашувате за конкретен оддел, наведете го (на пр.: „Кои лекари се на Кардиологија?"). '
            "За целиот лекарски тим прашајте на пример: „Кои лекари работат во болницата?" "
            'или „Сите лекари кај вас".'
        )

    rezultat = _najdi_oddel(baran)
    if not rezultat:
        return (
            f'Не најдов оддел со име „{baran}". Кликни на „Услуги" '
            "за листа на сите оддели или провери го правописот."
        )

    oddel_ime, _site = rezultat
    lekari = _zimi_lekari_od_oddel(oddel_ime)

    if not lekari:
        return f'На одделот „{oddel_ime}" моментално нема регистрирани лекари.'

    naslov = f'Лекари на одделот „{oddel_ime}" ({len(lekari)}):'
    redovi = [naslov, ""]
    for l in lekari:
        polno = f"Д-р {l['name']} {l['surname']}"
        email = l.get("email") or ""
        if email:
            redovi.append(f"- {polno} ({email})")
        else:
            redovi.append(f"- {polno}")

    redovi.append("")
    redovi.append(
        "За повеќе информации за лекар или за закажување на термин, во следната порака наведете го "
        'презимето (на пример: „Каков е д-р [презиме]?" или „Кога е слободен д-р [презиме]?").'
    )
    return "\n".join(redovi)
