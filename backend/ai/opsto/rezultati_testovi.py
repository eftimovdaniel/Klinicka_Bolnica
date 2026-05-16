"""
Статус на резултати од тестови — кога се готови извештаите.

Хибрид: правила по тип тест + AI извлекување (tip_test, datum).
"""

from datetime import date

from ai._kernel.ai_json import parse_ai_json
from ai._kernel.groq_client import ask_ai
from ai._kernel.prompt_loader import load_prompt
from ai._kernel.prompt_helpers import today_prompt_line
from ai._kernel.transliteracija import transliterijaj

_ROKOVI = (
    ("mri", "МРТ / MRI", "обично за 3–7 работни дена"),
    ("кт", "КТ", "обично за 2–5 работни дена"),
    ("крв", "крвна слика / лабораторија", "обично за 1–2 работни дена"),
    ("лаборатор", "лабораториски испитувања", "обично за 1–2 работни дена"),
    ("ехо", "ехо / ултразвук", "често истиот ден или за 2–3 часа"),
    ("уз", "уз / ултразвук", "често истиот ден или за 2–3 часа"),
    ("ultrazvuk", "уз / ултразвук", "често истиот ден или за 2–3 часа"),
    ("екг", "ЕКГ", "често веднаш или истиот ден"),
    ("рентген", "рентген", "често истиот ден"),
    ("биопси", "биопсија", "обично за 5–10 работни дена (зависи од тип)"),
)


def _izvlechi(prashanje: str) -> dict:
    full = f"{today_prompt_line()}\n\nКорисник: {prashanje!r}\n\nИзвлечи податоци."
    odgovor = ask_ai(full, system_prompt=load_prompt("rezultati_testovi_extract"))
    return parse_ai_json(odgovor, log_tag="rezultati_testovi")


def _rok_od_tip(tip: str | None) -> tuple[str, str]:
    p = transliterijaj(tip or "").lower()
    if not p:
        return "испитување", "рокот зависи од типот на тест. Рецепција (032/ 605-001) или лабораторијата имаат точен датум."
    for kluc, label, rok in _ROKOVI:
        if kluc in p:
            return label, rok
    return tip.strip(), "обично за 1–3 работни дена; за точен датум — рецепција (032/ 605-001) или вашиот лекар."


def odgovori_za_rezultati(prashanje: str) -> str:
    pod = _izvlechi(prashanje)
    tip = (pod.get("tip_test") or "").strip() or None
    label, rok = _rok_od_tip(tip)

    if not tip:
        p = transliterijaj(prashanje).lower()
        for kluc, lbl, r in _ROKOVI:
            if kluc in p:
                label, rok = lbl, r
                break

    datum_txt = ""
    if pod.get("datum_testa"):
        datum_txt = f" Тестот е направен на {pod['datum_testa']}."

    return (
        f"За {label},{datum_txt} резултатите се {rok}.\n"
        "Точен статус и подигнување: рецепција (032/ 605-001) или лекарот што ве упати.\n"
        "За онлајн пристап — прашајте на рецепција дали е достапно за вашиот случај."
    )
