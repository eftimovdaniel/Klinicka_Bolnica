"""Заеднички контекст за преглед/промена на дежурства во AI разговор."""

from datetime import date, datetime


def izgradи_kontekst(found: dict, dez: dict | None) -> dict:
    datum = dez.get("datum") if dez else None
    if isinstance(datum, datetime):
        datum = datum.date()
    datum_s = datum.isoformat() if isinstance(datum, date) else None

    dez_id = dez.get("dezurstvo_ID") if dez else None
    vreme_od = _fmt(dez.get("vreme_od")) if dez else None
    vreme_do = _fmt(dez.get("vreme_do")) if dez else None

    return {
        "intent": "promeni_dezurstvo",
        "dezurstvo_kontekst": {
            "doctor_id": found["doctor_ID"],
            "name": found["name"],
            "surname": found["surname"],
            "dezurstvo_id": dez_id,
            "datum": datum_s,
            "vreme_od": vreme_od,
            "vreme_do": vreme_do,
        },
    }


def lekar_od_kontekst(kontekst: dict | None) -> dict | None:
    if not kontekst:
        return None
    dk = kontekst.get("dezurstvo_kontekst")
    if not dk or not dk.get("doctor_id"):
        return None
    return {
        "doctor_ID": dk["doctor_id"],
        "name": dk.get("name", ""),
        "surname": dk.get("surname", ""),
        "specialty": dk.get("specialty"),
    }


def _fmt(t) -> str | None:
    if t is None:
        return None
    if hasattr(t, "strftime"):
        return t.strftime("%H:%M")
    s = str(t)
    return s[:5] if len(s) >= 5 else s
