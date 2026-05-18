"""
Отворање на постоечки табови во лекарскиот dashboard (frontend).

Користи navigacija.target = „lekar:pacienti" и слично; script.js → kbsOtvoriLekarPanel.
"""

from ai._kernel.auth import require_lekar
from ai._kernel.transliteracija import transliterijaj

TAB_LABELS = {
    "pacienti": "Преглед на пациенти",
    "dezurstva": "Распоред на дежурства",
    "aparati": "Закажи термин на апарат",
    "postavki": "Поставки",
}


def _p(prasanje: str) -> str:
    return transliterijaj(prasanje).lower()


def odredi_lekar_tab(prasanje: str) -> str:
    """Кој таб да се отвори (default: pacienti)."""
    p = _p(prasanje)
    if any(
        x in p
        for x in (
            "дежур",
            "dezur",
            "дежурств",
        )
    ) and not any(
        x in p
        for x in (
            "преглед на пациент",
            "термин",
            "termin",
            "пациент",
            "pacient",
            "закажан",
        )
    ):
        return "dezurstva"
    if any(
        x in p
        for x in (
            "апарат",
            "aparat",
            "мрт",
            "кт",
            "рентген",
            "сонограф",
            "узи",
        )
    ):
        return "aparati"
    if any(x in p for x in ("поставк", "postavk", "лозинк", "профил")):
        return "postavki"
    return "pacienti"


from ai.lekar.lekar_intent import prasanje_bara_lekar_panel  # noqa: F401 — re-export


def navigacija_za_tab(
    tab: str,
    *,
    termini_mode: str | None = None,
    datum: str | None = None,
) -> dict:
    label = TAB_LABELS.get(tab, tab)
    nav: dict = {
        "target": f"lekar:{tab}",
        "tab": tab,
        "label": label,
    }
    if termini_mode:
        nav["termini_mode"] = termini_mode
    if datum:
        nav["datum"] = datum
    return nav


def dopuni_so_lekar_panel(
    rezultat: str | dict,
    *,
    tab: str = "pacienti",
    termini_mode: str | None = None,
    datum: str | None = None,
    dodaj_napomena: bool = True,
) -> dict:
    """Додава navigacija + akcija за отворање на лекарскиот dashboard."""
    nav = navigacija_za_tab(tab, termini_mode=termini_mode, datum=datum)
    label = TAB_LABELS.get(tab, tab)

    if isinstance(rezultat, dict):
        odgovor = (rezultat.get("odgovor") or "").strip()
        out: dict = {
            "odgovor": odgovor,
            "navigacija": nav,
            "akcija": "otvori_lekar_panel",
        }
        if rezultat.get("kontekst") is not None:
            out["kontekst"] = rezultat["kontekst"]
        if dodaj_napomena and odgovor:
            out["odgovor"] = (
                odgovor + f"\n\nЛистата е прикажана на табот «{label}»."
            )
        elif not odgovor:
            out["odgovor"] = f"Го отворам табот «{label}» на вашиот панел."
        return out

    tekst = (rezultat or "").strip()
    if dodaj_napomena and tekst:
        tekst = tekst + f"\n\nЛистата е прикажана на табот «{label}»."
    elif not tekst:
        tekst = f"Го отворам табот «{label}» на вашиот панел."
    return {
        "odgovor": tekst,
        "navigacija": nav,
        "akcija": "otvori_lekar_panel",
    }


def odgovori_za_otvori_lekar_panel(
    prasanje: str,
    lekar: dict | None,
    kontekst: dict | None = None,
) -> dict:
    """Само отворање на таб (без листа во чат), кога корисникот бара панел."""
    if err := require_lekar(lekar):
        return {
            "odgovor": (
                f"{err}\n\n"
                "Најавете се како лекар преку «Најава за лекар» на сајтот."
            ),
            "akcija": "otvori_lekar_login",
        }

    tab = odredi_lekar_tab(prasanje)
    termini_mode = None
    datum = None

    if tab == "pacienti":
        try:
            from ai.pacient.moi_pregledi import datum_za_pregledi_od_prasanje

            d = datum_za_pregledi_od_prasanje(prasanje)
            if d:
                datum = d.strftime("%Y-%m-%d")
                termini_mode = "date"
            elif any(x in _p(prasanje) for x in ("сите", "site", "комплетн")):
                termini_mode = "all"
            else:
                termini_mode = "all"
        except ImportError:
            termini_mode = "all"

    label = TAB_LABELS.get(tab, tab)
    return dopuni_so_lekar_panel(
        f"Го отворам табот «{label}» на вашиот панел.",
        tab=tab,
        termini_mode=termini_mode,
        datum=datum,
        dodaj_napomena=False,
    )
