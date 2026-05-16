"""
Резолвирање на оддел / специјалност од прашање — агентски слој (правила → база → AI од листа).

Користи:
  - листа оддели живо од Doctors.specialty + Oddeli
  - алијаси (ОРЛ → Оториноларингологија, …)
  - правила (без AI) пред Groq
  - AI само за избор ЕДНО име од листата (closed-list)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache

from ai._kernel.agent_guidelines import (
    SOURCE_AI_LIST,
    SOURCE_ALIAS,
    SOURCE_EXACT,
    SOURCE_RULES,
)
from ai._kernel.ai_json import parse_ai_json
from ai._kernel.db_helpers import db_cursor
from ai._kernel.groq_client import ask_ai
from ai._kernel.prompt_loader import load_prompt_template
from ai._kernel.transliteracija import transliterijaj

# Клучни зборови во прашањето (нормализирано) → мора да се појават во името од база
_ALIAS_KEYWORDS: dict[str, str] = {
    "орл": "оториноларинголог",
    "orl": "otorinolaringolog",
    "оториноларингологија": "оториноларинголог",
    "оториноларингологи": "оториноларинголог",
    "otorinolaringologija": "otorinolaringolog",
    "kardiologija": "кардиолог",
    "кардиологија": "кардиолог",
    "kardiolog": "кардиолог",
    "кардиолог": "кардиолог",
    "nevrolog": "невролог",
    "невролог": "невролог",
    "urologija": "уролог",
    "урологија": "уролог",
    "ginekologija": "гинеколог",
    "гинекологија": "гинеколог",
    "pedijatrija": "педијатр",
    "педијатрија": "педијатр",
    "neurologija": "невролог",
    "неврологија": "невролог",
    "ortopedija": "ортопед",
    "ортопедија": "ортопед",
    "radiologija": "радиолог",
    "радиологија": "радиолог",
    "onkologija": "онколог",
    "онкологија": "онколог",
    "dermatologija": "дерматолог",
    "дерматологија": "дерматолог",
    "oftalmologija": "офталмолог",
    "офталмологија": "офталмолог",
}

_RE_ODDEL_ZA = re.compile(
    r"(?:на\s+)?оддел(?:от)?\s+за\s+([^?.!,;]+)|"
    r"од\s+оддел(?:от)?\s+за\s+([^?.!,;]+)|"
    r"лекари\s+(?:од|на)\s+([^?.!,;]+)|"
    r"лекарите\s+(?:од|на)\s+([^?.!,;]+)",
    re.IGNORECASE | re.UNICODE,
)


@dataclass(frozen=True)
class OddelResolveResult:
    """Резултат од resolve_oddel — за handler и за debug."""

    ok: bool
    oddel: str | None
    site_oddeli: tuple[str, ...]
    barano: str | None
    method: str
    poraka_greska: str | None = None


def _normaliziraj(s: str) -> str:
    s = transliterijaj(s).lower().strip()
    return re.sub(r"\s+", " ", s)


@lru_cache(maxsize=1)
def zimi_site_oddeli() -> tuple[str, ...]:
    """Сите уникатни имиња од Doctors.specialty + Oddeli.ime_na_oddel."""
    speci: list[str] = []
    oddeli: list[str] = []
    try:
        with db_cursor() as (_, cur):
            cur.execute(
                """
                SELECT DISTINCT TRIM(specialty) AS oddel FROM Doctors
                WHERE specialty IS NOT NULL AND TRIM(specialty) <> ''
                """
            )
            speci = [r["oddel"] for r in cur.fetchall() if r.get("oddel")]
            cur.execute(
                "SELECT ime_na_oddel AS oddel FROM Oddeli WHERE ime_na_oddel IS NOT NULL"
            )
            oddeli = [r["oddel"] for r in cur.fetchall() if r.get("oddel")]
    except Exception as e:
        print(f"[oddel_resolver] fetch greshka: {e}")
        return tuple()
    return tuple(sorted({*speci, *oddeli}, key=lambda x: (len(x), x)))


def _match_po_klucen_zbor(klucen: str, site: tuple[str, ...]) -> str | None:
    for ime in site:
        if klucen in _normaliziraj(ime):
            return ime
    return None


def _match_alias_vo_prasanje(p: str, site: tuple[str, ...]) -> str | None:
    for alias, klucen in _ALIAS_KEYWORDS.items():
        if alias in p:
            found = _match_po_klucen_zbor(klucen, site)
            if found:
                return found
    return None


def _match_hirurgija(p: str, site: tuple[str, ...]) -> str | None:
    """Хирургија ≠ Неврохирургија освен ако корисникот каже „невро". """
    if "неврохирурги" in p or "neurohirurg" in p:
        return _match_po_klucen_zbor("неврохирурги", site)
    if "хирурги" not in p and "hirurg" not in p:
        return None
    # Точно „Хирургија" ако постои
    for ime in site:
        if _normaliziraj(ime) == "хирургија":
            return ime
    # Други хирургиски без „невро"
    kandidati = [
        k
        for k in site
        if "хирурги" in _normaliziraj(k) and "невро" not in _normaliziraj(k)
    ]
    if len(kandidati) == 1:
        return kandidati[0]
    if kandidati:
        return min(kandidati, key=len)
    return None


def _match_tocno_ili_blisko(baran: str, site: tuple[str, ...]) -> str | None:
    bn = _normaliziraj(baran)
    for ime in site:
        if _normaliziraj(ime) == bn:
            return ime
    found = _match_po_klucen_zbor(bn, site)
    if found:
        return found
    return None


def _pravila_izvlechi(prashanje: str, site: tuple[str, ...]) -> tuple[str | None, str]:
    p = _normaliziraj(prashanje)

    m = _RE_ODDEL_ZA.search(prashanje)
    if m:
        fragment = next((g.strip() for g in m.groups() if g), "")
        if fragment:
            tocno = _match_tocno_ili_blisko(fragment, site)
            if tocno:
                return tocno, SOURCE_RULES

    alias = _match_alias_vo_prasanje(p, site)
    if alias:
        return alias, SOURCE_ALIAS

    hir = _match_hirurgija(p, site)
    if hir:
        return hir, SOURCE_RULES

    return None, ""


def _ai_izberi_od_lista(prashanje: str, site: tuple[str, ...]) -> str | None:
    if not site:
        return None
    lista = json.dumps(list(site), ensure_ascii=False)
    from ai._kernel.prompt_loader import load_prompt_template

    prompt = load_prompt_template(
        "oddel_closed_list",
        lista=lista,
        prashanje=prashanje,
    )
    odgovor = ask_ai(f"Прашање: {prashanje}", system_prompt=prompt)
    data = parse_ai_json(odgovor, log_tag="oddel_resolver")
    if data.get("_error"):
        return "_error"
    val = data.get("oddel")
    if not val:
        return None
    val = str(val).strip()
    for ime in site:
        if _normaliziraj(ime) == _normaliziraj(val):
            return ime
    return None


def resolve_oddel(prashanje: str) -> OddelResolveResult:
    """
    Главна функција: од прашање → каноничко име од база или јасна грешка.
    """
    site = zimi_site_oddeli()
    if not site:
        return OddelResolveResult(
            ok=False,
            oddel=None,
            site_oddeli=site,
            barano=None,
            method="",
            poraka_greska="Нема регистрирани оддели во системот.",
        )

    oddel, method = _pravila_izvlechi(prashanje, site)
    if oddel:
        return OddelResolveResult(
            ok=True,
            oddel=oddel,
            site_oddeli=site,
            barano=oddel,
            method=method,
        )

    ai_val = _ai_izberi_od_lista(prashanje, site)
    if ai_val == "_error":
        return OddelResolveResult(
            ok=False,
            oddel=None,
            site_oddeli=site,
            barano=None,
            method=SOURCE_AI_LIST,
            poraka_greska="_ai_busy",
        )
    if ai_val:
        return OddelResolveResult(
            ok=True,
            oddel=ai_val,
            site_oddeli=site,
            barano=ai_val,
            method=SOURCE_AI_LIST,
        )

    return OddelResolveResult(
        ok=False,
        oddel=None,
        site_oddeli=site,
        barano=None,
        method="",
        poraka_greska=None,
    )


def format_lista_oddeli(site: tuple[str, ...] | None = None) -> str:
    """Кратка помош за корисник кога одделот не е пронајден."""
    site = site or zimi_site_oddeli()
    if not site:
        return "Моментално нема листа на оддели во системот."
    redovi = ["Достапни оддели / специјалности во болницата:"]
    for o in site:
        redovi.append(f"• {o}")
    return "\n".join(redovi)
