from ai._kernel.auth import require_direktor, require_lekar
from ai._kernel.transliteracija import transliterijaj

def _baranje_e_prikazi_dezurstvo_vo_admin(prasanje: str) -> bool:
    """„Прикажи го во админ" по преглед на дежурство."""
    p = transliterijaj(prasanje).lower()
    ima_admin = any(
        x in p
        for x in (
            "админ","административ","admin","панел",)
    )
    if not ima_admin:
        return False
    return any(
        x in p
        for x in (
            "го ",
            " го",
            "неа",
            "тоа",
            "ова",
            "дежур",
            "dezur",
            "прикажи",
            "prikazi",
            "види",
        )
    )


def _odredi_subtab(prasanje: str) -> str:
    p = transliterijaj(prasanje).lower()
    if any(x in p for x in ("оглас", "огласи", "kariera", "oglas", "вработување")):
        return "oglasi-admin"
    if any(x in p for x in ("новост", "новости", "вест", "vesti")):
        return "novosti-admin"
    if "статистик" in p and any(x in p for x in ("оцен", "ocena", "рејтинг")):
        return "statistika-prosek-ocena-admin"
    if "статистик" in p or "оптовар" in p:
        return "statistika-optovaruvanje-admin"
    if any(x in p for x in ("дежур", "dezur")):
        return "dezurstva-admin"
    return "dezurstva-admin"


def odgovori_za_otvori_admin(
    prasanje: str,
    lekar: dict | None,
    kontekst: dict | None = None,
) -> dict:
    if err := require_lekar(lekar):
        return {
            "odgovor": (
                "За административниот панел треба да сте најавени како лекар (директор).\n"
                "Најавете се преку «Најава за лекар» на сајтот."
            ),
            "akcija": "otvori_lekar_login",
        }

    if err := require_direktor(lekar):
        return {
            "odgovor": (
                f"{err}\n\n"
                "Административниот панел е достапен само за директорот на болницата."
            ),
        }

    subtab = _odredi_subtab(prasanje)
    labels = {
        "dezurstva-admin": "Управување со дежурства",
        "oglasi-admin": "Управување со огласи",
        "novosti-admin": "Новости",
        "statistika-optovaruvanje-admin": "Статистика – оптовареност",
        "statistika-prosek-ocena-admin": "Просечна оцена – лекари",
    }
    label = labels.get(subtab, "Администрација")

    navigacija: dict = {
        "target": "lekar:admin",
        "subtab": subtab,
        "label": label,
    }
    odgovor_extra = ""

    dk = (kontekst or {}).get("dezurstvo_kontekst") if kontekst else None
    if dk and subtab == "dezurstva-admin" and _baranje_e_prikazi_dezurstvo_vo_admin(prasanje):
        if dk.get("doctor_id"):
            navigacija["doctor_id"] = dk["doctor_id"]
        if dk.get("datum"):
            navigacija["datum"] = dk["datum"]
        if dk.get("dezurstvo_id"):
            navigacija["dezurstvo_id"] = dk["dezurstvo_id"]
        ime = f"{dk.get('name', '')} {dk.get('surname', '')}".strip()
        if ime:
            navigacija["doctor_name"] = ime
        if dk.get("datum"):
            odgovor_extra = (
                f"\nГо филтрирам според разговорот: {ime or 'лекарот'}, "
                f"датум {dk['datum']}."
            )

    return {
        "odgovor": (
            f"Го отворам административниот панел — «{label}».{odgovor_extra}"
        ),
        "navigacija": navigacija,
        "akcija": "otvori_admin_panel",
        "kontekst": kontekst,
    }
