"""
Бришење вест или оглас — само за директорот (AI + MySQL).

Примери:
- „Избриши го најновиот оглас"  → последен оглас
- „Избриши ја најновата вест"   → последна вест
- „Избриши оглас ID 5"          → по ID
- „Избриши ја истата"           → last_vest_id од контекст (по објава)
"""

from typing import Any

from ai._kernel.ai_json import parse_ai_json
from ai._kernel.auth import require_direktor
from ai._kernel.db_helpers import ai_error_text, db_cursor, fetch_one, normalize_int
from ai._kernel.groq_client import GROQ_OFFLINE_MSG, ask_ai, groq_e_isklucen
from ai._kernel.groq_helpers import groq_zadolzhitelen
from ai._kernel.prompt_loader import load_prompt
from ai.opsto.vest_naslov import prasanje_e_izbrisi_po_kontekst, pronajdi_vest_po_naslov


def _izvlechi(prasanje: str, kontekst: dict | None = None) -> dict[str, Any]:
    """AI враќа dict со tip / id / kriterium / naslov."""
    if msg := groq_zadolzhitelen():
        return {"_error": msg}

    user = f'Прашање: „{prasanje}"'
    if kontekst and kontekst.get("last_vest_id"):
        user += f"\nКонтекст: последно објавена вест ID={kontekst['last_vest_id']}."

    odgovor = ask_ai(user, system_prompt=load_prompt("direktor_izbrisi_vest_oglas"))
    print(f"[izbrisi] AI: {odgovor!r}")
    return parse_ai_json(odgovor, log_tag="izbrisi_vest_oglas")


def _izbrisi_vest(target_id: int | None) -> str:
    """Брише вест по ID или најновата."""
    with db_cursor() as (conn, cur):
        if target_id:
            cur.execute("SELECT id, naslov FROM Novosti WHERE id = %s", (target_id,))
        else:
            cur.execute(
                "SELECT id, naslov FROM Novosti ORDER BY created_at DESC, id DESC LIMIT 1"
            )

        vest = fetch_one(cur)
        if not vest:
            if target_id:
                return f"Не најдов вест со ID {target_id}."
            return "Немате вести во базата."

        vest_id = int(vest["id"])
        naslov = str(vest.get("naslov") or "")
        cur.execute("DELETE FROM Novosti WHERE id = %s", (vest_id,))
        conn.commit()

    return f"Вест е избришана.\n\nID: {vest_id}\nНаслов: {naslov}"


def _izbrisi_oglas(target_id: int | None) -> str:
    """Брише оглас по ID или најновиот."""
    with db_cursor() as (conn, cur):
        if target_id:
            cur.execute(
                "SELECT id_oglas, pozicija, oddel FROM Vrabotuvanje WHERE id_oglas = %s",
                (target_id,),
            )
        else:
            cur.execute(
                "SELECT id_oglas, pozicija, oddel FROM Vrabotuvanje"
                " ORDER BY datum_na_objava DESC, id_oglas DESC LIMIT 1"
            )

        oglas = fetch_one(cur)
        if not oglas:
            if target_id:
                return f"Не најдов оглас со ID {target_id}."
            return "Немате огласи во базата."

        oglas_id = int(oglas["id_oglas"])
        pozicija = str(oglas.get("pozicija") or "")
        oddel = str(oglas.get("oddel") or "")
        cur.execute("DELETE FROM Vrabotuvanje WHERE id_oglas = %s", (oglas_id,))
        conn.commit()

    return (
        f"Огласот е избришан.\n\n"
        f"ID: {oglas_id}\n"
        f"Позиција: {pozicija}\n"
        f"Оддел: {oddel}"
    )


def odgovori_za_brisenje(
    prasanje: str, lekar: dict | None, kontekst: dict | None = None
) -> str:
    """Главна точка — повикана од router-от."""
    if err := require_direktor(lekar):
        return err

    # „Избриши ја истата“ — ID од UI контекст (не keyword NLP)
    if prasanje_e_izbrisi_po_kontekst(prasanje, kontekst) and kontekst:
        vid = kontekst.get("last_vest_id")
        if vid:
            return _izbrisi_vest(int(vid))

    if groq_e_isklucen():
        return GROQ_OFFLINE_MSG

    podatoci = _izvlechi(prasanje, kontekst)
    if msg := ai_error_text(podatoci):
        return msg

    tip = (podatoci.get("tip") or "").strip().lower()
    target_id = normalize_int(podatoci.get("id"))
    kriterium = (podatoci.get("kriterium") or "").strip().lower() or None

    if kriterium == "najnov":
        target_id = None

    if tip not in ("vest", "oglas"):
        return (
            "Не разбирам што да избришам. Пример:\n"
            "• „Избриши го најновиот оглас\"\n"
            "• „Избриши ја најновата вест\"\n"
            "• „Избриши оглас ID 5\""
        )

    if tip == "vest":
        naslov_ai = (podatoci.get("naslov") or "").strip()
        if kriterium == "naslov" or naslov_ai:
            vest = pronajdi_vest_po_naslov(naslov_ai or prasanje)
            if vest:
                return _izbrisi_vest(int(vest["id"]))
            return (
                "Не најдов вест со тој наслов.\n\n"
                "Проверете го насловот или наведете ID, на пр. „Избриши вест 3“."
            )
        return _izbrisi_vest(target_id)
    return _izbrisi_oglas(target_id)
