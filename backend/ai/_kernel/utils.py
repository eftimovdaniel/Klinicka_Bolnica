"""Заеднички формати за AI handler-и (време, датум, …)."""

from typing import Any

# Mapiranje na angliski kratenki na denovi vo makedonski
_DEN_KRATKO = {
    "Mon": "пон",
    "Tue": "вто",
    "Wed": "сре",
    "Thu": "чет",
    "Fri": "пет",
    "Sat": "саб",
    "Sun": "нед",
}


def format_vreme(v: Any) -> str:
    """time / timedelta / string → HH:MM."""
    if v is None:
        return "—"
    # Em dash kako placeholder za prazna vrednost
    if hasattr(v, "strftime"):
        return v.strftime("%H:%M")
        # time/datetime imaat strftime - format HH:MM
    if hasattr(v, "total_seconds"):
        s = int(v.total_seconds())
        return f"{s // 3600:02d}:{(s % 3600) // 60:02d}"
        # timedelta - rachno presmetuvanje na chasovi i minuti
    return str(v)[:5]
    # Fallback: prvite 5 znaci (HH:MM od HH:MM:SS string)


def format_datum(d: Any) -> str:
    """date / datetime / string → DD.MM.YYYY."""
    if not d:
        return "—"
    if hasattr(d, "strftime"):
        return d.strftime("%d.%m.%Y")
        # Makedonski format DD.MM.YYYY (ne ISO)
    s = str(d)
    return s[:10] if len(s) >= 10 else s
    # Fallback: prvi 10 znaci ako e string (YYYY-MM-DD ima 10 znaci)


def format_datum_so_den(d: Any) -> str:
    """date → DD.MM.YYYY (пон) — за распоред на лекар."""
    if not d:
        return "—"
    if hasattr(d, "strftime"):
        s = d.strftime("%d.%m.%Y (%a)")
        # %a vrakja angliski (Mon, Tue...) - zatoa ja zameni so makedonski
        for en, mk in _DEN_KRATKO.items():
            s = s.replace(en, mk)
        return s
    return str(d)


def format_datum_vreme(d: Any) -> str:
    """datetime → DD.MM.YYYY HH:MM (пријава на работа, итн.)."""
    if not d:
        return "—"
    if hasattr(d, "strftime"):
        return d.strftime("%d.%m.%Y %H:%M")
    return str(d)[:16]
    # Prvi 16 znaci za "YYYY-MM-DD HH:MM" string


def format_datum_i_vreme(d: Any, t: Any) -> str:
    """date + time → „15.05.2026 14:30“."""
    if hasattr(d, "strftime"):
        d_s = d.strftime("%d.%m.%Y")
    else:
        d_s = str(d)
    return f"{d_s} {format_vreme(t)}"
    # Sostavuva go datumot i vremeto so prazno mesto megju
