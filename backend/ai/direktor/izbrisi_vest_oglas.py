"""
Бришење вест или оглас — само за директорот (правила + AI, локално за „истата").

Примери:
- „Избриши го најновиот оглас"           → DELETE од Vrabotuvanje (последниот)
- „Избриши ја најновата вест"            → DELETE од Novosti (последната)
- „Избриши ја веста со наслов …"         → DELETE по наслов од Novosti
- „Избриши оглас ID 5"                   → DELETE Vrabotuvanje WHERE id=5
- „Избриши вест 3"                       → DELETE Novosti WHERE id=3
"""

import re
from typing import Any

from ai._kernel.ai_json import parse_ai_json
from ai._kernel.auth import require_direktor
from ai._kernel.db_helpers import ai_error_text, db_cursor, fetch_one, normalize_int
from ai._kernel.groq_client import GROQ_OFFLINE_MSG, ask_ai, groq_e_isklucen
from ai._kernel.prompt_loader import load_prompt
from ai._kernel.transliteracija import transliterijaj
from ai.opsto.vest_naslov import (
    prasanje_e_izbrisi_po_kontekst,
    prasanje_e_izbrisi_vest_oglas,
    prasanje_ima_brisenje_marker,
    pronajdi_vest_po_naslov,
)


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


def _lokalno_izvlechi_brisenje(
    prasanje: str, kontekst: dict | None
) -> tuple[str, int | None] | None:
    """('vest'|'oglas', id|None) без Groq."""
    if not prasanje_ima_brisenje_marker(prasanje):
        return None
    p = transliterijaj(prasanje).lower()
    e_oglas = any(w in p for w in ("оглас", "oglas")) and not any(
        w in p for w in ("вест", "новост", "vest", "novost", "наслов")
    )
    if e_oglas:
        m = re.search(r"(?:оглас|oglas)\s*(?:id)?\s*[#:]?\s*(\d+)", p)
        return ("oglas", int(m.group(1)) if m else None)

    if prasanje_e_izbrisi_po_kontekst(prasanje, kontekst):
        return ("vest", int(kontekst["last_vest_id"]))  # type: ignore[index]

    m = re.search(r"(?:вест|новост|vest|novost)\s*(?:id)?\s*[#:]?\s*(\d+)", p)
    if m:
        return ("vest", int(m.group(1)))

    vest = pronajdi_vest_po_naslov(prasanje)
    if vest:
        return ("vest", int(vest["id"]))

    if any(w in p for w in ("најнов", "последн", "najnov", "posledn")):
        return ("vest", None)

    if prasanje_e_izbrisi_vest_oglas(prasanje, kontekst):
        return ("vest", None)

    return None


def odgovori_za_brisenje(
    prasanje: str, lekar: dict | None, kontekst: dict | None = None
) -> str:
    """Главна точка - повикана од router-от."""
    if err := require_direktor(lekar):
        return err

    if prasanje_e_izbrisi_po_kontekst(prasanje, kontekst) and kontekst:
        vid = kontekst.get("last_vest_id")
        if vid:
            return _izbrisi_vest(int(vid))

    if groq_e_isklucen():
        return GROQ_OFFLINE_MSG

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
        kriterium = (podatoci.get("kriterium") or "").strip().lower()
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
