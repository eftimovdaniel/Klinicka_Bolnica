"""
Лекари по оддел / специјалност (агент: lekari_oddel).

Патека:
  1. Дали е прашање за СИТЕ лекари? → навигација #lekari
  2. resolve_oddel(prasanje) — правила + алијаси + AI само од листа од база
  3. SQL: Doctors WHERE specialty = <оддел>
  4. Форматиран одговор

Види: ai._kernel.agent_guidelines, ai._kernel.oddel_resolver
"""

import re
from typing import Any

from ai._kernel.oddel_resolver import format_lista_oddeli, resolve_oddel
from ai._kernel.transliteracija import transliterijaj
from ai._kernel.db_helpers import db_cursor


def _site_lekari_vo_ustanova(prasanje: str) -> bool:
    """Прашање за целиот лекарски тим (без конкретен оддел)."""
    p = transliterijaj(prasanje).lower()
    if not any(w in p for w in ("лекар", "доктор", "специјалист")):
        return False
    if re.search(r"на\s+оддел", p) or re.search(r"од\s+оддел", p) or re.search(
        r"оддел(?:от|о)?\s+за", p
    ):
        return False
    if re.search(r"во\s+болниц", p):
        return True
    if re.search(r"во\s+установ", p) or "установа" in p or "установата" in p:
        return True
    if re.search(r"во\s+клиник", p) or "клиниката" in p:
        return True
    if "кај вас" in p:
        return True
    if re.search(r"каде\s+(?:се\s+)?(?:наоѓа|сме|се)?\s*(?:лекар|доктор)", p):
        return True
    if re.search(
        r"kade\s+(?:se\s+)?(?:naogja|naodga|sme|se)?\s*(?:lekar|lekari|doktor)", p
    ):
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


def odgovor_navigacija_lekari() -> dict[str, Any]:
    """Кратка порака + скрол кон #lekari."""
    from ai.pacient.slobodni_termini import zimi_site_lekari

    lekari = zimi_site_lekari()
    n = len(lekari) if lekari else 0
    if n == 0:
        odgovor = (
            'Ве пренасочувам кон делот „Лекари" на почетната страница. '
            "Моментално нема регистрирани лекари во системот."
        )
    else:
        odgovor = (
            'Ве пренасочувам кон делот „Лекари" на почетната страница. '
            f"На екранот ќе ја видите листата со {n} лекари — "
            "можете да пребарувате по име или специјалност и да закажете преглед."
        )
    return {
        "odgovor": odgovor,
        "navigacija": {"target": "index.html#lekari", "label": "Лекари"},
    }


def _zimi_lekari_od_oddel(oddel: str) -> list[dict]:
    try:
        with db_cursor() as (_, cur):
            cur.execute(
                """
                SELECT doctor_ID, name, surname, specialty, email
                FROM Doctors
                WHERE LOWER(TRIM(specialty)) = LOWER(TRIM(%s))
                ORDER BY surname, name
                """,
                (oddel,),
            )
            return list(cur.fetchall())
    except Exception as e:
        print(f"[lekari_oddel] lekari greska: {e}")
        return []


def odgovori_za_lekari_oddel(prasanje: str) -> str | dict[str, Any]:
    if _site_lekari_vo_ustanova(prasanje):
        return odgovor_navigacija_lekari()

    resolved = resolve_oddel(prasanje)

    if resolved.poraka_greska == "_ai_busy":
        return "Привремено сум зафатен. Те молам обиди се повторно за неколку секунди."

    if not resolved.ok or not resolved.oddel:
        if _site_lekari_vo_ustanova(prasanje):
            return odgovor_navigacija_lekari()
        delovi = [
            'Ако прашувате за конкретен оддел, наведете го (на пр.: „Кои лекари се на Кардиологија?").',
            'За целиот тим: „Кои лекари работат во болницата?" или „Каде се лекарите?".',
            "",
            format_lista_oddeli(resolved.site_oddeli),
        ]
        return "\n".join(delovi)

    oddel_ime = resolved.oddel
    print(f"[lekari_oddel] оддел={oddel_ime!r} method={resolved.method}")

    lekari = _zimi_lekari_od_oddel(oddel_ime)

    if not lekari:
        return (
            f'На одделот „{oddel_ime}" моментално нема регистрирани лекари.\n\n'
            + format_lista_oddeli(resolved.site_oddeli)
        )

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
        "За повеќе информации или термин, наведете презиме "
        '(на пр.: „Кога е слободен д-р [презиме]?").'
    )
    return "\n".join(redovi)
