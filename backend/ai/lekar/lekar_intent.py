"""
Детекција: најавен лекар бара свој распоред/термини или UI панел.
Едно место — без дуплирани листи низ ai_chat / intent_detector.
"""
import re

from ai._kernel.transliteracija import transliterijaj

_RE_SHOW = re.compile(
    r"\b(прикажи|покажи|прикази|prikazi|pokazi|отвори|otvori|листа|list|види|vidi)\w*",
    re.UNICODE | re.IGNORECASE,
)
_RE_SCHED = re.compile(
    r"\b(термин\w*|pregled\w*|преглед\w*|raspored\w*|распоред\w*)\b",
    re.UNICODE | re.IGNORECASE,
)
_RE_HAVE = re.compile(
    r"\b(дали\s+имам|имам\s+ли|што\s+имам|кои\s+(се\s+)?моите)\b",
    re.UNICODE | re.IGNORECASE,
)
_RE_MINE = re.compile(
    r"\b(мој\w*|моите|закажан\w*|следн\w*|идн\w*)\b",
    re.UNICODE | re.IGNORECASE,
)
_RE_DR = re.compile(
    r"\b(д-р|др\.?|доктор)\s+[a-zа-яёіїјљњћџ]",
    re.UNICODE | re.IGNORECASE,
)
_RE_KAJ = re.compile(
    r"\b(кај|kaj)\s+[a-zа-яёіїјљњћџ]{3,}",
    re.UNICODE | re.IGNORECASE,
)
_RE_SLOBODEN = re.compile(
    r"\b(слободн|slobodn)\w*\s+(термин|pregled)",
    re.UNICODE | re.IGNORECASE,
)
_RE_DATUM = re.compile(
    r"(?:преглед|термин)\w*\s+(?:за|на)\s+\d",
    re.UNICODE | re.IGNORECASE,
)
_RE_PAC_PANEL = re.compile(r"преглед\s+на\s+пациент", re.UNICODE | re.IGNORECASE)
_RE_UI = re.compile(
    r"\b(панел|panel|таб|tab|dashboard|дашборд|на\s+екран|на\s+сајт)",
    re.UNICODE | re.IGNORECASE,
)


def _p(prasanje: str) -> str:
    return transliterijaj(prasanje or "").lower()


def prasanje_e_moj_raspored_lekar(prasanje: str) -> bool:
    """Лекар: мои термини/прегледи/распоред (не info_lekar за друго име)."""
    p = _p(prasanje)
    if _RE_SLOBODEN.search(p) or _RE_DR.search(p) or _RE_KAJ.search(p):
        return False
    if _RE_DATUM.search(p):
        return True
    if _RE_HAVE.search(p) and _RE_SCHED.search(p):
        return True
    if _RE_SHOW.search(p) and _RE_SCHED.search(p):
        return True
    if _RE_MINE.search(p) and _RE_SCHED.search(p):
        return True
    return False


def prasanje_bara_lekar_panel(prasanje: str) -> bool:
    """Отвори таб на dashboard (пациенти, распоред, …)."""
    if prasanje_e_moj_raspored_lekar(prasanje):
        return True
    p = _p(prasanje)
    if _RE_UI.search(p):
        return True
    return bool(_RE_PAC_PANEL.search(p) and _RE_SHOW.search(p))
