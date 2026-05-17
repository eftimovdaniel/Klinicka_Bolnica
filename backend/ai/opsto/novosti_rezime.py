"""
Краток преглед на последните новости од базата (+ Groq резиме).

Примери:
- „Што има ново?“
- „Резиме на последните новости“
"""

from ai._kernel.db_helpers import as_dict, db_cursor
from ai._kernel.odgovor_formatter import formatiraj_odgovor_so_ai

# Иста релативна патека како во navigacija.py (frontend со static сервер)
NOVOSTI_STRANICA = "novosti.html"
# Frontend го претвора [[Новости|novosti.html]] во кликабилен линк
NOVOSTI_LINK = f"[[Новости|{NOVOSTI_STRANICA}]]"
POTPIS = "[[center]]Ви благодариме\nКлиничка Болница Штип[[/center]]"


def odgovori_za_novosti_rezime() -> str:
    try:
        with db_cursor() as (_, cur):
            cur.execute(
                """
                SELECT naslov
                FROM Novosti
                ORDER BY created_at DESC
                LIMIT 3
                """
            )
            rows = cur.fetchall() or []
    except Exception as e:
        print(f"[novosti_rezime] DB: {e}")
        return (
            "Моментално не можам да ги вчитам новостите. "
            f"Отворете ја страницата {NOVOSTI_LINK} или пробајте подоцна.\n\n"
            f"{POTPIS}"
        )

    if not rows:
        return (
            f"Нема објавени новости во моментов. Следете ги на {NOVOSTI_LINK} кога ќе има нови објави.\n\n"
            f"{POTPIS}"
        )

    linii = ["Последни објави на сајтот:\n"]
    for r in rows:
        row = as_dict(r)
        naslov = (row.get("naslov") or "Без наслов").strip()
        linii.append(f"•{naslov}")

    linii.append(
        "\nЦелата содржина на овие вести, но и на останатите може да ја погледнете на "
        f"{NOVOSTI_LINK}.\n\n"
        f"{POTPIS}"
    )
    sablon = "\n".join(linii)
    naslovi = []
    for r in rows:
        row = as_dict(r)
        naslovi.append((row.get("naslov") or "Без наслов").strip())

    podatoci = {
        "broj_novosti": len(naslovi),
        "naslovi": naslovi,
        "link_novosti": NOVOSTI_LINK,
        "potpis": POTPIS,
        "sledna_akcija": f"Повеќе детали на {NOVOSTI_LINK}.",
    }
    return formatiraj_odgovor_so_ai("novosti_rezime", podatoci, sablon)
