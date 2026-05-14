"""
Краток преглед на последните новости од базата (без LLM).

Примери:
- „Што има ново?“
- „Резиме на последните новости“
"""

from typing import Any, cast

from database import get_connection

# Иста релативна патека како во navigacija.py (frontend со static сервер)
NOVOSTI_STRANICA = "novosti.html"


def odgovori_za_novosti_rezime() -> str:
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT id, naslov, created_at
            FROM Novosti
            ORDER BY created_at DESC
            LIMIT 3
            """
        )
        rows = cur.fetchall() or []
        cur.close()
    except Exception as e:
        print(f"[novosti_rezime] DB: {e}")
        return (
            "Моментално не можам да ги вчитам новостите. "
            f"Отвори ја страницата **{NOVOSTI_STRANICA}** на сајтот или пробај подоцна."
        )
    finally:
        if conn:
            conn.close()

    if not rows:
        return (
            f"Нема објавени новости во моментов. Следи на **{NOVOSTI_STRANICA}** кога ќе има објави."
        )

    linii = ["Последни објави на сајтот:\n"]
    for r in rows:
        row = cast(dict[str, Any], r)
        naslov = (row.get("naslov") or "Без наслов").strip()
        rid = row.get("id")
        linii.append(f"• **{naslov}** (ID {rid})")
    linii.append(
        f"\nЦелосна листа и содржина: отвори **{NOVOSTI_STRANICA}** (копче „Прочитај повеќе“ кај секоја вест)."
    )
    return "\n".join(linii)
