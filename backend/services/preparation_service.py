import json
import os
import re
import threading
from typing import Any, Dict, List, Optional, Tuple

# Lokacija na JSON fajlot relativno na ovoj modul
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA_PATH = os.path.join(_BASE_DIR, "data", "preparation_instructions.json")

# Cache za vchitanata data (eden vchit po proces dovolen e)
_cache_lock = threading.Lock()
_cache: Optional[Dict[str, Any]] = None


def _normalize_text(s: str) -> str:
    """Mali bukvi + ednostaven prostor kompakt. Za sporedba na klucni zborovi."""
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def load_preparations() -> Dict[str, Any]:
    """Vchituva i kesira JSON fajl. Vrakame celiot data dict.
    Ako fajlot ne postoi ili ima parsing greska - vrakame prazna struktura
    (agentot nema da padne, samo nema podgotovki za nudenje).
    """
    global _cache
    with _cache_lock:
        if _cache is not None:
            return _cache
        try:
            with open(_DATA_PATH, "r", encoding="utf-8") as f:
                _cache = json.load(f)
        except FileNotFoundError:
            print(f"[preparation_service] WARN: ne najdov {_DATA_PATH}")
            _cache = {"preparations": []}
        except json.JSONDecodeError as e:
            print(f"[preparation_service] ERROR: JSON parsing failed: {e}")
            _cache = {"preparations": []}
        return _cache


def reload_preparations() -> Dict[str, Any]:
    """Forsiraj povtorno vchituvanje (korisno pri update na JSON bez restart)."""
    global _cache
    with _cache_lock:
        _cache = None
    return load_preparations()


def _score_match(prompt_lower: str, keywords: List[str], title_lower: str) -> int:
    """Brojaime kolku klucni zborovi/naslov se sodrzat vo prompt-ot.
    Pogolem skor = podobar match. 0 = nema poklopuvanje.
    Naslov-poklopuvanjeto nosi pomalku skor od klucni zborovi (zato klucni zborovi se primarni).
    """
    if not prompt_lower:
        return 0
    score = 0
    for kw in keywords or []:
        kw_low = _normalize_text(kw)
        if not kw_low:
            continue
        # cel zbor ili substring match - i dvete brojaat
        if kw_low in prompt_lower:
            # podolg klucen zbor = pogolem skor (poprecizno poklopuvanje)
            score += max(2, len(kw_low.split()))
    # naslov poklopuvanje (sekoj zbor od naslovot dodava pomal bonus)
    for word in title_lower.split():
        if len(word) >= 4 and word in prompt_lower:
            score += 1
    return score


def match_preparation(prompt: str) -> Optional[Dict[str, Any]]:
    """Najdi najdobar match za korisniciot prompt.
    Vrakame None ako nieden zapis nema znacaen match (skor < 2).
    """
    data = load_preparations()
    items = data.get("preparations", []) or []
    if not items or not prompt:
        return None

    prompt_lower = _normalize_text(prompt)
    best: Tuple[int, Optional[Dict[str, Any]]] = (0, None)
    for item in items:
        title_lower = _normalize_text(item.get("title", ""))
        score = _score_match(prompt_lower, item.get("keywords", []), title_lower)
        if score > best[0]:
            best = (score, item)

    # Prag: barem 2 poena za da prifatime match (izbegnuva slucajni poklopuvanja)
    if best[0] >= 2 and best[1] is not None:
        return best[1]
    return None


def list_available_titles() -> List[str]:
    """Vrakame lista na site naslovi (korisno koga AI ne moze da pogodi - nudime izbor)."""
    data = load_preparations()
    return [item.get("title", "") for item in data.get("preparations", []) if item.get("title")]


def find_preparation_by_id(prep_id: str) -> Optional[Dict[str, Any]]:
    """Naogja zapis po id (za API endpoint koj prikazuva detali za specificna podgotovka)."""
    data = load_preparations()
    target = _normalize_text(prep_id)
    for item in data.get("preparations", []) or []:
        if _normalize_text(item.get("id", "")) == target:
            return item
    return None


def format_preparation_message(item: Dict[str, Any]) -> str:
    """Pretvora JSON zapis vo chitlivo tekstualno upatstvo na makedonski.
    Strukturata vo poraka: naslov, gladuvanje, koraci, sto da donese, predupreduvanja.
    """
    if not item:
        return ""

    title = item.get("title", "Подготовка").strip()
    lines: List[str] = [f"📋 Подготовка за: {title}", ""]

    # Gladuvanje (najvazna informacija) - prikazi prvo
    fasting = item.get("fasting") or {}
    if fasting.get("required"):
        hours = int(fasting.get("hours") or 0)
        line = f"🍽  Гладување: ЗАДОЛЖИТЕЛНО — {hours} часа без храна"
        note = (fasting.get("note") or "").strip()
        if note:
            line += f" ({note})"
        lines.append(line)
    else:
        note = (fasting.get("note") or "").strip()
        if note:
            lines.append(f"Гладување: не е задолжително. {note}")
        else:
            lines.append(" Гладување: не е потребно.")

    # Glavni instrukcii (poslednite tri ako se mnogu - pak gi prikazuvame site)
    instructions = item.get("instructions") or []
    if instructions:
        lines.append("")
        lines.append("Упатства:")
        for i, instr in enumerate(instructions, 1):
            lines.append(f"  {i}. {instr}")

    # Sto da donese
    what_to_bring = item.get("what_to_bring") or []
    if what_to_bring:
        lines.append("")
        lines.append("Понесете со себе:")
        for w in what_to_bring:
            lines.append(f"  • {w}")

    # Predupreduvanja
    warnings = item.get("warnings") or []
    if warnings:
        lines.append("")
        lines.append("Важно:")
        for w in warnings:
            lines.append(f"  ! {w}")

    # Traenje na pregledot ako e zapisano
    duration = item.get("duration_minutes")
    if duration:
        lines.append("")
        lines.append(f"Очекувано траење: {int(duration)} минути.")

    lines.append("")
    lines.append("ℹОвие упатства се општи. Секогаш проверете со вашиот лекар за конкретни забелешки.")
    return "\n".join(lines)


def build_unmatched_response_message() -> str:
    """Koga ne moze da pogodime za koja podgotovka prashuva pacientot,
    mu nudime lista na dostapni opcii."""
    titles = list_available_titles()
    if not titles:
        return (
            "Во моментов не располагам со упатства за подготовка. "
            "Ве молам обратете се на вашиот лекар или болничкиот персонал."
        )

    lines = [
        "Не успеав да препознам за која подготовка прашувате.",
        "Можам да ви помогнам со упатства за:",
        "",
    ]
    for title in titles:
        lines.append(f"• {title}")
    lines.append("")
    lines.append('Напишете го името на испитувањето (на пр. „крвна слика", „ЕКГ", „ултразвук на абдомен").')
    return "\n".join(lines)
