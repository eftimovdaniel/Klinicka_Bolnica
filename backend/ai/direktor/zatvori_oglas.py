import re
from database import get_connection
from ai._kernel.auth import require_direktor
from ai._kernel.ai_json import parse_ai_json
from ai._kernel.groq_client import ask_ai
PROMPT = """
Ти си систем што извлекува податоци за затворање оглас за работа. Корисникот е директор и сака да затвори оглас (status → „истечен"). Врати САМО JSON:
{"id": число | null, "pozicija": "текст" | null, "site": true | false}
Правила:
- Ако корисникот спомне ID на оглас → "id"=число.
- Ако корисникот спомне позиција (пр. „кардиолог", „медицинска сестра") → "pozicija"=текст.
- Ако корисникот вели „сите огласи", „сите" → "site"=true.
- Ако нема ништо јасно → сите вредности null/false. БЕЗ markdown, БЕЗ објаснувања. Само JSON. """.strip()

def _izvlechi(prasanje: str) -> dict:
    odgovor = ask_ai(f"Прашање: „{prasanje}\"", system_prompt=PROMPT)
    print(f"[zatvori_oglas] AI: {odgovor!r}")
    return parse_ai_json(odgovor, log_tag="zatvori_oglas")

def _zatvori_po_id(target_id: int) -> str:
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT id_oglas, pozicija, oddel, status_oglas FROM Vrabotuvanje WHERE id_oglas = %s",
        (target_id,),
    )
    oglas = cur.fetchone()
    if not oglas:
        cur.close()
        conn.close()
        return f"Не најдов оглас со ID {target_id}."

    if (oglas["status_oglas"] or "").lower() == "истечен":
        cur.close()
        conn.close()
        return f'Огласот „{oglas["pozicija"]}" (ID {target_id}) веќе е истечен.'

    cur2 = conn.cursor()
    cur2.execute(
        "UPDATE Vrabotuvanje SET status_oglas='истечен' WHERE id_oglas = %s",
        (target_id,),
    )
    conn.commit()
    cur.close()
    cur2.close()
    conn.close()

    return (
        f"Огласот е затворен (статус: истечен).\n\n"
        f"ID: {oglas['id_oglas']}\n"
        f"Позиција: {oglas['pozicija']}\n"
        f"Оддел: {oglas['oddel']}"
    )
def _zatvori_po_pozicija(pozicija: str) -> str:
    """Барај активен оглас со таа позиција (или близок match)."""
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    p = f"%{pozicija.lower()}%"
    cur.execute(
        "SELECT id_oglas, pozicija, oddel, status_oglas FROM Vrabotuvanje"
        " WHERE LOWER(pozicija) LIKE %s AND COALESCE(LOWER(status_oglas),'') <> 'истечен'"
        " ORDER BY datum_na_objava DESC",
        (p,),
    )
    rows = cur.fetchall()
    if not rows:
        cur.close()
        conn.close()
        return f'Не најдов активен оглас за „{pozicija}".'

    if len(rows) > 1:
        cur.close()
        conn.close()
        lista = "\n".join(f"• ID {r['id_oglas']}: {r['pozicija']} ({r['oddel']})" for r in rows[:5])
        return (
            f'Најдов повеќе огласи за „{pozicija}":\n{lista}\n\n'
            f'Те молам прецизирај, пр. „Затвори оглас ID {rows[0]["id_oglas"]}".'
        )
    oglas = rows[0]
    cur2 = conn.cursor()
    cur2.execute(
        "UPDATE Vrabotuvanje SET status_oglas='истечен' WHERE id_oglas = %s",
        (oglas["id_oglas"],),
    )
    conn.commit()
    cur.close()
    cur2.close()
    conn.close()

    return (
        f"Огласот е затворен (статус: истечен).\n\n"
        f"ID: {oglas['id_oglas']}\n"
        f"Позиција: {oglas['pozicija']}\n"
        f"Оддел: {oglas['oddel']}"
    )
def _zatvori_site() -> str:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE Vrabotuvanje SET status_oglas='истечен'"
        " WHERE COALESCE(LOWER(status_oglas),'') <> 'истечен'"
    )
    promeneti = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    if promeneti == 0:
        return "Нема активни огласи за затворање."
    return f"Затворени се {promeneti} огласи (статус: истечен)."

def odgovori_za_zatvoranje_oglas(prasanje: str, lekar: dict | None) -> str:
    """Главна точка - повикана од router-от."""
    if err := require_direktor(lekar):
        return err
    podatoci = _izvlechi(prasanje)
    if podatoci.get("_error"):
        return podatoci["_error"]
    if podatoci.get("site"):
        return _zatvori_site()
    target_id = podatoci.get("id")
    if target_id:
        try:
            return _zatvori_po_id(int(target_id))
        except (TypeError, ValueError):
            pass
    pozicija = (podatoci.get("pozicija") or "").strip()
    if pozicija:
        return _zatvori_po_pozicija(pozicija)
    return (
        'Не разбирам кој оглас да го затворам. Пример:\n'
        '• „Затвори го огласот за кардиолог"\n'
        '• „Затвори оглас ID 5"\n'
        '• „Затвори ги сите огласи"'
    )
