# modul za preference na lekar
# ovoj fajl sluzi korisnikot da moze da bara lekar spored:
# - pol (zenski/maski)
# - oddel/specijalnost
# - iskustvo
# - jazik

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
# konstanta za telefonski broj na recepcija
# konstantite po pravilo se pisuvaat so golemi bukvi

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
# frozenset e nepromenliv set — pobrz za prebaruvanje
# primer: "марија" in _ZENSKI_IMENA -> True
# ne moze da se menuva posle kreiranje

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
# zborovi koi ne ni se korisni pri sporedba so specialty
# primer: "дали има женски лекар" — "дали" se ignorira

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
# frazi za follow-up — "a zenski tamu?" znaci ist oddel od kontekst


def _izvlechi(prasanje: str) -> dict:
    # funkcija koja koristi ai za izvlekuvanje podatoci od korisnickoto prasanje
    from ai._kernel.groq_helpers import groq_zadolzhitelen
    # lazy import — ne se vcituva pri start na aplikacijata

    if msg := groq_zadolzhitelen():
        # walrus operator — zacuvuva i proveruva dali groq raboti
        return {"_error": msg}
        # ako ai servisot ne raboti — vrakame greska

    odgovor = ask_ai(
        f"Прашање: {prasanje!r}",
        system_prompt=load_prompt("preference_lekar_extract"),
    )
    # ask_ai go prakja prasanjeto do modelot
    # !r e raw string; promptot e vo poseben fajl

    return parse_ai_json(odgovor, log_tag="preference_lekar")
    # ai odgovorot se pretvara vo dict


def _verojatno_zenski(ime: str) -> bool:
    # heuristika za procena dali ime e zensko — vo baza nema kolona za pol
    i = (ime or "").strip().lower()
    # strip + lower za sporedba
    if not i:
        return False
        # ako nema ime — ne mozeme da pretpostavime pol
    if i in _ZENSKI_IMENA:
        return True
        # direktna proverka vo listata
    return len(i) > 2 and i.endswith("а")
    # mnogu zenski iminja zavrsuvaat na "а"


def _filtriraj_pol(lekari: list[dict], pol: str | None) -> list[dict]:
    # filtriranje na lista od lekari spored pol
    if pol not in ("zenski", "muski"):
        return lekari
        # ako nema validen pol — vrati gi site
    out: list[dict] = []
    for lekar in lekari:
        z = _verojatno_zenski(lekar.get("name") or "")
        if pol == "zenski" and z:
            out.append(lekar)
        elif pol == "muski" and not z:
            out.append(lekar)
    return out


def _lekari_po_specialty(specialty: str) -> list[dict]:
    # gi zema site lekari od odreden oddel/specijalnost
    with db_cursor() as (_, cur):
        # context manager — automatski zatvora konekcija
        cur.execute(
            """
            SELECT doctor_ID, name, surname, specialty
            FROM Doctors
            WHERE specialty = %s
            ORDER BY surname, name
            """,
            (specialty,),
        )
        # %s e placeholder — bezbednost protiv sql injection
        return list(cur.fetchall() or [])
        # fetchall — prazna lista ako nema rezultati


def _e_nastavok(prasanje: str) -> bool:
    # dali prasanjeto e prodolzenie na prethoden razgovor
    p = transliterijaj(prasanje).lower()
    return any(m in p for m in _FOLLOWUP_MARKERS)
    # any vraka True ako barem eden marker postoi


def _oddel_od_kontekst(kontekst: dict | None) -> str | None:
    # zema oddel od prethoden chat kontekst
    if not isinstance(kontekst, dict):
        return None
    for key in ("last_oddel", "oddel", "specialty"):
        val = kontekst.get(key)
        if val and str(val).strip():
            return str(val).strip()
            # vrati go prviot validen oddel
    return None


def _specialty_se_sovpaagja(prasanje: str, specialty: str) -> bool:
    # dali korisnickoto prasanje se sovpagja so specialty
    p = transliterijaj(prasanje).lower()
    sp = transliterijaj(specialty or "").lower()
    if not sp:
        return False
    if sp in p:
        return True
        # direktno sovpagjanje
    for tok in re.findall(r"[\w\u0400-\u04FF]+", p):
        if len(tok) < 5 or tok in _STOP_TOKENS:
            continue
        if tok in sp:
            return True
            # delimicno sovpagjanje
    return False


def _najdi_oddel(prasanje: str, kontekst: dict | None) -> str | None:
    # glavna logika za pronagjanje oddel
    resolved = resolve_oddel(prasanje)
    if resolved.ok and resolved.oddel:
        return resolved.oddel
        # resolver modul — primer "usno" -> stomatologija

    if _e_nastavok(prasanje) or _oddel_od_kontekst(kontekst):
        oddel = _oddel_od_kontekst(kontekst)
        if oddel:
            return oddel
            # follow-up — "tamu" znaci oddel od kontekst

    from ai.pacient.slobodni_termini import zimi_site_lekari
    # lazy import — izbegnuvanje circular imports

    site = zimi_site_lekari()
    for l in site:
        sp = l.get("specialty") or ""
        if _specialty_se_sovpaagja(prasanje, sp):
            return sp
    return None


def _najdi_lekari(prasanje: str, kontekst: dict | None) -> tuple[list[dict], str | None]:
    # vraka lista lekari + ime na oddel
    oddel = _najdi_oddel(prasanje, kontekst)
    if oddel:
        return _lekari_po_specialty(oddel), oddel
    return [], None


def _nov_kontekst(oddel: str | None, pol: str | None) -> dict:
    # kreira nov kontekst za sledni poraki
    ctx: dict = {"intent": "preference_lekar"}
    if oddel:
        ctx["last_oddel"] = oddel
    if pol:
        ctx["last_pol"] = pol
    return ctx


def odgovori_za_preference(prasanje: str, kontekst: dict | None = None) -> dict:
    # glavna funkcija — entry point za ovoj modul
    pod = _izvlechi(prasanje)
    # ai analiza na korisnickoto prasanje

    pol = (pod.get("pol") or "").strip().lower() or None
    if pol not in ("zenski", "muski"):
        pol = _izvlechi(prasanje).get("pol")
        # povtoren obid ako prviot pat ne uspee
    if pol not in ("zenski", "muski"):
        pol = None

    jazik = (pod.get("jazik") or "").strip() or None
    # jazik — nasocuvanje kon recepcija

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
    # filtriranje po pol

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
        # maksimum 8 lekari vo listata
        spec = lekar.get("specialty") or "—"
        linii.append(
            f"• Д-р {lekar.get('name', '')} {lekar.get('surname', '')} — {spec}"
        )
    if len(lekari) > 8:
        linii.append(f"\n... и уште {len(lekari) - 8}.")
    linii.append(f"\nЗа закажување: рецепција ({_RECEPTCIJA}) или формата за термин на сајтот.")
    return {
        "odgovor": "\n".join(linii),
        # join gi spojuva site linii vo eden string
        "kontekst": _nov_kontekst(oddel, pol),
    }
