"""
Заеднички помошници за Groq — intent, JSON извлекување.
Без keyword/локални fallback патеки (AI-only).
"""

from __future__ import annotations

from ai._kernel.ai_json import parse_ai_json
from ai._kernel.groq_client import GROQ_OFFLINE_MSG, ask_ai, groq_e_isklucen


def groq_zadolzhitelen() -> str | None:
    """None ако Groq е достапен; инаку порака за корисник."""
    if groq_e_isklucen():
        return GROQ_OFFLINE_MSG
    return None
    # None znachi: vse e OK, mozhe da se prodolzhi so AI povik


def izvlechi_json_so_ai(
    prasanje: str,
    system_prompt: str,
    *,
    log_tag: str = "groq_json",
    user_prefix: str = "",
) -> dict:
    """Groq → JSON dict; при грешка/429 → {"_error": "..."}."""
    if msg := groq_zadolzhitelen():
        return {"_error": msg}
    # Walrus operator - dodeli i proveri vo edna linija
    user = f"{user_prefix}{prasanje}".strip() if user_prefix else prasanje
    # Opcionalen prefix za dodatni instrukcii pred prasanjeto
    raw = ask_ai(user, system_prompt=system_prompt)
    print(f"[{log_tag}] AI raw: {raw!r}")
    # Log za debug - vidi shto tochno AI vrakja
    return parse_ai_json(raw, log_tag=log_tag)
    # Centralizirana JSON parser - cisti markdown fences, vrakja dict


def detektiraj_intent_ai_only(prasanje: str) -> str:
    """Главна klasifikacija na intent — AI so high-confidence keyword pre-filter."""
    from ai._kernel.ai_intent_detector import detektiraj_intent_so_ai
    from ai._kernel.transliteracija import transliterijaj
    # Lazy import - izbegnuva ciklichni zavisnosti

    if not (prasanje or "").strip():
        return "general"
    # Prazno prasanje - generichen intent

    # High-confidence keyword pre-filter: raboti za chesti frazi kade AI gresi
    # (npr. „дали има отворени работни позиции" AI go praka vo „uslugi")
    p = transliterijaj(prasanje).lower()
    # Normalizacija - kirilica vo latinica, mali bukvi
    ima_kreiraj = any(
        k in p
        for k in (
            "креирај", "kreiraj",
            "објави", "objavi",
            "стави оглас", "stavi oglas",
            "нов оглас", "nov oglas",
            "напиши", "napishi",
            "направи", "napravi",
            "сакам да објавам", "сакам да креирам",
        )
    )
    # Proverka dali korisnikot saka da kreira oglas (admin akcija)
    if not ima_kreiraj and any(
        k in p
        for k in (
            "кариер", "kariera",
            "вработувањ", "вработување", "vrabotuvanje", "vrabotuvanj",
            "слободни позиции", "слободни работни", "работни места", "работна позиција",
            "работни позиции", "rabotni pozicii", "rabotna pozicija",
        )
    ):
        return "navigacija"
        # Ako ne sak kreira a pituva za pozicii - go upatuva na stranata

    # Specijalen slucaj: „позиции" + („отворени/слободни/активни/нови/достапни")
    if not ima_kreiraj and "позиц" in p and any(
        w in p for w in ("отвор", "слобод", "актив", "работн", "нови ", "достапн")
    ):
        return "navigacija"

    # Zavrshi/zatvori pregled (lekar) - mora PRED apliciraj proverki bidejki
    # "затвори ја пријавата на X со терапија" AI go prepoznava kako apliciraj
    # poradi zborot "пријава", iako kontekstot e jasno medicinski (терапија/дијагноза)
    try:
        from ai.lekar.zavrshi_pregled import prasanje_e_zavrshi_pregled

        if prasanje_e_zavrshi_pregled(prasanje):
            return "zavrshi_pregled"
            # High-confidence rule-based detekcija - po-vredna od AI klasifikacija
    except ImportError:
        pass
        # Ako modulot ne e dostapen - prodolzhi normalno

    # Izbrisi vest/oglas - rule-based pre-filter za da ne se padne na "general"
    # koga Groq e preopovaren (inache "избриши ја последната вест" vrakja "Среќно!")
    try:
        from ai.opsto.vest_naslov import prasanje_e_izbrisi_vest_oglas

        if prasanje_e_izbrisi_vest_oglas(prasanje, None):
            return "izbrisi_vest_oglas"
            # Sigurno detektirano - "избриши" + "вест/оглас/последна/најнова"
    except ImportError:
        pass

    # Zapishi terapija/dijagnoza (lekar) - „терапија: X" / „дијагноза: X" bez
    # zbor za zatvoranje. AI ne treba da ja gleda kako apliciraj_za_rabota.
    try:
        from ai._kernel.transliteracija import transliterijaj as _tr
        _p_low = _tr(prasanje).lower()
        ima_dx_tx_kluc = bool(
            __import__("re").search(
                r"(дијагноз|dijagnoz|терапиј|terapij)\s*:",
                _p_low,
            )
        )
        # Ako ima kluchen zbor `дијагноза:` ili `терапија:` -> medicinski kontekst
        if ima_dx_tx_kluc and any(
            w in _p_low for w in ("терапи", "terapi", "дијагноз", "dijagnoz")
        ):
            from ai.lekar.zavrshi_pregled import prasanje_e_zavrshi_pregled as _pez
            if _pez(prasanje):
                return "zavrshi_pregled"
                # Ako vleguva i vo zavrshi_pregled - imame i akcija (затвори/заврши)
            return "zapishi_terapija"
            # Inaku - samo zapishuvanje na terapija/dijagnoza
    except ImportError:
        pass

    # Brisenje/otkazuvanje na aplikacija za rabota (pacient)
    # „избриши/откажи го мојата апликација", „izbrisi ja aplikacijata"
    try:
        from ai.pacient.apliciraj_za_rabota import (
            prasanje_e_izbrisi_aplikacija_rabota,
            prasanje_e_proverka_aplikacija_rabota,
        )

        if prasanje_e_izbrisi_aplikacija_rabota(prasanje):
            return "apliciraj_za_rabota"
        if prasanje_e_proverka_aplikacija_rabota(prasanje):
            return "apliciraj_za_rabota"
    except ImportError:
        pass
        # Ako modulot ne e dostapen - prodolzhi normalno

    if msg := groq_zadolzhitelen():
        print(f"[groq_helpers] intent blocked: {msg}")
        return "general"
        # Bez AI ne mozhe da klasificira - opshti odgovor
    return detektiraj_intent_so_ai(prasanje)
    # Glavna AI klasifikacija
