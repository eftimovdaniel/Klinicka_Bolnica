"""
Бришење вест или оглас преку AI - само за директорот.

Примери:
- „Избриши го најновиот оглас"           → DELETE од Vrabotuvanje (последниот)
- „Избриши ја најновата вест"            → DELETE од Novosti (последната)
- „Избриши оглас ID 5"                   → DELETE Vrabotuvanje WHERE id=5
- „Избриши вест 3"                       → DELETE Novosti WHERE id=3
"""

import json
import re

from database import get_connection
from ai.groq_client import ask_ai


PROMPT = """
Ти си систем што одредува што сака корисникот да избрише.

Корисникот е директор и може да брише ВЕСТ или ОГЛАС. Врати САМО JSON:
{"tip": "vest" | "oglas", "id": число | null, "kriterium": "najnov" | "id" | null}

Правила:
- "tip" мора да биде "vest" или "oglas" (на македонски: вест=новост, оглас=за работа/вработување).
- Ако корисникот спомне ID (бр.) → "id"=число, "kriterium"="id".
- Ако корисникот вели „најнов", „последен", „најновата", „последната" → "kriterium"="najnov", "id"=null.
- Ако не е јасно → "tip"=null.

БЕЗ markdown, БЕЗ објаснувања. Само JSON.
""".strip()


def _izvlechi(prashanje: str) -> dict:
    """AI враќа dict со tip/id/kriterium."""
    odgovor = ask_ai(f"Прашање: „{prashanje}\"", system_prompt=PROMPT)
    print(f"[izbrisi] AI: {odgovor!r}")

    if "Привремено сум" in odgovor or "Привремена грешка" in odgovor:
        return {"_error": odgovor}

    cist = re.sub(r"^```(?:json)?|```$", "", odgovor.strip()).strip()
    try:
        return json.loads(cist)
    except Exception:
        return {}


def _izbrisi_vest(target_id: int | None) -> str:
    """Брише вест по ID или најновата."""
    conn = get_connection()
    cur = conn.cursor(dictionary=True)

    if target_id:
        cur.execute("SELECT id, naslov FROM Novosti WHERE id = %s", (target_id,))
    else:
        cur.execute("SELECT id, naslov FROM Novosti ORDER BY created_at DESC, id DESC LIMIT 1")

    vest = cur.fetchone()
    if not vest:
        cur.close()
        conn.close()
        if target_id:
            return f"Не најдов вест со ID {target_id}."
        return "Немате вести во базата."

    cur2 = conn.cursor()
    cur2.execute("DELETE FROM Novosti WHERE id = %s", (vest["id"],))
    conn.commit()
    cur.close()
    cur2.close()
    conn.close()

    return f"Вест е избришана.\n\nID: {vest['id']}\nНаслов: {vest['naslov']}"


def _izbrisi_oglas(target_id: int | None) -> str:
    """Брише оглас по ID или најновиот."""
    conn = get_connection()
    cur = conn.cursor(dictionary=True)

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

    oglas = cur.fetchone()
    if not oglas:
        cur.close()
        conn.close()
        if target_id:
            return f"Не најдов оглас со ID {target_id}."
        return "Немате огласи во базата."

    cur2 = conn.cursor()
    cur2.execute("DELETE FROM Vrabotuvanje WHERE id_oglas = %s", (oglas["id_oglas"],))
    conn.commit()
    cur.close()
    cur2.close()
    conn.close()

    return (
        f"Огласот е избришан.\n\n"
        f"ID: {oglas['id_oglas']}\n"
        f"Позиција: {oglas['pozicija']}\n"
        f"Оддел: {oglas['oddel']}"
    )


def odgovori_za_brisenje(prashanje: str, lekar: dict | None) -> str:
    """Главна точка - повикана од router-от."""
    if not lekar or not lekar.get("doctor_ID"):
        return "Мораш прво да се најавиш како директор."

    from routers.admin import check_admin_access
    if not check_admin_access(lekar["doctor_ID"]):
        return "Само директорот може да брише вести и огласи."

    podatoci = _izvlechi(prashanje)
    if podatoci.get("_error"):
        return podatoci["_error"]

    tip = (podatoci.get("tip") or "").strip().lower()
    target_id = podatoci.get("id")

    # Дополнителна проверка: ако AI не препозна, пробај локално
    if tip not in ("vest", "oglas"):
        low = prashanje.lower()
        if any(w in low for w in ("оглас", "oglas")):
            tip = "oglas"
        elif any(w in low for w in ("вест", "новост", "vest", "novost")):
            tip = "vest"
        else:
            return (
                'Не разбирам што да избришам. Пример:\n'
                '• „Избриши го најновиот оглас"\n'
                '• „Избриши ја најновата вест"\n'
                '• „Избриши оглас ID 5"'
            )

    if tip == "vest":
        return _izbrisi_vest(target_id)
    return _izbrisi_oglas(target_id)
