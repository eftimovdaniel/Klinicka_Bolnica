"""
Бришење вест или оглас преку AI - само за директорот.

Примери:
- „Избриши го најновиот оглас"           → DELETE од Vrabotuvanje (последниот)
- „Избриши ја најновата вест"            → DELETE од Novosti (последната)
- „Избриши оглас ID 5"                   → DELETE Vrabotuvanje WHERE id=5
- „Избриши вест 3"                       → DELETE Novosti WHERE id=3
"""

from typing import Any

from ai._kernel.ai_json import parse_ai_json
from ai._kernel.auth import require_direktor
from ai._kernel.db_helpers import ai_error_text, db_cursor, fetch_one, normalize_int
from ai._kernel.groq_client import ask_ai
from ai._kernel.prompt_loader import load_prompt


def _izvlechi(prasanje: str) -> dict[str, Any]:
    """AI враќа dict со tip/id/kriterium."""
    odgovor = ask_ai(
        f"Прашање: „{prasanje}\"",
        system_prompt=load_prompt("direktor_izbrisi_vest_oglas"),
    )
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


def odgovori_za_brisenje(prasanje: str, lekar: dict | None) -> str:
    """Главна точка - повикана од router-от."""
    if err := require_direktor(lekar):
        return err

    podatoci = _izvlechi(prasanje)
    if msg := ai_error_text(podatoci):
        return msg

    tip = (podatoci.get("tip") or "").strip().lower()
    target_id = normalize_int(podatoci.get("id"))

    if tip not in ("vest", "oglas"):
        low = prasanje.lower()
        if any(w in low for w in ("оглас", "oglas")):
            tip = "oglas"
        elif any(w in low for w in ("вест", "новост", "vest", "novost")):
            tip = "vest"
        else:
            return (
                "Не разбирам што да избришам. Пример:\n"
                "• „Избриши го најновиот оглас\"\n"
                "• „Избриши ја најновата вест\"\n"
                "• „Избриши оглас ID 5\""
            )

    if tip == "vest":
        return _izbrisi_vest(target_id)
    return _izbrisi_oglas(target_id)
