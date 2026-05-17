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
from ai.pacient.slobodni_termini import (
    lekar_od_zakazi_kontekst,
    prasanje_e_drugi_lekari_specijalnost,
)


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


def _specijalnost_od_lekari(oddel: str, lekari: list[dict] | None) -> str:
    """Точен низ од Doctors.specialty за филтер на фронтот."""
    if lekari:
        for l in lekari:
            s = (l.get("specialty") or l.get("specijalnost") or "").strip()
            if s:
                return s
    return (oddel or "").strip()


def navigacija_lekari(
    oddel: str | None = None,
    lekari: list[dict] | None = None,
) -> dict[str, str]:
    """Навигација кон #lekari; опционално филтрирање по специјалност на фронтот."""
    nav: dict[str, str] = {"target": "index.html#lekari", "label": "Лекари"}
    if oddel:
        spec = _specijalnost_od_lekari(oddel, lekari)
        nav["label"] = f"Лекари — {spec or oddel}"
        nav["specijalnost"] = spec or oddel
    return nav


def odgovor_navigacija_lekari(oddel: str | None = None) -> dict[str, Any]:
    """Кратка порака + скрол кон #lekari (опционално филтрирано по оддел)."""
    from ai.pacient.slobodni_termini import zimi_site_lekari

    lekari = zimi_site_lekari()
    n = len(lekari) if lekari else 0
    if oddel:
        intro = (
            f'Ве пренасочувам кон делот „Лекари" со филтер за „{oddel}". '
            "На екранот ќе ги видите само лекарите од таа специјалност."
        )
    elif n == 0:
        intro = (
            'Ве пренасочувам кон делот „Лекари" на почетната страница. '
            "Моментално нема регистрирани лекари во системот."
        )
    else:
        intro = (
            'Ве пренасочувам кон делот „Лекари" на почетната страница. '
            f"На екранот ќе ја видите листата со {n} лекари — "
            "можете да пребарувате по име или специјалност и да закажете преглед."
        )
    return {"odgovor": intro, "navigacija": navigacija_lekari(oddel)}


def _linija_lekar(l: dict) -> str:
    """Една ставка — еднаш „Д-р", без дуплирање."""
    return f"- Д-р {l.get('name', '').strip()} {l.get('surname', '').strip()}".strip()


def _naslov_lista_lekari(
    oddel_ime: str,
    lekari: list[dict],
    lekar_ref: dict | None,
    drugi_od_istata: bool,
) -> str:
    if drugi_od_istata and lekar_ref:
        ref = f"д-р {lekar_ref.get('name', '')} {lekar_ref.get('surname', '')}".strip()
        spec = (oddel_ime or lekar_ref.get("specialty") or "").strip()
        if spec:
            return (
                f"Лекари кои работат во истата специјалност како {ref} ({spec}) се:"
            )
        return f"Лекари кои работат во истата специјалност како {ref} се:"
    return f'Лекари од специјалноста „{oddel_ime}" ({len(lekari)}):'


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


def odgovori_za_lekari_oddel(
    prasanje: str, kontekst: dict | None = None
) -> str | dict[str, Any]:
    if _site_lekari_vo_ustanova(prasanje):
        return odgovor_navigacija_lekari()

    oddel_ime: str | None = None
    exclude_doctor_id: int | None = None
    lekar_ref: dict | None = None
    drugi_od_istata = prasanje_e_drugi_lekari_specijalnost(prasanje)
    site_oddeli: tuple[str, ...] = ()

    if drugi_od_istata:
        lekar_ctx = lekar_od_zakazi_kontekst(kontekst)
        if lekar_ctx:
            lekar_ref = lekar_ctx
            oddel_ime = (lekar_ctx.get("specialty") or "").strip() or None
            exclude_doctor_id = int(lekar_ctx["doctor_ID"])

    resolved = resolve_oddel(prasanje) if not oddel_ime else None
    if resolved:
        site_oddeli = resolved.site_oddeli
        if resolved.poraka_greska == "_ai_busy":
            return "Привремено сум зафатен. Те молам обиди се повторно за неколку секунди."
        if resolved.ok and resolved.oddel:
            oddel_ime = resolved.oddel
    elif not site_oddeli:
        from ai._kernel.oddel_resolver import zimi_site_oddeli

        site_oddeli = zimi_site_oddeli()

    if not oddel_ime:
        if _site_lekari_vo_ustanova(prasanje):
            return odgovor_navigacija_lekari()
        delovi = [
            'Ако прашувате за конкретен оддел, наведете го (на пр.: „Кои лекари се на Кардиологија?").',
            'За целиот тим: „Кои лекари работат во болницата?" или „Каде се лекарите?".',
            "",
            format_lista_oddeli(site_oddeli),
        ]
        return "\n".join(delovi)

    method = resolved.method if resolved else "kontekst_lekar"
    print(f"[lekari_oddel] оддел={oddel_ime!r} method={method}")

    lekari = _zimi_lekari_od_oddel(oddel_ime)
    if exclude_doctor_id is not None:
        lekari = [
            l for l in lekari if int(l["doctor_ID"]) != int(exclude_doctor_id)
        ]

    if not lekari:
        if exclude_doctor_id is not None:
            return (
                f'На специјалноста „{oddel_ime}" нема други регистрирани лекари '
                "освен оној од претходната порака.\n\n"
                "Можете да закажете кај него (напишете го часот) или да изберете "
                "друга специјалност од листата:\n\n"
                + format_lista_oddeli(site_oddeli)
            )
        return (
            f'На одделот „{oddel_ime}" моментално нема регистрирани лекари.\n\n'
            + format_lista_oddeli(site_oddeli)
        )

    naslov = _naslov_lista_lekari(
        oddel_ime or "",
        lekari,
        lekar_ref,
        drugi_od_istata and exclude_doctor_id is not None,
    )

    redovi = [naslov, ""]
    for l in lekari:
        redovi.append(_linija_lekar(l))

    redovi.append("")
    sledna = (
        "За слободни термини напишете: „Кога е слободен д-р [презиме]?“ "
        "или „закажи кај [презиме] во [час]“."
    )
    redovi.append(sledna)
    sablon = "\n".join(redovi)

    return {
        "odgovor": sablon,
        "navigacija": navigacija_lekari(oddel_ime, lekari),
    }
