"""
Навигација преку AI - пренасочи го корисникот до одредена секција на сајтот.

Примери:
- „Дај ми ги сите лекари во болницата"     → #lekari
- „Покажи ми ги услугите"                  → #uslugi
- „Каде е контакт?"                        → #kontakt
- „Прикажи ми кариера"                     → #kariera
- „Однеси ме на новости"                   → novosti.html
"""

import json
import re

from ai._kernel.groq_client import ask_ai


# Сите достапни „дестинации". Frontend ги мапира на href/scroll.
DESTINACII = {
    "lekari":   {"label": "Лекари",   "target": "index.html#lekari"},
    "uslugi":   {"label": "Услуги",   "target": "index.html#uslugi"},
    "kontakt":  {"label": "Контакт",  "target": "index.html#kontakt"},
    "kariera":  {"label": "Кариера",  "target": "index.html#kariera"},
    "novosti":  {"label": "Новости",  "target": "novosti.html"},
    "pocetna":  {"label": "Почетна",  "target": "index.html"},
}


PROMPT = """
Ти си систем што препознава дали корисникот сака да биде однесен до некоја секција на сајтот.

Достапни дестинации:
- "lekari"  → секција со сите лекари
- "uslugi"  → секција со услуги (оддели/специјалности)
- "kontakt" → секција со контакт-форма и информации
- "kariera" → секција со огласи за работа
- "novosti" → страна со вести
- "pocetna" → почетна страна

Корисникот пишува на македонски. Врати САМО JSON:
{"destinacija": "lekari" | "uslugi" | "kontakt" | "kariera" | "novosti" | "pocetna" | null}

Правила:
- „лекари", „сите лекари", „медицински тим", „доктори" → "lekari"
- „услуги", „оддели", „специјалности", „што нудите" → "uslugi"
- „контакт", „телефон", „каде сте", „адреса" → "kontakt"
- „кариера", „кариери", „работа", „вработување", „вработувања",
  „огласи за работа", „сите огласи", „слободни позиции",
  „слободни работни места", „имате ли работа",
  „сакам да аплицирам", „како да аплицирам", „сакам да работам кај вас",
  „дали може да аплицирам за X", „сакам да се вработам" → "kariera"
- „новости", „вести", „сите вести" → "novosti"
- „почетна", „home", „главна страна" → "pocetna"
- ако не е јасно → null

ВАЖНО: „креирај/нов/објави оглас" НЕ е навигација (тоа е креирање) → null.

БЕЗ markdown, БЕЗ објаснувања. Само JSON.
""".strip()


def _izvlechi(prashanje: str) -> dict:
    odgovor = ask_ai(f"Прашање: „{prashanje}\"", system_prompt=PROMPT)
    print(f"[navigacija] AI: {odgovor!r}")

    if "Привремено сум" in odgovor or "Привремена грешка" in odgovor:
        return {"_error": odgovor}

    cist = re.sub(r"^```(?:json)?|```$", "", odgovor.strip()).strip()
    try:
        return json.loads(cist)
    except Exception:
        return {}


def odgovori_za_navigacija(prashanje: str) -> dict:
    """
    Враќа dict со 2 ставки:
    - odgovor: текст да го прикажеме во чатот
    - navigacija: dict со {target, label} - frontend-от ќе скрола/пренасочи
    """
    podatoci = _izvlechi(prashanje)
    if podatoci.get("_error"):
        return {"odgovor": podatoci["_error"]}

    dest = (podatoci.get("destinacija") or "").strip().lower()
    if dest not in DESTINACII:
        return {
            "odgovor": (
                'Не разбрав каде да те однесам. Може да побараш:\n'
                '• „Покажи ми ги лекарите"\n'
                '• „Покажи ги услугите"\n'
                '• „Каде е контакт?"\n'
                '• „Однеси ме на новости"\n'
                '• „Прикажи кариера"'
            )
        }

    cel = DESTINACII[dest]
    odgovor = f'Те носам кон „{cel["label"]}"...'

    if dest == "lekari":
        try:
            from ai.pacient.slobodni_termini import zimi_site_lekari

            lek = zimi_site_lekari()
            if lek:
                delovi = [odgovor, "", "Краток преглед на лекарскиот тим:", ""]
                for l in lek[:24]:
                    spec = (l.get("specialty") or "—").strip() or "—"
                    delovi.append(f"- Д-р {l['name']} {l['surname']} — {spec}")
                if len(lek) > 24:
                    delovi.append("")
                    delovi.append(f"(Уште {len(lek) - 24} лекари во секцијата „Лекари".)")
                odgovor = "\n".join(delovi)
        except Exception as e:
            print(f"[navigacija] greshka pri lista lekari: {e}")

    return {
        "odgovor": odgovor,
        "navigacija": {"target": cel["target"], "label": cel["label"]},
    }
