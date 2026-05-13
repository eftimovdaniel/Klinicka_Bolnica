"""
Лекари по оддел / специјалност.

Примери:
- „Кои лекари се на одделот за Урологија?"
- „Кои се лекарите од Кардиологија?"
- „Прикажи ги докторите од хирургија"
- „Кои се на гинекологија?"

Логика:
1. Со AI (Groq) се извлекува името на одделот од прашањето.
2. Се прави fuzzy-match со постоечките оддели (Doctors.specialty + Oddeli.ime_na_oddel),
   за да се толерираат разлики во правопис / падежи / латиница.
3. Се враќаат лекарите од тој оддел.
"""

import json
import re

from database import get_connection
from ai.groq_client import ask_ai


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


def _normaliziraj(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"\s+", " ", s)
    return s


def _najdi_oddel(baran_oddel: str) -> tuple[str, list[str]] | None:
    """
    Прави fuzzy-match. Враќа (нормализирано_име_за_query, [сите_варијанти_во_DB])
    или None ако нема никакво совпаѓање.

    Стратегија:
    - Точна (case-insensitive) еднаквост во Doctors.specialty или Oddeli.ime_na_oddel
    - Substring совпаѓање (баран_оддел во DB име ИЛИ DB име во баран_оддел)
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

    site = list({*speci, *oddeli})
    if not site:
        return None

    barano_n = _normaliziraj(baran_oddel)

    for kandidat in site:
        if _normaliziraj(kandidat) == barano_n:
            return kandidat, site

    for kandidat in site:
        k_n = _normaliziraj(kandidat)
        if barano_n in k_n or k_n in barano_n:
            return kandidat, site

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


def odgovori_za_lekari_oddel(prashanje: str) -> str:
    baran = _izvlechi(prashanje)
    if baran == "_error":
        return (
            "Привремено сум зафатен. Те молам обиди се повторно за неколку секунди."
        )
    if not baran:
        return (
            'Не разбрав за кој оддел прашуваш. Те молам пишувај, на пр.: '
            '„Кои лекари се на Урологија?" или „Кои се од Кардиологија?"'
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
        'За детали или закажување напиши: „Каков е д-р [презиме]?" '
        'или „Кога е слободен д-р [презиме]?"'
    )
    return "\n".join(redovi)
