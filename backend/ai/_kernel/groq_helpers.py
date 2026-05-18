"""
Заеднички помошници за Groq — intent, JSON извлекување, проверка на грешки.
"""

from __future__ import annotations

from ai._kernel.ai_json import parse_ai_json
from ai._kernel.groq_client import ask_ai, groq_e_isklucen

# Интенти што keyword детекторот ги дава доволно точно — не трошиме Groq повторно
_INTENTI_KLUCNI_BEZ_GROQ = frozenset(
    {
        "zakazi_termin",
        "otkazi_termin",
        "prenesi_termin",
        "postavi_potsetnik",
        "prenesi_termin",
        "postavi_potsetnik",
        "oceni_pregled",
        "trgni_ocena",
        "zavrshi_pregled",
        "izbrisi_vest_oglas",
        "objavi_vest",
        "kreiraj_oglas",
        "zatvori_oglas",
        "promeni_dezurstvo",
        "pregled_dezurstvo",
        "otvori_admin_panel",
        "aplikanti_oglas",
        "apliciraj_za_rabota",
        "preference_lekar",
        "moi_pregledi",
        "moj_raspored",
        "otvori_lekar_panel",
        "lekari_oddel",
        "slobodni_termini",
        "info_lekar",
    }
)


def izvlechi_json_so_ai(
    prasanje: str,
    system_prompt: str,
    *,
    log_tag: str = "groq_json",
    user_prefix: str = "",
) -> dict:
    """Groq → JSON dict; при грешка/429 → {"_error": "..."}."""
    user = f"{user_prefix}{prasanje}".strip() if user_prefix else prasanje
    raw = ask_ai(user, system_prompt=system_prompt)
    print(f"[{log_tag}] AI raw: {raw!r}")
    return parse_ai_json(raw, log_tag=log_tag)


def intent_so_groq_augment(prasanje: str, keyword_intent: str | None) -> str:
    """
    Keyword прво; Groq кога е нејасно (general, info_lekar) или нема keyword match.
    """
    from ai._kernel.ai_intent_detector import detektiraj_intent_so_ai

    kw = (keyword_intent or "").strip().lower() or None
    if groq_e_isklucen():
        return kw or "general"
    if kw and kw in _INTENTI_KLUCNI_BEZ_GROQ:
        return kw
    # Доверба на keyword за познати интенти (распоред, оддел, слободни, …)
    if kw and kw not in ("general", "info_lekar"):
        return kw

    try:
        ai_intent = detektiraj_intent_so_ai(prasanje)
    except Exception as e:
        print(f"[groq_helpers] intent AI greska: {e}")
        ai_intent = None

    if ai_intent and ai_intent != "general":
        return ai_intent
    return kw or "general"
