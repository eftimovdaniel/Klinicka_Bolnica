"""
Servis za FAQ - chesto postavuvani prashanja.

Architektura (RAG-lite):
  1. Pacient pita: „Koe e rabotno vreme na laboratorijata?"
  2. _match_faqs_in_db() - vlece TOP-N relevantni zapisi od FAQ tabela po
     klucni zborovi (MATCH AGAINST + LIKE fallback)
  3. _answer_with_google_ai() - prakja prashanjeto + tie zapisi na Gemini
     i bara prirooden odgovor (so kontekst, ne samo copy-paste)
  4. Ako AI ne raboti, _build_static_response() vrakja prv najden FAQ kako fallback.

Predusovi:
  - GOOGLE_API_KEY vo .env (za prirooden odgovor)
  - Bez API key - sistemot pak raboti, samo so staticki odgovor.

Dependencies: koristi database.get_connection (postoeci pattern) i
  services.google_ai_client.chat_safe (postoeci klient za Gemini).
"""
import re
from typing import Any, Dict, List, Optional

from database import get_connection
from services.google_ai_client import chat_safe

# Maksimum FAQ zapisi koi se prakaat na AI kako kontekst.
# Premalo - AI nema dovolno informacii. Premnogu - prashanje stane skapo i bavno.
MAX_FAQ_CANDIDATES = 5

# Minimum dolzhina na korisniciot prompt za da gi pobaravme od baza.
# Tekstovi pomali od ova - sigurno se ne-FAQ (kratke komandi).
MIN_PROMPT_LEN = 3


def _normalize(s: str) -> str:
    """Mali bukvi + tab-only space, za poklopuvanje."""
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def _split_keywords(klucni_zborovi: str) -> List[str]:
    """Klucni zborovi se sklanjat kako 'lab, raboto vreme, kako'.
    Razbivame i trimame.
    """
    if not klucni_zborovi:
        return []
    return [k.strip().lower() for k in str(klucni_zborovi).split(",") if k.strip()]


def _score_faq_row(prompt_lower: str, row: Dict[str, Any]) -> int:
    """Eden FAQ zapis - kolku poena dava za daden prompt.
    Logika:
      - Glaven prashanje: ako celiot prompt e podstring -> +10
      - Klucen zbor: za sekoj klucen zbor sodrzan vo prompt -> +3
      - Kategorija: ako kategorija e vo prompt -> +1
    """
    if not prompt_lower:
        return 0
    score = 0
    prashanje = _normalize(row.get("prashanje", ""))
    if prashanje and (prashanje in prompt_lower or prompt_lower in prashanje):
        score += 10
    for kw in _split_keywords(row.get("klucni_zborovi", "")):
        if not kw:
            continue
        if kw in prompt_lower:
            # podolg klucen zbor = poprecizno = pogolem skor
            score += max(3, len(kw.split()) + 2)
    kat = _normalize(row.get("kategorija", ""))
    if kat and kat in prompt_lower:
        score += 1
    return score


def _match_faqs_in_db(prompt: str, limit: int = MAX_FAQ_CANDIDATES) -> List[Dict[str, Any]]:
    """Vrakame TOP-N FAQ zapisi po relevantnost za korisniciot prompt.
    Strategija (vo prioriteten redosled):
      1. Probaj MySQL FULLTEXT search (najbrzo, semantichko)
      2. Padni na Python score-iranje vo memorija (sekogash raboti)
    """
    prompt_clean = _normalize(prompt)
    if len(prompt_clean) < MIN_PROMPT_LEN:
        return []

    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)

        # Probaj prvo FULLTEXT (povrzano so FT indeksot na FAQ).
        # IN NATURAL LANGUAGE MODE - dobro za seloboden tekst.
        try:
            cur.execute(
                """
                SELECT faq_ID, prashanje, odgovor, kategorija, klucni_zborovi,
                       MATCH (prashanje, odgovor, klucni_zborovi)
                         AGAINST (%s IN NATURAL LANGUAGE MODE) AS relevance
                FROM FAQ
                WHERE aktiven = 1
                  AND MATCH (prashanje, odgovor, klucni_zborovi)
                        AGAINST (%s IN NATURAL LANGUAGE MODE)
                ORDER BY relevance DESC
                LIMIT %s
                """,
                (prompt_clean, prompt_clean, int(limit)),
            )
            ft_rows = cur.fetchall() or []
            if ft_rows:
                cur.close()
                return ft_rows
        except Exception:
            # Ako FULLTEXT pucna (na pr. premalku zborovi za stopwords),
            # padaj na klasichen Python score-iranje.
            pass

        # Fallback: vlechi site i score-iraj vo Python
        cur.execute(
            """
            SELECT faq_ID, prashanje, odgovor, kategorija, klucni_zborovi
            FROM FAQ
            WHERE aktiven = 1
            """
        )
        all_rows = cur.fetchall() or []
        cur.close()

        scored = []
        for row in all_rows:
            sc = _score_faq_row(prompt_clean, row)
            if sc > 0:
                scored.append((sc, row))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored[:limit]]
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _increment_usage_count(faq_ids: List[int]) -> None:
    """Inkrementira pati_iskoristen za zapisite koi bea koristeni vo posledniot odgovor.
    Analitika - ne e kritichno za funkcionalnost, ako padne tihu padne.
    """
    if not faq_ids:
        return
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        placeholders = ",".join(["%s"] * len(faq_ids))
        cur.execute(
            f"UPDATE FAQ SET pati_iskoristen = pati_iskoristen + 1 WHERE faq_ID IN ({placeholders})",
            tuple(int(i) for i in faq_ids),
        )
        conn.commit()
        cur.close()
    except Exception:
        pass
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _build_ai_system_prompt() -> str:
    """System poraka za Gemini - kazuvame mu kako da se odnesuva."""
    return (
        "Ти си љубезен и професионален асистент во Клиничка Болница Штип. "
        "Одговарај исклучиво на македонски јазик. "
        "Користи ги ИСКЛУЧИВО податоците дадени во контекст за да формираш одговор. "
        "Ако контекстот не содржи доволно информации за прашањето, "
        "одговори: „За ова прашање немам точна информација. Ве молам контактирајте ја "
        "болницата на 032/550-500.\" "
        "Не измислувај информации. Не изнесувај медицински дијагнози или совети. "
        "Биди концизен (3-6 реченици), пријатен и со јасна структура. "
        "Не повторувај го прашањето на корисникот. "
        "Не пиши JSON или код - само природен текст на македонски."
    )


def _build_ai_user_prompt(prompt: str, candidates: List[Dict[str, Any]]) -> str:
    """User poraka so kontekst za Gemini.
    Ja gradime od najdenите FAQ zapisi - tie se 'knowledge base'.
    """
    lines = [
        "Контекст (тоа што го знаеш за Клиничка Болница Штип):",
        "",
    ]
    for i, c in enumerate(candidates, 1):
        q = (c.get("prashanje") or "").strip()
        a = (c.get("odgovor") or "").strip()
        lines.append(f"[{i}] Прашање: {q}")
        lines.append(f"    Одговор: {a}")
        lines.append("")
    lines.append("Корисникот пита:")
    lines.append(f'  "{(prompt or "").strip()}"')
    lines.append("")
    lines.append(
        "Одговори на корисникот на природен и пријателски начин, "
        "користејќи ги горните информации од контекстот. "
        "Ако прашањето не одговара на ниту еден од дадените записи, "
        "кажи дека немаш точна информација."
    )
    return "\n".join(lines)


def _answer_with_google_ai(prompt: str, candidates: List[Dict[str, Any]]) -> Optional[str]:
    """Praka prashanje + relevantni FAQ na Gemini i vrakja prirooden odgovor.
    Vrakame None ako AI ne uspee (mrezha, API key, timeout) - togash povikuvac padaj na static.
    """
    if not candidates:
        return None
    system = _build_ai_system_prompt()
    user = _build_ai_user_prompt(prompt, candidates)
    response = chat_safe(system, user)
    if not response or not response.strip():
        return None
    return response.strip()


def _build_static_response(candidates: List[Dict[str, Any]]) -> str:
    """Ako AI ne raboti, prosto vrati prv match - chist FAQ odgovor."""
    if not candidates:
        return ""
    first = candidates[0]
    answer = (first.get("odgovor") or "").strip()
    if not answer:
        return ""
    return answer


def answer_faq(prompt: str) -> Optional[Dict[str, Any]]:
    """Glavna javna funkcija - vrakja gotov odgovor za AI agent intent.
    Vrakja dict so:
      - message: gotov tekst za pacientot
      - matched_faq_ids: lista na FAQ ID koi bea koristeni
      - source: 'ai' (Gemini) ili 'static' (direkten DB odgovor) ili 'none'
    Ili None ako voopjasto nema relevantni FAQ zapisi.
    """
    candidates = _match_faqs_in_db(prompt)
    if not candidates:
        return None

    faq_ids = [int(c.get("faq_ID")) for c in candidates if c.get("faq_ID")]

    # 1) Probaj so Google AI - prirooden, prijaten odgovor
    ai_answer = _answer_with_google_ai(prompt, candidates)
    if ai_answer:
        _increment_usage_count(faq_ids)
        return {
            "message": ai_answer,
            "matched_faq_ids": faq_ids,
            "source": "ai",
            "related_questions": [c.get("prashanje") for c in candidates if c.get("prashanje")],
        }

    # 2) Static fallback - prv najden FAQ
    static_answer = _build_static_response(candidates)
    if static_answer:
        _increment_usage_count([faq_ids[0]] if faq_ids else [])
        return {
            "message": static_answer,
            "matched_faq_ids": [faq_ids[0]] if faq_ids else [],
            "source": "static",
            "related_questions": [c.get("prashanje") for c in candidates if c.get("prashanje")],
        }

    return None


def list_active_faqs(kategorija: Optional[str] = None) -> List[Dict[str, Any]]:
    """Vrakame site aktivni FAQ zapisi (za UI prikaz - dropdown, listing, kartichki).
    Opcionalno filtrira po kategorija.
    """
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        if kategorija:
            cur.execute(
                """
                SELECT faq_ID, prashanje, odgovor, kategorija
                FROM FAQ
                WHERE aktiven = 1 AND kategorija = %s
                ORDER BY pati_iskoristen DESC, faq_ID ASC
                """,
                (kategorija,),
            )
        else:
            cur.execute(
                """
                SELECT faq_ID, prashanje, odgovor, kategorija
                FROM FAQ
                WHERE aktiven = 1
                ORDER BY kategorija ASC, pati_iskoristen DESC, faq_ID ASC
                """
            )
        rows = cur.fetchall() or []
        cur.close()
        return rows
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def list_categories() -> List[Dict[str, Any]]:
    """Vrakame lista na kategorii so broj na zapisi (za UI grupiranje)."""
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT kategorija, COUNT(*) AS broj
            FROM FAQ
            WHERE aktiven = 1 AND kategorija IS NOT NULL
            GROUP BY kategorija
            ORDER BY broj DESC
            """
        )
        rows = cur.fetchall() or []
        cur.close()
        return rows
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def get_faq_by_id(faq_id: int) -> Optional[Dict[str, Any]]:
    """Vrakame ceo zapis po ID (za detalen prikaz)."""
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT faq_ID, prashanje, odgovor, kategorija, klucni_zborovi,
                   aktiven, pati_iskoristen, kreiran_na, azuriran_na
            FROM FAQ
            WHERE faq_ID = %s
            LIMIT 1
            """,
            (int(faq_id),),
        )
        row = cur.fetchone()
        cur.close()
        return row
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def build_unmatched_response_message() -> str:
    """Koga ne najdovme nieden relevanten FAQ zapis - vrakame korisna pomos."""
    return (
        "Не успеав да најдам соодветен одговор во базата на знаење. "
        "Можете да:\n"
        "  • Преобразите го прашањето со подруги зборови\n"
        "  • Прашате за: работно време, локации, упати, телефонски броеви, процедури\n"
        "  • Контактирате на 032 / 550 - 500 за директна помош"
    )
