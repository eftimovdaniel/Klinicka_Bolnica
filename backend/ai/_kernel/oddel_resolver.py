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
    "дерматовенерологија": "дерматолог",
    "дерматовенеролог": "дерматолог",
    "dermatovenerologija": "дерматолог",
    "dermatovenerolog": "дерматолог",
    "oftalmologija": "офталмолог",
    "офталмологија": "офталмолог",
    "интернист": "интерна",
    "internist": "intern",
    "интерна": "интерна",
    "interna": "intern",
    "интерн": "интерна",
    "пластична хирургија": "пластич",
    "пластична": "пластич",
    "plastichna hirurgija": "plastichn",
    "plastichna": "plastichn",
    "кардиохирургија": "кардиохирурги",
    "kardiohirurgija": "kardiohirurg",
    "неврохирургија": "неврохирурги",
    "neurohirurgija": "neurohirurg",
}

_RE_ODDEL_ZA = re.compile(
    r"(?:на\s+)?од(?:ел|дел)(?:от|о)?\s+за\s+([^?.!,;]+)|"
    r"од\s+од(?:ел|дел)(?:от|о)?\s+за\s+([^?.!,;]+)|"
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
        print(f"[oddel_resolver] fetch greska: {e}")
        return tuple()
    return tuple(sorted({*speci, *oddeli}, key=lambda x: (len(x), x)))


def _match_po_klucen_zbor(klucen: str, site: tuple[str, ...]) -> str | None:
    for ime in site:
        if klucen in _normaliziraj(ime):
            return ime
    return None


def _match_ime_vo_prasanje(p: str, site: tuple[str, ...]) -> str | None:
    """Целосно име на специјалност од база ако се појавува во прашањето (најдолго прво)."""
    for ime in sorted(site, key=lambda x: len(_normaliziraj(x)), reverse=True):
        in_norm = _normaliziraj(ime)
        if len(in_norm) >= 6 and in_norm in p:
            return ime
    return None


def _match_alias_vo_prasanje(p: str, site: tuple[str, ...]) -> str | None:
    for alias, klucen in _ALIAS_KEYWORDS.items():
        if alias in p:
            found = _match_po_klucen_zbor(klucen, site)
            if found:
                return found
    return None


def _match_fragment_po_zborovi(fragment: str, site: tuple[str, ...]) -> str | None:
    """
    Најдобар оддел по заеднички зборови од фрагментот
    (пр. „пластична хирургија" → Пластична хирургија, не Кардиохирургија).
    """
    fn = _normaliziraj(fragment)
    words = [w for w in fn.split() if len(w) >= 4]
    if not words:
        return None

    best_ime: str | None = None
    best_score = 0
    for ime in site:
        inorm = _normaliziraj(ime)
        score = sum(1 for w in words if w in inorm)
        if score > best_score:
            best_score = score
            best_ime = ime

    if not best_ime or best_score < 2:
        return None
    # Ако корисникот кажа „пластична", одделот мора да ја содржи таа ознака
    for marker in ("plastichn", "пластич", "kardio", "кардио", "невро", "neuro"):
        if marker in fn and marker not in _normaliziraj(best_ime):
            alt = _match_po_klucen_zbor(marker, site)
            if alt:
                return alt
            return None
    return best_ime


def _match_hirurgija(p: str, site: tuple[str, ...]) -> str | None:
    """Хирургија — со подтип (пластична, кардио, невро), не најкраткото име."""
    if "неврохирурги" in p or "neurohirurg" in p:
        return _match_po_klucen_zbor("неврохирурги", site)
    if "кардиохирурги" in p or "kardiohirurg" in p:
        return _match_po_klucen_zbor("кардиохирурги", site)
    if "пластич" in p or "plastichn" in p:
        return _match_po_klucen_zbor("пластич", site)
    if "хирурги" not in p and "hirurg" not in p:
        return None

    # Квалификувана хирургија — не избирај произволен „*хирургија*"
    if any(
        q in p
        for q in (
            "пластич",
            "plastichn",
            "кардио",
            "kardio",
            "невро",
            "neuro",
            "рекonstrukt",
            "реконструкт",
            "торакал",
            "torakal",
        )
    ):
        return _match_fragment_po_zborovi(p, site)

    for ime in site:
        if _normaliziraj(ime) == "хирургија":
            return ime

    kandidati = [
        k
        for k in site
        if "хирурги" in _normaliziraj(k) and "невро" not in _normaliziraj(k)
    ]
    if len(kandidati) == 1:
        return kandidati[0]
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


def _pravila_izvlechi(prasanje: str, site: tuple[str, ...]) -> tuple[str | None, str]:
    p = _normaliziraj(prasanje)

    m = _RE_ODDEL_ZA.search(prasanje)
    if m:
        fragment = next((g.strip() for g in m.groups() if g), "")
        if fragment:
            tocno = _match_tocno_ili_blisko(fragment, site)
            if tocno:
                return tocno, SOURCE_RULES
            po_zborovi = _match_fragment_po_zborovi(fragment, site)
            if po_zborovi:
                return po_zborovi, SOURCE_RULES
            alias_frag = _match_alias_vo_prasanje(_normaliziraj(fragment), site)
            if alias_frag:
                return alias_frag, SOURCE_ALIAS

    direktno = _match_ime_vo_prasanje(p, site)
    if direktno:
        return direktno, SOURCE_RULES

    alias = _match_alias_vo_prasanje(p, site)
    if alias:
        return alias, SOURCE_ALIAS

    hir = _match_hirurgija(p, site)
    if hir:
        return hir, SOURCE_RULES

    return None, ""


def _ai_izberi_od_lista(prasanje: str, site: tuple[str, ...]) -> str | None:
    if not site:
        return None
    lista = json.dumps(list(site), ensure_ascii=False)
    from ai._kernel.prompt_loader import load_prompt_template

    prompt = load_prompt_template(
        "oddel_closed_list",
        lista=lista,
        prasanje=prasanje,
    )
    odgovor = ask_ai(f"Прашање: {prasanje}", system_prompt=prompt)
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


def resolve_oddel(prasanje: str) -> OddelResolveResult:
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

    oddel, method = _pravila_izvlechi(prasanje, site)
    if oddel:
        return OddelResolveResult(
            ok=True,
            oddel=oddel,
            site_oddeli=site,
            barano=oddel,
            method=method,
        )

    ai_val = _ai_izberi_od_lista(prasanje, site)
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
