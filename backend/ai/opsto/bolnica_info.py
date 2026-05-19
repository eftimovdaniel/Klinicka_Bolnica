"""
Информации за болницата - работно време, локации, контакти.

Овие податоци не се во DB (нема такви табели), па се вчитуваат
од backend/data/bolnica_info.json.

Содржи:
- odgovori_za_rabotno_vreme()  → #12
- odgovori_za_lokacija()       → #13
- odgovori_za_kontakti()       → #14
"""

import json
from pathlib import Path

from ai._kernel.groq_client import ask_ai
from ai._kernel.prompts import ODDEL_EXTRACT_PROMPT

# backend/ai/opsto/bolnica_info.py → три нивоа нагоре = backend/, па data/bolnica_info.json
_JSON_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "bolnica_info.json"


def _zimi_info() -> dict:
    """Вчитај JSON со инфо за болницата."""
    try:
        with open(_JSON_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[bolnica_info] greska pri citanje: {e}")
        return {}


_ODDEL_KLUCNI = (
    ("кардиолог", "Кардиологија"),
    ("гинеколог", "Гинекологија"),
    ("невролог", "Неврологија"),
    ("ортопед", "Ортопедија"),
    ("лаборатор", "Лабораторија"),
    ("радиолог", "Радиологија"),
    ("хирург", "Хирургија"),
    ("педиатр", "Педиатрија"),
    ("онколог", "Онкологија"),
    ("интерна", "Интерна медицина"),
    ("итна", "Итна помош"),
    ("аптека", "Аптека"),
)


def _najdi_oddel_lokalno(prasanje: str, oddeli: list[str]) -> str | None:
    """Правила без AI — кардиологијата → Кардиологија."""
    p = prasanje.lower()
    for kluc, ime in _ODDEL_KLUCNI:
        if kluc in p:
            for o in oddeli:
                if o.lower() == ime.lower() or kluc in o.lower():
                    return o
            if ime in oddeli:
                return ime
    return None


def _najdi_oddel_so_ai(prasanje: str, oddeli: list[str]) -> str | None:
    """
    Прашува AI (Groq) кој оддел е во прашањето.
    Враќа точно име на оддел или None.
    """
    lista_text = "\n".join([f"- {o}" for o in oddeli])
    full_prompt = f"""
Достапни оддели:
{lista_text}

Корисник пишува: „{prasanje}"

Кој оддел е во прашањето? Врати точно име од листата или NONE.
""".strip()

    odgovor = ask_ai(full_prompt, system_prompt=ODDEL_EXTRACT_PROMPT)
    odgovor_cist = odgovor.strip().replace('"', '').replace("'", "").strip()

    if "NONE" in odgovor_cist.upper():
        return None

    # Точно совпаѓање
    for o in oddeli:
        if o.lower() == odgovor_cist.lower():
            return o

    # Делумно совпаѓање
    for o in oddeli:
        if o.lower() in odgovor_cist.lower() or odgovor_cist.lower() in o.lower():
            return o

    return None


def odgovori_za_rabotno_vreme(prasanje: str) -> str:
    """
    #12 - Работно време.
    Ако корисник прашува за конкретен оддел → специфично време.
    Инаку → општо работно време.
    """
    info = _zimi_info()
    rabotno = info.get("rabotno_vreme", {})
    po_oddel = rabotno.get("po_oddel", {})

    # Дали прашува за конкретен оддел?
    oddeli = list(po_oddel.keys())
    izbran_oddel = _najdi_oddel_so_ai(prasanje, oddeli)

    if izbran_oddel:
        vreme = po_oddel.get(izbran_oddel, "—")
        return f"Работно време на {izbran_oddel}:\n\n{vreme}"

    # Општо работно време
    delovi = ["Работно време на Клиничка Болница Штип:", ""]
    delovi.append(rabotno.get("opsto", "—"))
    delovi.append(rabotno.get("vikendi", ""))
    delovi.append("")
    delovi.append("По оддели:")
    for od, vreme in po_oddel.items():
        delovi.append(f"- {od}: {vreme}")

    return "\n".join(delovi)


def odgovori_za_lokacija(prasanje: str) -> str:
    """
    #13 - Локација на оддели во болницата.
    """
    info = _zimi_info()
    lokacii = info.get("lokacii", {})

    if not lokacii:
        return "Нема расположливи податоци за локации."

    oddeli = list(lokacii.keys())
    izbran_oddel = _najdi_oddel_so_ai(prasanje, oddeli)

    if izbran_oddel:
        lokacija = lokacii.get(izbran_oddel, "—")
        return f"Локација на {izbran_oddel}:\n\n{lokacija}"

    # Прикажи сите локации
    delovi = ["Локации на оддели во Клиничка Болница Штип:", ""]
    for od, lok in lokacii.items():
        delovi.append(f"- {od}: {lok}")

    delovi.append("")
    delovi.append(f'Адреса: {info.get("kontakti", {}).get("adresa", "—")}')

    return "\n".join(delovi)


def odgovori_za_kontakti(prasanje: str) -> str:
    """
    #14 - Контакти на болницата.
    """
    info = _zimi_info()
    kontakti = info.get("kontakti", {})

    if not kontakti:
        return "Нема расположливи контакти."

    # Дали прашува за итна?
    prasanje_lower = prasanje.lower()
    if "итн" in prasanje_lower or "ургент" in prasanje_lower or "веднаш" in prasanje_lower:
        return (
            f"Итна помош:\n\n"
            f"Телефон: {kontakti.get('itna', '—')}\n"
            f"Локација: Главна зграда, приземје, главен влез\n"
            f"Достапна: 24 часа, 7 дена во неделата"
        )

    # Сите контакти
    delovi = ["Контакти на Клиничка Болница Штип:", ""]
    if kontakti.get("centrala"):
        delovi.append(f"Централа: {kontakti['centrala']}")
    if kontakti.get("itna"):
        delovi.append(f"Итна помош: {kontakti['itna']}")
    if kontakti.get("informacii"):
        delovi.append(f"Рецепција / информации: {kontakti['informacii']}")
    if kontakti.get("rezervacii"):
        delovi.append(f"Резервации: {kontakti['rezervacii']}")
    if kontakti.get("email"):
        delovi.append(f"Email: {kontakti['email']}")
    if kontakti.get("adresa"):
        delovi.append("")
        delovi.append(f"Адреса: {kontakti['adresa']}")

    return "\n".join(delovi)
