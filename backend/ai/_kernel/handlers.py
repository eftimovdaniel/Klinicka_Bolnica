"""
Регистар на AI интенти → handler функции.
Едно место за рутирање; ai_chat.py само детектира интент и повикува dispatch().

Агентски модел: intent → handler (def) → правила/база → понекогаш AI од листа.
Водич: ai._kernel.agent_guidelines
"""

from dataclasses import dataclass
from typing import Any, Callable
from ai._kernel.groq_client import ask_ai


@dataclass(frozen=True)
class AiContext:
    pitanje: str
    pitanje_norm: str
    pacient: dict | None
    lekar: dict | None
    kontekst: dict | None
@dataclass(frozen=True)
class HandlerSpec:
    fn: Callable[..., Any]
    use_raw_question: bool = False
    kind: str = "str"  # str | dict | dict_nav | dict_full
def _build_handlers() -> dict[str, HandlerSpec]:
    from ai import (
        apliciraj_za_rabota,
        aplikanti_oglas,
        bolnica_info,
        faq_pregled,
        preference_lekar,
        rezultati_testovi,
        info_lekar,
        istorija_pacient,
        izbrisi_vest_oglas,
        izvestaj_den_nedela,
        karton_pacient,
        kreiraj_oglas,
        lekari_oddel,
        moj_raspored,
        moja_statistika,
        moi_pregledi,
        navigacija,
        novosti_rezime,
        objavi_vest,
        oceni_pregled,
        otkazi_termin,
        postavi_potsetnik,
        prenesi_termin,
        preporaka_lekar,
        pregled_dezurstvo,
        promeni_dezurstvo,
        otvori_admin_panel,
        slobodni_termini,
        statistika_oddeli,
        trgni_ocena,
        uslugi,
        zatvori_oglas,
        zapishi_terapija,
        zakazi_termin,
        zavrshi_pregled,
    )

    return {
        "slobodni_termini": HandlerSpec(slobodni_termini.odgovori_za_slobodni_termini, kind="dict"),
        "zakazi_termin": HandlerSpec(zakazi_termin.odgovori_za_zakazuvanje, kind="dict_full"),
        "otkazi_termin": HandlerSpec(otkazi_termin.odgovori_za_otkazuvanje),
        "prenesi_termin": HandlerSpec(prenesi_termin.odgovori_za_prenesuvanje),
        "postavi_potsetnik": HandlerSpec(postavi_potsetnik.odgovori_za_potsetnik),
        "oceni_pregled": HandlerSpec(oceni_pregled.odgovori_za_ocenuvanje),
        "trgni_ocena": HandlerSpec(trgni_ocena.odgovori_za_trgni_ocena),
        "info_lekar": HandlerSpec(info_lekar.odgovori_za_info_lekar, kind="dict"),
        "preporaka_lekar": HandlerSpec(preporaka_lekar.odgovori_za_preporaka),
        "rabotno_vreme": HandlerSpec(bolnica_info.odgovori_za_rabotno_vreme),
        "lokacija": HandlerSpec(bolnica_info.odgovori_za_lokacija),
        "kontakti": HandlerSpec(bolnica_info.odgovori_za_kontakti),
        "uslugi": HandlerSpec(uslugi.odgovori_za_uslugi),
        "objavi_vest": HandlerSpec(objavi_vest.odgovori_za_objava_vest, use_raw_question=True),
        "kreiraj_oglas": HandlerSpec(kreiraj_oglas.odgovori_za_kreiranje_oglas),
        "izbrisi_vest_oglas": HandlerSpec(izbrisi_vest_oglas.odgovori_za_brisenje),
        "zatvori_oglas": HandlerSpec(zatvori_oglas.odgovori_za_zatvoranje_oglas),
        "pregled_dezurstvo": HandlerSpec(
            pregled_dezurstvo.odgovori_za_pregled_dezurstvo, kind="dict"
        ),
        "promeni_dezurstvo": HandlerSpec(
            promeni_dezurstvo.odgovori_za_dezurstvo, kind="dict"
        ),
        "otvori_admin_panel": HandlerSpec(
            otvori_admin_panel.odgovori_za_otvori_admin, kind="dict_full"
        ),
        "statistika_oddeli": HandlerSpec(statistika_oddeli.odgovori_za_statistika),
        "zavrshi_pregled": HandlerSpec(zavrshi_pregled.odgovori_za_zavrshi),
        "istorija_pacient": HandlerSpec(istorija_pacient.odgovori_za_istorija),
        "karton_pacient": HandlerSpec(karton_pacient.odgovori_za_karton),
        "moja_statistika": HandlerSpec(moja_statistika.odgovori_za_moja_statistika),
        "moj_raspored": HandlerSpec(moj_raspored.odgovori_za_raspored, kind="dict"),
        "navigacija": HandlerSpec(navigacija.odgovori_za_navigacija, kind="dict_nav"),
        "lekari_oddel": HandlerSpec(lekari_oddel.odgovori_za_lekari_oddel, kind="dict_nav"),
        "apliciraj_za_rabota": HandlerSpec(apliciraj_za_rabota.odgovori_za_aplikacija, kind="dict_full"),
        "moi_pregledi": HandlerSpec(moi_pregledi.odgovori_za_moi_pregledi),
        "aplikanti_oglas": HandlerSpec(aplikanti_oglas.odgovori_za_aplikanti),
        "zapishi_terapija": HandlerSpec(zapishi_terapija.odgovori_za_terapija),
        "novosti_rezime": HandlerSpec(novosti_rezime.odgovori_za_novosti_rezime, kind="none"),
        "faq_pregled": HandlerSpec(faq_pregled.odgovori_za_faq_pregled),
        "rezultati_testovi": HandlerSpec(rezultati_testovi.odgovori_za_rezultati),
        "preference_lekar": HandlerSpec(
            preference_lekar.odgovori_za_preference, kind="dict"
        ),
        "izvestaj_den_nedela": HandlerSpec(izvestaj_den_nedela.odgovori_za_izvestaj),
    }


_HANDLERS: dict[str, HandlerSpec] | None = None


def get_handlers() -> dict[str, HandlerSpec]:
    global _HANDLERS
    if _HANDLERS is None:
        _HANDLERS = _build_handlers()
    return _HANDLERS


def dispatch(intent: str, ctx: AiContext) -> dict[str, Any]:
    """
    Враќа {"odgovor", "kontekst"?, "navigacija"?, "akcija"?} — ист формат како ai_chat.
    """
    handlers = get_handlers()
    spec = handlers.get(intent)

    if spec is None:
        from ai._kernel.intent_detector import _prasanje_e_asistent_opsto
        from ai._kernel.transliteracija import transliterijaj
        from ai.opsto.asistent_opsto import odgovori_za_asistent_opsto

        if _prasanje_e_asistent_opsto(transliterijaj(ctx.pitanje_norm).lower()):
            return {"odgovor": odgovori_za_asistent_opsto(ctx.pitanje_norm)}
        return {"odgovor": ask_ai(ctx.pitanje_norm)}

    q = ctx.pitanje if spec.use_raw_question else ctx.pitanje_norm

    if spec.kind == "none":
        raw = spec.fn()
    elif intent in ("slobodni_termini", "lekari_oddel"):
        raw = spec.fn(q, ctx.kontekst)
    elif intent == "otvori_admin_panel":
        raw = spec.fn(q, ctx.lekar, ctx.kontekst)
    elif intent in (
        "zakazi_termin",
        "apliciraj_za_rabota",
    ):
        raw = spec.fn(q, ctx.pacient, ctx.kontekst)
    elif intent == "otkazi_termin":
        raw = spec.fn(q, ctx.pacient, ctx.kontekst)
    elif intent in (
        "prenesi_termin",
        "postavi_potsetnik",
        "oceni_pregled",
        "trgni_ocena",
    ):
        raw = spec.fn(q, ctx.pacient)
    elif intent == "moi_pregledi":
        raw = spec.fn(q, ctx.pacient, ctx.lekar)
    elif intent in ("info_lekar", "preference_lekar"):
        raw = spec.fn(q, ctx.kontekst)
    elif intent in ("pregled_dezurstvo", "promeni_dezurstvo"):
        raw = spec.fn(q, ctx.lekar, ctx.kontekst)
    elif intent in ("moj_raspored", "zavrshi_pregled"):
        raw = spec.fn(q, ctx.lekar, ctx.kontekst)
    elif intent in (
        "objavi_vest",
        "kreiraj_oglas",
        "izbrisi_vest_oglas",
        "zatvori_oglas",
        "statistika_oddeli",
        "istorija_pacient",
        "karton_pacient",
        "moja_statistika",
        "aplikanti_oglas",
        "zapishi_terapija",
        "izvestaj_den_nedela",
    ):
        raw = spec.fn(q, ctx.lekar)
    else:
        raw = spec.fn(q)

    out: dict[str, Any] = {"odgovor": "", "kontekst": None}

    if spec.kind == "dict":
        if isinstance(raw, dict):
            out["odgovor"] = raw.get("odgovor", "")
            if raw.get("kontekst") is not None:
                out["kontekst"] = raw.get("kontekst")
            elif ctx.kontekst:
                out["kontekst"] = ctx.kontekst
            if raw.get("akcija"):
                out["akcija"] = raw["akcija"]
        else:
            out["odgovor"] = raw or ""
            if ctx.kontekst and intent == "info_lekar":
                out["kontekst"] = ctx.kontekst

    elif spec.kind == "dict_full":
        if isinstance(raw, dict):
            out["odgovor"] = raw.get("odgovor", "")
            out["kontekst"] = raw.get("kontekst")
            if raw.get("navigacija"):
                out["navigacija"] = raw["navigacija"]
            if raw.get("akcija"):
                out["akcija"] = raw["akcija"]
            elif intent == "zakazi_termin" and ctx.kontekst and ctx.kontekst.get("zakazi_od_slobodni"):
                if "kontekst" not in raw:
                    out["kontekst"] = ctx.kontekst
        else:
            out["odgovor"] = raw or ""
            if intent == "zakazi_termin" and ctx.kontekst and ctx.kontekst.get("zakazi_od_slobodni"):
                out["kontekst"] = ctx.kontekst

    elif spec.kind == "dict_nav":
        if isinstance(raw, dict):
            out["odgovor"] = raw.get("odgovor", "")
            if raw.get("navigacija"):
                out["navigacija"] = raw["navigacija"]
            if raw.get("kontekst") is not None:
                out["kontekst"] = raw.get("kontekst")
            elif ctx.kontekst:
                out["kontekst"] = ctx.kontekst
        else:
            out["odgovor"] = raw or ""

    else:
        out["odgovor"] = raw if isinstance(raw, str) else str(raw or "")

    return out
