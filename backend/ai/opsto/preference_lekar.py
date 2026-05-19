"""
Преференции за лекар (пол, специјалност, искуство).

База: Doctors (name, surname, specialty). Пол/јазик немаат колона —
женски/машки се приближно преку име; за јазик насочување кон рецепција.
"""

import re

from ai._kernel.ai_json import parse_ai_json
from ai._kernel.db_helpers import db_cursor
from ai._kernel.groq_client import ask_ai
from ai._kernel.oddel_resolver import resolve_oddel
from ai._kernel.prompt_loader import load_prompt
from ai._kernel.transliteracija import transliterijaj

_RECEPTCIJA = "032/ 605-001"

_ZENSKI_IMENA = frozenset(
    {
        "марија",
        "ана",
        "елена",
        "софија",
        "ивана",
        "наташа",
        "весна",
        "олга",
        "тамара",
        "снежана",
        "катерина",
        "викторија",
        "александра",
        "јордана",
    }
)

_STOP_TOKENS = frozenset(
    {
        "има",
        "ли",
        "дали",
        "женски",
        "машки",
        "кој",
        "кои",
        "зборува",
        "искуство",
        "млад",
        "стар",
        "лекар",
        "лекари",
        "доктор",
        "докторка",
        "овој",
        "ова",
        "овде",
        "таму",
        "дел",
        "одел",
        "оддел",
        "истиот",
        "иста",
        "исти",
        "на",
        "од",
        "за",
        "пак",
    }
)

_FOLLOWUP_MARKERS = (
    "овој дел",
    "овој одел",
    "овој оддел",
    "од овој",
    "на овој",
    "истиот одел",
    "истиот оддел",
    "ист дел",
    "истиот дел",
    "таму",
    "овде",
    "пак",
    "a zenski",
    "a maski",
    "а женски",
    "а машки",
)


def _izvlechi(prasanje: str) -> dict:
    from ai._kernel.groq_helpers import groq_zadolzhitelen

    if msg := groq_zadolzhitelen():
        return {"_error": msg}
    odgovor = ask_ai(
        f"Прашање: {prasanje!r}",
        system_prompt=load_prompt("preference_lekar_extract"),
    )
    return parse_ai_json(odgovor, log_tag="preference_lekar")


def _verojatno_zenski(ime: str) -> bool:
    i = (ime or "").strip().lower()
    if not i:
        return False
    if i in _ZENSKI_IMENA:
        return True
    return len(i) > 2 and i.endswith("а")


def _filtriraj_pol(lekari: list[dict], pol: str | None) -> list[dict]:
    if pol not in ("zenski", "muski"):
        return lekari
    out: list[dict] = []
    for lekar in lekari:
        z = _verojatno_zenski(lekar.get("name") or "")
        if pol == "zenski" and z:
            out.append(lekar)
        elif pol == "muski" and not z:
            out.append(lekar)
    return out


def _lekari_po_specialty(specialty: str) -> list[dict]:
    with db_cursor() as (_, cur):
        cur.execute(
            """
            SELECT doctor_ID, name, surname, specialty
            FROM Doctors
            WHERE specialty = %s
            ORDER BY surname, name
            """,
            (specialty,),
        )
        return list(cur.fetchall() or [])


def _e_nastavok(prasanje: str) -> bool:
    p = transliterijaj(prasanje).lower()
    return any(m in p for m in _FOLLOWUP_MARKERS)


def _oddel_od_kontekst(kontekst: dict | None) -> str | None:
    if not isinstance(kontekst, dict):
        return None
    for key in ("last_oddel", "oddel", "specialty"):
        val = kontekst.get(key)
        if val and str(val).strip():
            return str(val).strip()
    return None


def _specialty_se_sovpaagja(prasanje: str, specialty: str) -> bool:
    p = transliterijaj(prasanje).lower()
    sp = transliterijaj(specialty or "").lower()
    if not sp:
        return False
    if sp in p:
        return True
    for tok in re.findall(r"[\w\u0400-\u04FF]+", p):
        if len(tok) < 5 or tok in _STOP_TOKENS:
            continue
        if tok in sp:
            return True
    return False


def _najdi_oddel(prasanje: str, kontekst: dict | None) -> str | None:
    resolved = resolve_oddel(prasanje)
    if resolved.ok and resolved.oddel:
        return resolved.oddel

    if _e_nastavok(prasanje) or _oddel_od_kontekst(kontekst):
        oddel = _oddel_od_kontekst(kontekst)
        if oddel:
            return oddel

    from ai.pacient.slobodni_termini import zimi_site_lekari

    site = zimi_site_lekari()
    for l in site:
        sp = l.get("specialty") or ""
        if _specialty_se_sovpaagja(prasanje, sp):
            return sp
    return None


def _najdi_lekari(prasanje: str, kontekst: dict | None) -> tuple[list[dict], str | None]:
    oddel = _najdi_oddel(prasanje, kontekst)
    if oddel:
        return _lekari_po_specialty(oddel), oddel
    return [], None


def _nov_kontekst(oddel: str | None, pol: str | None) -> dict:
    ctx: dict = {"intent": "preference_lekar"}
    if oddel:
        ctx["last_oddel"] = oddel
    if pol:
        ctx["last_pol"] = pol
    return ctx


def odgovori_za_preference(prasanje: str, kontekst: dict | None = None) -> dict:
    pod = _izvlechi(prasanje)
    pol = (pod.get("pol") or "").strip().lower() or None
    if pol not in ("zenski", "muski"):
        pol = _izvlechi(prasanje).get("pol")
    if pol not in ("zenski", "muski"):
        pol = None
    jazik = (pod.get("jazik") or "").strip() or None

    lekari, oddel = _najdi_lekari(prasanje, kontekst)

    if not oddel:
        return {
            "odgovor": (
                'За кој оддел барате лекар? Наведете го (на пр. "Оториноларингологија") '
                f"или повторете го првото прашање со одделот.\n"
                f"Рецепција: {_RECEPTCIJA}."
            ),
            "kontekst": kontekst if isinstance(kontekst, dict) else None,
        }

    if not lekari:
        return {
            "odgovor": (
                f'На одделот "{oddel}" нема регистрирани лекари.\n'
                f"Јавете се на рецепција ({_RECEPTCIJA})."
            ),
            "kontekst": _nov_kontekst(oddel, pol),
        }

    lekari = _filtriraj_pol(lekari, pol)

    if jazik:
        return {
            "odgovor": (
                f"За лекар што зборува {jazik}, најточно е да прашате на рецепција ({_RECEPTCIJA}).\n"
                f'На одделот "{oddel}" имаме {len(_lekari_po_specialty(oddel))} лекар(и) - '
                "рецепцијата ќе ви предложи соодветен термин."
            ),
            "kontekst": _nov_kontekst(oddel, pol),
        }

    if pol and not lekari:
        pol_txt = "женски" if pol == "zenski" else "машки"
        return {
            "odgovor": (
                f'Не најдов {pol_txt} лекар на одделот "{oddel}".\n'
                f"Препорачувам рецепција ({_RECEPTCIJA}) или избор од листата на сајтот."
            ),
            "kontekst": _nov_kontekst(oddel, pol),
        }

    linii = [f'Лекари на одделот "{oddel}" што одговараат на барањето:', ""]
    for lekar in lekari[:8]:
        spec = lekar.get("specialty") or "—"
        linii.append(
            f"• Д-р {lekar.get('name', '')} {lekar.get('surname', '')} — {spec}"
        )
    if len(lekari) > 8:
        linii.append(f"\n... и уште {len(lekari) - 8}.")
    linii.append(f"\nЗа закажување: рецепција ({_RECEPTCIJA}) или формата за термин на сајтот.")
    return {
        "odgovor": "\n".join(linii),
        "kontekst": _nov_kontekst(oddel, pol),
    }
