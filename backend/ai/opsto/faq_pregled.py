"""
FAQ за подготовка за преглед — прво JSON (брзо), потоа AI од agent_prompts (faq_pregled).

Податоци: backend/data/faq_pregled.json
"""

import json
from pathlib import Path

from ai._kernel.groq_client import ask_ai
from ai._kernel.prompt_loader import load_prompt

_JSON_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "faq_pregled.json"


def _load() -> dict:
    try:
        with open(_JSON_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[faq_pregled] читање JSON: {e}")
        return {}


def odgovori_za_faq_pregled(prashanje: str) -> str:
    p = (prashanje or "").lower().strip()
    if not p:
        return "Напиши го прашањето (на пр. дали на гладно, што да понесам на преглед)."

    data = _load()
    stavki_raw = data.get("stavki")
    stavki: list = stavki_raw if isinstance(stavki_raw, list) else []
    disclaimer = (data.get("disclaimer") or "").strip()
    default_odgovor = (data.get("default_odgovor") or "").strip()

    for st in stavki:
        if not isinstance(st, dict):
            continue
        kws = st.get("keywords") or []
        if not isinstance(kws, list):
            continue
        for kw in kws:
            if isinstance(kw, str) and kw.lower() in p:
                naslov = (st.get("naslov") or "").strip()
                odg = (st.get("odgovor") or "").strip()
                parts = []
                if naslov:
                    parts.append(f"**{naslov}**\n")
                parts.append(odg)
                if disclaimer:
                    parts.append(f"\n\n_{disclaimer}_")
                return "\n".join(parts)

    try:
        ai_odg = ask_ai(
            f'Прашање: „{prashanje}"',
            system_prompt=load_prompt("faq_pregled"),
        ).strip()
        if ai_odg:
            parts = [ai_odg]
            if disclaimer:
                parts.append(f"\n\n_{disclaimer}_")
            return "\n".join(parts)
    except Exception as e:
        print(f"[faq_pregled] AI fallback: {e}")

    out = [default_odgovor or "За конкретни барања за преглед контактирај ја рецепцијата (032/ 605-001)."]
    if disclaimer:
        out.append(f"\n\n_{disclaimer}_")
    return "\n".join(out)
