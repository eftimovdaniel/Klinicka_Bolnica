"""
Навигација преку AI - пренасочи го корисникот до одредена секција на сајтот.

Примери:
- „Дај ми ги сите лекари во болницата"     → #lekari
- „Покажи ми ги услугите"                  → #uslugi
- „Каде е контакт?"                        → #kontakt
- „Прикажи ми кариера"                     → #kariera
- „Однеси ме на новости"                   → novosti.html
"""

import re

from database import get_connection
from ai._kernel.ai_json import parse_ai_json
from ai._kernel.db_helpers import as_dict
from ai._kernel.groq_client import ask_ai
from vrabotuvanje_helpers import fetch_aktivni_oglasi_rows, format_rok_datum


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
- „каде се лекарите", „каде се докторите", „каде се наоѓаат лекарите" → "lekari"
- „услуги", „оддели", „специјалности", „што нудите" → "uslugi"
- „контакт", „телефон", „каде сте", „адреса" → "kontakt"
- „кариера", „кариери", „работа", „вработување", „вработувања", „вработување во болницата",
  „огласи за работа", „сите огласи", „слободни позиции", „работни места", „работна позиција",
  „слободни работни места", „имате ли работа", „листа на огласи",
  „сакам да аплицирам", „како да аплицирам", „сакам да работам кај вас",
  „дали може да аплицирам за X", „сакам да се вработам" → "kariera"
- „новости", „вести", „сите вести" → "novosti"
- „почетна", „home", „главна страна" → "pocetna"
- ако не е јасно → null

ВАЖНО: „креирај/нов/објави оглас" НЕ е навигација (тоа е креирање) → null.

БЕЗ markdown, БЕЗ објаснувања. Само JSON.
""".strip()


def _aktivni_oglasi_za_kariera() -> list[dict]:
    """Ист филтер како GET /kariera — само важечки активни (рок >= денес)."""
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        rows = fetch_aktivni_oglasi_rows(cur)
        cur.close()
        out: list[dict] = []
        for raw in rows:
            r = as_dict(raw)
            out.append(
                {
                    "id_oglas": r.get("id_oglas"),
                    "pozicija": (r.get("pozicija") or "").strip(),
                    "oddel": (r.get("oddel") or "").strip(),
                    "rok": format_rok_datum(r.get("datum_na_prijavuvanje")),
                }
            )
        return out
    except Exception as e:
        print(f"[navigacija] greska pri citanje oglasi: {e}")
        return []
    finally:
        if conn and conn.is_connected():
            conn.close()


def _tekst_za_kariera(oglasi: list[dict]) -> str:
    """Текст за чат: листа на позиции или порака дека нема отворени."""
    uvod = (
        'Ве пренасочувам кон делот „Кариера" (работни позиции и пријавување) на почетната страница.\n\n'
    )
    if not oglasi:
        return (
            uvod
            + "Моментално нема отворени работни позиции за пријавување. "
            "Погледнете ја секцијата повторно подоцна или контактирајте ја централата за информации."
        )

    linii = [uvod + "Активни огласи (можете да се пријавите преку формата во секцијата):", ""]
    for o in oglasi:
        poz = o.get("pozicija") or "—"
        odd = o.get("oddel") or "—"
        rok = o.get("rok") or "—"
        linii.append(f"• {poz} — оддел: {odd}. Рок за пријава: {rok}.")
    linii.append("")
    linii.append('За апликација отворете ја секцијата „Кариера" и пополнете ја формата подолу на страницата.')
    return "\n".join(linii)


def _izvlechi(prasanje: str) -> dict:
    odgovor = ask_ai(f"Прашање: „{prasanje}\"", system_prompt=PROMPT)
    print(f"[navigacija] AI: {odgovor!r}")
    return parse_ai_json(odgovor, log_tag="navigacija")


def odgovori_za_navigacija(prasanje: str) -> dict:
    """
    Враќа dict со 2 ставки:
    - odgovor: текст да го прикажеме во чатот
    - navigacija: dict со {target, label} - frontend-от ќе скрола/пренасочи
    """
    podatoci = _izvlechi(prasanje)
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
            from ai.opsto.lekari_oddel import odgovor_navigacija_lekari

            return odgovor_navigacija_lekari()
        except Exception as e:
            print(f"[navigacija] greska pri navigacija lekari: {e}")
            odgovor = (
                'Ве пренасочувам кон делот „Лекари" на почетната страница. '
                "Листата со лекари ќе ја видите на екранот."
            )

    if dest == "kariera":
        oglasi = _aktivni_oglasi_za_kariera()
        odgovor = _tekst_za_kariera(oglasi)

    return {
        "odgovor": odgovor,
        "navigacija": {"target": cel["target"], "label": cel["label"]},
    }
